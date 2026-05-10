"""
Synthesis agent entrypoint.

Runs three concurrent loops:
  1. metrics consumer  — qos.metrics.raw → detection + forecast → alerts/diagnosis/insights/proposals
  2. action consumer   — qos.action.proposed → wait for human verdict (handled by gateway endpoints)
  3. heartbeat         — periodic log line so operators can confirm liveness

Everything published to the bus is real:
  • alerts come from real KPI thresholds + the collector's anomaly_score
  • diagnoses come from cosine match to prior incidents (seeded + live)
  • insights come from Qwen2.5 (best-effort, deterministic fallback)
  • actions come from a transparent rule-based mapping with safety checks
  • Jira tickets are populated only after an operator defers an action
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections import Counter
from datetime import datetime, timezone
from typing import Any

import orjson
import uvicorn
from fastapi import FastAPI, HTTPException, Query
from pydantic import ValidationError

from contracts.schemas import (
    AlertEvent,
    DiagnosisEvent,
    InsightEvent,
    MetricEvent,
    ProposedActionEvent,
    Role,
    Severity,
    StreamName,
)
from contracts.noc_vocab import NOC_FACTOR_LABELS

from bus.graceful import install_sigterm_handler
from bus.redis_streams import RedisStreamsBus

from .audit import AuditChain
from .detector import detect, rank_top_factors
from .diagnoser import Diagnoser
from .forecaster import Forecaster
from .llm import LlmClient
from .recommender import recommend

log = logging.getLogger("qos.synthesis")

GROUP = "synthesis"
CONSUMER = os.getenv("HOSTNAME", "synthesis-1")
API_PORT = int(os.getenv("SYNTHESIS_API_PORT", "8090"))

# Cooldown so we don't republish the same alert every sample while a
# breach is sustained. Per cell, per detector.
ALERT_COOLDOWN_SECONDS = float(os.getenv("ALERT_COOLDOWN_SECONDS", "30"))

app = FastAPI(title="QOS-Buddy Synthesis", version="0.1.0")
_api_bus: RedisStreamsBus | None = None
_api_llm: LlmClient | None = None
_shift_cache: tuple[float, dict[str, Any]] | None = None


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/synthesis/cluster-summary")
async def cluster_summary(
    detector: str = Query(..., min_length=1),
    severity: str = Query(..., min_length=1),
    count: int = Query(3, ge=1, le=30),
) -> dict[str, Any]:
    if _api_bus is None or _api_llm is None:
        raise HTTPException(status_code=503, detail="synthesis api not ready")

    items = await _api_bus.latest(StreamName.ALERTS, count=max(100, count * 8))
    now = datetime.now(timezone.utc)
    matches: list[dict[str, Any]] = []
    for _msg_id, alert in reversed(items):
        if str(alert.get("detector")) != detector or str(alert.get("severity")) != severity:
            continue
        if _age_seconds(alert.get("occurred_at"), now) > 600:
            continue
        matches.append(alert)
        if len(matches) >= count:
            break

    if not matches:
        return {"summary": "No matching alert cluster is active.", "top_cell": None}

    cells = Counter(str(a.get("cell_id") or "unknown") for a in matches)
    labels = Counter(str(a.get("display_label") or "Network condition") for a in matches)
    factors = Counter(_top_factor(a) for a in matches if _top_factor(a))
    top_cells = [cell for cell, _n in cells.most_common(3)]
    top_cell = top_cells[0] if top_cells else None
    label = labels.most_common(1)[0][0]
    top_factor = factors.most_common(1)[0][0] if factors else label
    fallback = (
        f"{len(matches)} {severity} {label} alerts detected on cells "
        f"{', '.join(top_cells)}; likely driver is {top_factor}."
    )
    summary = await _api_llm.sentence(
        system=(
            "You summarize alert clusters for NOC operators in one sentence. "
            "Use plain NOC language and avoid technical model terms."
        ),
        user=(
            f"{len(matches)} alerts. Severity: {severity}. Detector: {detector}. "
            f"Cells: {', '.join(top_cells)}. Alert label: {label}. "
            f"Likely driver: {top_factor}."
        ),
        fallback=fallback,
    )
    return {"summary": summary, "top_cell": top_cell, "count": len(matches)}


@app.get("/api/synthesis/shift-summary")
async def shift_summary() -> dict[str, Any]:
    global _shift_cache
    if _api_bus is None or _api_llm is None:
        raise HTTPException(status_code=503, detail="synthesis api not ready")

    now = datetime.now(timezone.utc)
    if _shift_cache and (now.timestamp() - _shift_cache[0]) < 60:
        return _shift_cache[1]

    items = await _api_bus.latest(StreamName.ALERTS, count=300)
    recent = [
        alert
        for _msg_id, alert in items
        if _age_seconds(alert.get("occurred_at"), now) <= 600
    ]
    total = len(recent)
    critical = sum(1 for alert in recent if str(alert.get("severity")) == "critical")
    cells = sorted({str(alert.get("cell_id") or "unknown") for alert in recent})
    labels = Counter(str(alert.get("display_label") or "network condition") for alert in recent)
    factors = Counter(_top_factor(alert) for alert in recent if _top_factor(alert))
    label = labels.most_common(1)[0][0] if labels else "network condition"
    top_kpi = factors.most_common(1)[0][0] if factors else "live KPIs"
    fallback = _shift_fallback(total, critical, cells, label, top_kpi)
    summary = await _api_llm.sentence(
        system=(
            "You summarize the last 10 minutes for NOC operators in one sentence. "
            "Use plain NOC language and avoid technical model terms."
        ),
        user=(
            f"Total alerts: {total}. Critical alerts: {critical}. "
            f"Cells affected: {', '.join(cells) or 'none'}. "
            f"Dominant pattern: {label}. Primary KPI: {top_kpi}. "
            "Include one short recommendation."
        ),
        fallback=fallback,
    )
    result = {
        "summary": summary,
        "total_alerts": total,
        "critical_alerts": critical,
        "cells_affected": cells,
        "top_anomaly_type": label,
        "top_kpi": top_kpi,
    }
    _shift_cache = (now.timestamp(), result)
    return result


class Synthesis:
    def __init__(self, bus: RedisStreamsBus, llm: LlmClient) -> None:
        self.bus = bus
        self.llm = llm
        self.forecaster = Forecaster()
        self.diagnoser = Diagnoser()
        self.audit = AuditChain()
        self._last_alert_at: dict[tuple[str, str], float] = {}

    # ─── lifecycle ────────────────────────────────────────────────────

    async def run(self) -> None:
        await self.audit.seed_from_stream(self.bus)
        await asyncio.gather(
            self._consume_metrics(),
            self._heartbeat(),
        )

    async def _heartbeat(self) -> None:
        while True:
            await asyncio.sleep(30)
            log.info("heartbeat ok consumer=%s", CONSUMER)

    # ─── metrics → alerts/diagnosis/insight/proposal ──────────────────

    async def _consume_metrics(self) -> None:
        async for msg_id, payload in self.bus.consume(
            StreamName.METRICS_RAW, group=GROUP, consumer=CONSUMER
        ):
            try:
                await self._handle_metric(payload)
            except Exception as exc:  # noqa: BLE001
                log.exception("synthesis failed msg=%s: %s", msg_id, exc)
            finally:
                await self.bus.ack(StreamName.METRICS_RAW, GROUP, msg_id)

    async def _handle_metric(self, payload: dict[str, Any]) -> None:
        try:
            metric = MetricEvent.model_validate(payload)
        except ValidationError as exc:
            log.warning("invalid metric: %s", exc.errors()[:1])
            return

        # 1. Threshold + behavioral detector (current breach)
        alert = detect(metric)

        # 2. Forecast — runs every sample; emits its own alert when a breach
        # is projected within the horizon. Forecast is published *independently*
        # of the current alert: a "throughput crashing" alert and a "latency
        # will breach in 90s" forecast are two different operator-facing
        # signals, not competing options for one slot.
        forecast_alert = self.forecaster.update_and_forecast(metric)
        if forecast_alert is not None and self._cooldown_ok(forecast_alert):
            await self.bus.publish(StreamName.ALERTS, forecast_alert)
            log.info(
                "forecast published label=%r severity=%s eta=%ss cell=%s",
                forecast_alert.display_label,
                forecast_alert.severity,
                forecast_alert.time_to_breach_seconds,
                forecast_alert.cell_id,
            )

        # Headline alert for the diagnose/recommend pipeline. We prefer the
        # current breach if one exists; otherwise the forecast can drive
        # preemptive recommendations.
        final_alert = _choose_alert(alert, forecast_alert)
        if final_alert is None:
            return

        # Avoid double-publishing the forecast as the headline.
        if final_alert is not forecast_alert:
            if not self._cooldown_ok(final_alert):
                return
            await self.bus.publish(StreamName.ALERTS, final_alert)
            log.info(
                "alert published label=%r severity=%s detector=%s cell=%s",
                final_alert.display_label,
                final_alert.severity,
                final_alert.detector,
                final_alert.cell_id,
            )

        # 3. Diagnose
        diagnosis = self.diagnoser.diagnose(final_alert, metric)
        await self.bus.publish(StreamName.DIAGNOSIS, diagnosis)

        # 4. Recommend (action proposal + safety + verdict)
        proposed = recommend(final_alert, diagnosis, metric)
        proposed.insight_id = None  # filled below if insight succeeds
        await self.bus.publish(StreamName.ACTION_PROPOSED, proposed)

        # 5. Insight (LLM-best-effort, never blocks)
        insight = await self._build_insight(final_alert, diagnosis, metric)
        if insight is not None:
            await self.bus.publish(StreamName.INSIGHT, insight)

        # 6. Audit: action proposed
        audit_proposed = self.audit.append(
            actor="synthesis",
            actor_role=Role.AI_ENGINEER,
            action="action.proposed",
            target_id=proposed.action_id,
            succeeded=True,
            correlation_id=final_alert.correlation_id,
            causation_id=proposed.event_id,
            cell_id=final_alert.cell_id,
        )
        await self.bus.publish(StreamName.AUDIT, audit_proposed)

        # 7. Ticket creation is intentionally operator-driven. A DEFERRED
        # policy verdict means "needs human review"; the gateway creates the
        # Jira payload only when the operator presses Defer.

    async def _build_insight(
        self,
        alert: AlertEvent,
        diagnosis: DiagnosisEvent,
        metric: MetricEvent,
    ) -> InsightEvent | None:
        kpis = {
            NOC_FACTOR_LABELS.get("latency_ms", "Round-trip delay"): metric.latency_ms,
            NOC_FACTOR_LABELS.get("jitter_ms", "Delay variation"): metric.jitter_ms,
            NOC_FACTOR_LABELS.get("packet_loss_pct", "Packet loss"): metric.packet_loss_pct,
            NOC_FACTOR_LABELS.get("throughput_mbps", "Throughput"): metric.throughput_mbps,
        }
        ctx = {
            "display_label": alert.display_label,
            "severity": alert.severity,
            "cell_id": alert.cell_id,
            "kpis": {k: v for k, v in kpis.items() if v is not None},
            "top_factors": [
                {
                    "display_label": f.display_label,
                    "impact_pct": f.impact_pct,
                    "direction": f.direction,
                }
                for f in (alert.top_factors or [])
            ],
            "similar": [
                {"summary": s.summary, "resolution": s.resolution}
                for s in (diagnosis.similar_incidents or [])
            ],
        }
        try:
            text = await self.llm.brief(ctx)
        except Exception as exc:  # noqa: BLE001
            log.debug("llm brief failed: %s", exc)
            return None
        if not text:
            return None
        return InsightEvent(
            producer="synthesis",
            producer_version="0.1",
            correlation_id=alert.correlation_id,
            causation_id=alert.event_id,
            tenant_id=alert.tenant_id,
            zone_id=alert.zone_id,
            cell_id=alert.cell_id,
            node_id=alert.node_id,
            diagnosis_id=diagnosis.event_id,
            summary=text,
            confidence=alert.confidence,
        )

    # ─── cooldown ─────────────────────────────────────────────────────

    def _cooldown_ok(self, alert: AlertEvent) -> bool:
        import time

        key = (alert.cell_id or "default", str(alert.detector))
        now = time.time()
        last = self._last_alert_at.get(key, 0.0)
        if now - last < ALERT_COOLDOWN_SECONDS:
            return False
        self._last_alert_at[key] = now
        return True


# ─── alert chooser ────────────────────────────────────────────────────────


_SEVERITY_ORDER = {
    Severity.INFO.value: 0,
    Severity.LOW.value: 1,
    Severity.MEDIUM.value: 2,
    Severity.HIGH.value: 3,
    Severity.CRITICAL.value: 4,
}


def _sev_rank(sev: Any) -> int:
    if isinstance(sev, Severity):
        return _SEVERITY_ORDER[sev.value]
    return _SEVERITY_ORDER.get(str(sev), 0)


def _choose_alert(a: AlertEvent | None, b: AlertEvent | None) -> AlertEvent | None:
    if a is None:
        return b
    if b is None:
        return a
    if _sev_rank(a.severity) >= _sev_rank(b.severity):
        return a
    return b


# ─── entrypoint ───────────────────────────────────────────────────────────


def _top_factor(alert: dict[str, Any]) -> str:
    factors = alert.get("top_factors") if isinstance(alert.get("top_factors"), list) else []
    if factors:
        first = factors[0] if isinstance(factors[0], dict) else {}
        label = first.get("display_label") or first.get("technical_name")
        if label:
            return str(label)
    return str(alert.get("display_label") or "")


def _age_seconds(value: Any, now: datetime) -> float:
    if not value:
        return 0.0
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0.0, (now - dt.astimezone(timezone.utc)).total_seconds())
    except Exception:
        return 0.0


def _shift_fallback(
    total: int,
    critical: int,
    cells: list[str],
    label: str,
    top_kpi: str,
) -> str:
    if total == 0:
        return "In the last 10 minutes, no active behavioral alerts were detected; keep monitoring the live KPI stream."
    cell_text = ", ".join(cells[:4])
    if len(cells) > 4:
        cell_text += f" and {len(cells) - 4} more"
    severity_text = f", including {critical} critical," if critical else ""
    return (
        f"In the last 10 minutes, {total} behavioral alerts{severity_text} were detected "
        f"across {cell_text}. The dominant pattern is {label}, primarily affecting {top_kpi}; "
        "review the recommended action and safety checks."
    )


async def main() -> None:
    global _api_bus, _api_llm
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    install_sigterm_handler(log)
    bus = RedisStreamsBus()
    await bus.connect()
    llm = LlmClient()
    agent = Synthesis(bus, llm)
    _api_bus = bus
    _api_llm = llm
    api_server = uvicorn.Server(
        uvicorn.Config(app, host="0.0.0.0", port=API_PORT, log_level="info")
    )
    try:
        await asyncio.gather(agent.run(), api_server.serve())
    finally:
        _api_bus = None
        _api_llm = None
        api_server.should_exit = True
        await bus.close()
        await llm.close()
        log.info("Shutdown complete")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
