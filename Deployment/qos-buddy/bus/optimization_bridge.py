"""
Optimization bridge.

Subscribes to `qos.metrics.raw` and `qos.diagnosis`, forwards live telemetry
snapshots and diagnostic contracts to the *real* optimization agent, then calls
`/api/agent/decide` and publishes the returned decision as `ProposedActionEvent`
on `qos.action.proposed` so Network Consultant / the Operator dashboard can
render the actual agent payload.

The agent itself runs the multi-armed bandit, LLM reasoner, policy gate,
and optional Jira hand-off — we don't reproduce any of that here.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import httpx

from contracts.schemas import (
    Counterfactual,
    ImpactRadius,
    PolicyVerdict,
    ProposedActionEvent,
    RiskLevel,
    SafetyCheck,
    StreamName,
)

from .graceful import install_sigterm_handler
from .otel import flush_tracer, init_tracer
from .redis_streams import RedisStreamsBus, run_consumer

log = logging.getLogger("qos.bridge.optimization")

OPTIMIZATION_URL = os.getenv("OPTIMIZATION_URL", "http://optimization:8000")
OPTIMIZATION_TOKEN = os.getenv("OPTIMIZATION_TOKEN", "engineer-dev-token")
GROUP = os.getenv("OPTIMIZATION_GROUP", "optimization")
CONSUMER = os.getenv("OPTIMIZATION_CONSUMER", "optimization-1")
MONITORING_GROUP = os.getenv("OPTIMIZATION_MONITORING_GROUP", "optimization-monitoring")
MONITORING_CONSUMER = os.getenv("OPTIMIZATION_MONITORING_CONSUMER", "optimization-monitoring-1")
SNAPSHOT_COOLDOWN_S = float(os.getenv("OPTIMIZATION_SNAPSHOT_COOLDOWN_SECONDS", "5"))


def _verdict(safety_passed: bool, risk: RiskLevel) -> PolicyVerdict:
    if not safety_passed:
        return PolicyVerdict.REJECTED
    if risk == RiskLevel.LOW:
        return PolicyVerdict.AUTO
    return PolicyVerdict.DEFERRED


# Diagnostic agent's 8 RC codes → Optimization agent's PHASE3_ACTIONS keys.
# Codes the optimization agent doesn't have a contract for fall through to
# RC_NONE (observe-only) on the agent side.
_RC_TO_OPTIMIZATION = {
    "RC_CAPACITY_OVERLOAD": "RC_CAPACITY_OVERLOAD",
    "RC_TRANSPORT_DELAY": "RC_TRANSPORT_DELAY",
    "RC_RADIO_SIGNAL_WEAK": "RC_WEAK_SIGNAL",
    "RC_HANDOVER_INSTABILITY": "RC_HO_FAILURE",
    "RC_CQI_MISMATCH": "RC_CQI_MISMATCH",
    # Diagnostic-only codes — optimization treats as PRB-style congestion.
    "RC_PACKET_LOSS": "RC_PRB_CONGESTION",
    "RC_RETRANSMISSION": "RC_PRB_CONGESTION",
    "RC_JITTER_INSTABILITY": "RC_TRANSPORT_DELAY",
}


def _build_contract(diagnosis: dict[str, Any]) -> dict[str, Any]:
    """Map a DiagnosisEvent to the agent's `DiagnosticContractIn` schema.

    The agent rejects payloads where `cell_id` is missing or
    `root_cause` is not in its PHASE3_ACTIONS map, so we always supply
    `cell_id` (default "C1") and translate diagnostic-side RC codes
    into the optimization agent's vocabulary.
    """
    raw_pattern = str(diagnosis.get("pattern_id") or "RC_NONE")
    pattern_id = _RC_TO_OPTIMIZATION.get(raw_pattern, raw_pattern)
    similar = diagnosis.get("similar_incidents") or []
    evidence = [
        f"{n.get('summary') or n.get('incident_id')}@{round(float(n.get('similarity_pct') or 0.0), 1)}%"
        for n in similar[:5]
        if isinstance(n, dict)
    ]
    if diagnosis.get("alert_id"):
        evidence.insert(0, f"alert:{diagnosis['alert_id']}")
    return {
        "observed_at": diagnosis.get("occurred_at"),
        "source_system": "diagnostic-agent",
        "zone_id": diagnosis.get("zone_id") or "Z1",
        "node_id": diagnosis.get("node_id") or "N1",
        "cell_id": diagnosis.get("cell_id") or "C1",
        "root_cause": pattern_id,
        "confidence": 0.85,
        "summary": diagnosis.get("pattern_label"),
        "evidence": evidence,
    }


_ACTION_TITLES = {
    "ACT_ALERT_COVERAGE_HOLE": "Open coverage-hole ticket for NOC review",
    "ACT_LOADBALANCE_FREQ_BAND": "Shift UEs to less-congested frequency band",
    "ACT_OPTIMIZE_HO_PARAMS": "Tune handover A3 offset and TTT timer",
    "ACT_TRIGGER_CA": "Trigger carrier aggregation change request",
    "ACT_REDUCE_BUFFER_SIZE": "Shrink transport buffer to drain queue",
    "ACT_PRIORITY_VOLTE_SCHEDULING": "Raise QCI scheduling priority for VoLTE",
    "ACT_RECOMMEND_SITE_ADDITION": "Recommend new site / radio planning case",
    "ACT_NO_OP": "Hold — observe KPI stream",
}

_RISK_MAP = {
    "low": RiskLevel.LOW,
    "medium": RiskLevel.MEDIUM,
    "high": RiskLevel.HIGH,
    "critical": RiskLevel.HIGH,
}

_GATE_TO_VERDICT = {
    "APPROVED": PolicyVerdict.AUTO,
    "AUTO_EXECUTED": PolicyVerdict.AUTO,
    "PENDING": PolicyVerdict.DEFERRED,
    "PENDING_APPROVAL": PolicyVerdict.DEFERRED,
    "REJECTED": PolicyVerdict.REJECTED,
}


def _to_proposed(diagnosis: dict[str, Any], decision: dict[str, Any]) -> ProposedActionEvent:
    """Translate the optimization agent's `AgentResult.to_dict()` into the
    bus's `ProposedActionEvent`. Field names line up with deployment/agent/loop.py.
    """
    action = str(decision.get("selected_action") or "no_op")
    title = _ACTION_TITLES.get(action, action.replace("_", " ").capitalize())
    description = (
        str(decision.get("llm_reasoning") or "").strip()
        or f"Gate: {decision.get('gate_decision', 'unknown')}. {decision.get('gate_reason', '')}"
    )
    confidence = float(decision.get("rc_confidence") or decision.get("hybrid_score") or 0.7)
    confidence = max(0.0, min(1.0, confidence))
    risk = _RISK_MAP.get(str(decision.get("risk_level", "medium")).lower(), RiskLevel.MEDIUM)

    safety: list[SafetyCheck] = []
    for chk in decision.get("validators") or []:
        try:
            safety.append(
                SafetyCheck(
                    name=str(chk.get("name") or chk.get("validator") or "check"),
                    display_label=str(
                        chk.get("display_label") or chk.get("name") or "Safety check"
                    ).replace("_", " ").capitalize(),
                    passed=bool(chk.get("passed", chk.get("ok", True))),
                    reason=str(chk.get("reason") or chk.get("message") or ""),
                )
            )
        except Exception:  # noqa: BLE001
            continue

    counterfactual = _counterfactual_from_kpis(decision)

    gate = str(decision.get("gate_decision", "")).upper()
    if decision.get("auto_executed"):
        verdict = PolicyVerdict.AUTO
    else:
        verdict = _GATE_TO_VERDICT.get(gate, _verdict(all(s.passed for s in safety) if safety else True, risk))

    impact_radius_str = str(decision.get("impact_radius") or "sector").lower()
    try:
        impact_radius = ImpactRadius(impact_radius_str)
    except ValueError:
        impact_radius = ImpactRadius.SECTOR

    return ProposedActionEvent(
        correlation_id=diagnosis.get("correlation_id") or f"corr-{diagnosis.get('event_id','')}",
        causation_id=diagnosis.get("event_id"),
        tenant_id=diagnosis.get("tenant_id", "default"),
        zone_id=diagnosis.get("zone_id"),
        cell_id=decision.get("cell_id") or diagnosis.get("cell_id"),
        node_id=diagnosis.get("node_id"),
        producer="optimization",
        producer_version="3.0",
        title=title,
        description=description,
        risk_level=risk,
        impact_radius=impact_radius,
        is_reversible=action not in {"open_ticket", "trigger_carrier_aggregation"},
        rollback_available=True,
        confidence=confidence,
        estimated_users_affected=None,
        estimated_sla_burn_pct=None,
        safety_checks=safety,
        verdict=verdict,
        counterfactual=counterfactual,
        playbook_id=action,
        playbook_params={"selected_tool": decision.get("selected_tool")},
    )


def _counterfactual_from_kpis(decision: dict[str, Any]) -> Counterfactual | None:
    """Build a 60-second latency counterfactual from kpi_before/kpi_after."""
    before = decision.get("kpi_before") or {}
    after = decision.get("kpi_after") or {}
    if not isinstance(before, dict) or not isinstance(after, dict):
        return None
    b = before.get("latency_ms")
    a = after.get("latency_ms")
    if b is None or a is None:
        return None
    try:
        b_v, a_v = float(b), float(a)
    except (TypeError, ValueError):
        return None
    # Visualize the agent's before/after KPI estimate as a short glide so the
    # dashboard can compare no-action vs action without inventing a new model.
    steps = 6
    no_action = [round(b_v, 3) for _ in range(steps)]
    with_action = [round(b_v + (a_v - b_v) * (i + 1) / steps, 3) for i in range(steps)]
    return Counterfactual(
        metric="latency_ms",
        horizon_seconds=60,
        series_no_action=no_action,
        series_with_action=with_action,
    )


# Per-(cell, RC) cooldown so a flood of duplicate diagnoses doesn't
# spam the agent or the bus.
_CONTRACT_COOLDOWN_S = 60.0
_recent_contracts: dict[tuple[str, str], float] = {}
_recent_snapshots: dict[str, float] = {}


def _build_monitoring_snapshot(metric: dict[str, Any]) -> dict[str, Any]:
    extra = metric.get("extra") or {}

    def value(name: str) -> Any:
        return metric.get(name, extra.get(name))

    return {
        "observed_at": metric.get("occurred_at") or metric.get("timestamp"),
        "source_system": "monitoring-agent",
        "zone_id": metric.get("zone_id") or extra.get("zone_id") or "Z1",
        "node_id": metric.get("node_id") or extra.get("node_id") or metric.get("cell_id") or "N1",
        "cell_id": metric.get("cell_id") or extra.get("cell_id") or "C1",
        "latency_ms": value("latency_ms"),
        "jitter_ms": value("jitter_ms"),
        "packet_loss_pct": value("packet_loss_pct"),
        "throughput_mbps": value("throughput_mbps"),
        "bandwidth_util_pct": value("bandwidth_util_pct"),
        "queue_length": value("queue_length"),
        "rssi_dbm": value("rssi_dbm"),
        "sinr_db": value("sinr_db"),
        "cqi": value("cqi"),
        "bler_proxy_pct": value("bler_proxy_pct"),
        "ho_success_rate_pct": value("ho_success_rate_pct"),
        "active_connections": value("active_connections"),
        "anomaly_score": value("anomaly_score"),
        "signal_health_score": value("signal_health_score"),
    }


async def _handle_metric(
    client: httpx.AsyncClient, _bus: RedisStreamsBus, _msg_id: str, metric: dict[str, Any]
) -> None:
    cell_id = str(metric.get("cell_id") or (metric.get("extra") or {}).get("cell_id") or "C1")
    now = asyncio.get_event_loop().time()
    last = _recent_snapshots.get(cell_id, 0.0)
    if now - last < SNAPSHOT_COOLDOWN_S:
        return
    headers = {"authorization": f"Bearer {OPTIMIZATION_TOKEN}"}
    try:
        resp = await client.post(
            f"{OPTIMIZATION_URL}/api/integrations/monitoring/snapshot",
            json=_build_monitoring_snapshot(metric),
            headers=headers,
            timeout=5.0,
        )
        resp.raise_for_status()
        _recent_snapshots[cell_id] = now
    except httpx.HTTPError as exc:
        log.warning("optimization monitoring snapshot failed: %s", exc)


async def _handle(
    client: httpx.AsyncClient, bus: RedisStreamsBus, _msg_id: str, diagnosis: dict[str, Any]
) -> None:
    rc = str(diagnosis.get("pattern_id") or "RC_NONE")
    rc_mapped = _RC_TO_OPTIMIZATION.get(rc, rc)
    cell_id = diagnosis.get("cell_id") or "C1"
    key = (cell_id, rc_mapped)
    now = asyncio.get_event_loop().time()
    last = _recent_contracts.get(key, 0.0)
    if now - last < _CONTRACT_COOLDOWN_S:
        return  # dedupe — same cell+RC seen recently

    headers = {"authorization": f"Bearer {OPTIMIZATION_TOKEN}"}
    try:
        # Ingest the diagnostic contract — agent persists it and emits its own
        # internal alert. This is the real agent doing real work per RC change.
        c_resp = await client.post(
            f"{OPTIMIZATION_URL}/api/integrations/diagnostic/contract",
            json=_build_contract(diagnosis),
            headers=headers,
            timeout=10.0,
        )
        c_resp.raise_for_status()
    except httpx.HTTPError as exc:
        log.warning("optimization contract failed: %r body=%s", exc, getattr(getattr(exc, 'response', None), 'text', None))
        return

    _recent_contracts[key] = now
    try:
        d_resp = await client.post(
            f"{OPTIMIZATION_URL}/api/agent/decide",
            json={"cell_id": cell_id, "human_approved": False},
            headers=headers,
            timeout=float(os.getenv("OPTIMIZATION_DECIDE_TIMEOUT_SECONDS", "90")),
        )
        d_resp.raise_for_status()
        decision = d_resp.json()
    except httpx.HTTPError as exc:
        log.warning("optimization decide failed: %r body=%s", exc, getattr(getattr(exc, 'response', None), 'text', None))
        return
    proposed = _to_proposed(diagnosis, decision)
    await bus.publish(StreamName.ACTION_PROPOSED, proposed)


async def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    install_sigterm_handler(log)
    init_tracer(os.getenv("OTEL_SERVICE_NAME", "optimization-bridge"))
    bus = RedisStreamsBus()
    await bus.connect()
    client = httpx.AsyncClient()

    for _ in range(60):
        try:
            r = await client.get(f"{OPTIMIZATION_URL}/api/ping", timeout=2.0)
            if r.status_code == 200:
                log.info("optimization agent ready")
                break
        except httpx.HTTPError:
            pass
        await asyncio.sleep(2.0)

    async def diagnosis_handler(msg_id: str, payload: dict[str, Any]) -> None:
        await _handle(client, bus, msg_id, payload)

    async def metric_handler(msg_id: str, payload: dict[str, Any]) -> None:
        await _handle_metric(client, bus, msg_id, payload)

    try:
        await asyncio.gather(
            run_consumer(
                bus,
                StreamName.METRICS_RAW,
                group=MONITORING_GROUP,
                consumer=MONITORING_CONSUMER,
                handler=metric_handler,
            ),
            run_consumer(
                bus,
                StreamName.DIAGNOSIS,
                group=GROUP,
                consumer=CONSUMER,
                handler=diagnosis_handler,
            ),
        )
    finally:
        await client.aclose()
        await bus.close()
        flush_tracer()
        log.info("Shutdown complete")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
