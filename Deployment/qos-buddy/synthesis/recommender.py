"""
Recommender — turns an alert + diagnosis into a ProposedActionEvent
with safety checks, counterfactual snapshot, and policy verdict.

Verdict logic (simple, transparent, NOC-explainable):
  • AUTO     — low risk, local impact, reversible, confidence ≥ 0.8
  • DEFERRED — anything else that isn't outright unsafe
  • REJECTED — non-reversible AND high-risk OR confidence < 0.4
"""

from __future__ import annotations

from typing import Any

from contracts.schemas import (
    AlertEvent,
    Counterfactual,
    DiagnosisEvent,
    ImpactRadius,
    MetricEvent,
    PolicyVerdict,
    ProposedActionEvent,
    RiskLevel,
    SafetyCheck,
)

# Map alert pattern → (playbook id, NOC title, NOC description, params)
_PLAYBOOKS: dict[str, dict[str, Any]] = {
    "backbone congestion pattern": {
        "playbook_id": "qos.reprioritise",
        "title": "Re-prioritise voice and signalling traffic",
        "description": (
            "Temporarily raise priority for voice and signalling traffic on the "
            "affected cell so round-trip delay returns within service targets."
        ),
        "risk_level": RiskLevel.LOW,
        "impact_radius": ImpactRadius.LOCAL,
        "is_reversible": True,
        "estimated_users_affected": 600,
    },
    "buffer pressure cluster": {
        "playbook_id": "qos.scale_queue",
        "title": "Scale queue depth on the affected cell",
        "description": (
            "Increase queue depth and shaping headroom so packets stop bunching "
            "and delay variation drops back into the acceptable band."
        ),
        "risk_level": RiskLevel.LOW,
        "impact_radius": ImpactRadius.LOCAL,
        "is_reversible": True,
        "estimated_users_affected": 350,
    },
    "backhaul degradation": {
        "playbook_id": "qos.backhaul_failover",
        "title": "Fail over to secondary backhaul",
        "description": (
            "Move traffic onto the standby backhaul link so throughput recovers "
            "while we investigate the primary path."
        ),
        "risk_level": RiskLevel.MEDIUM,
        "impact_radius": ImpactRadius.SECTOR,
        "is_reversible": True,
        "estimated_users_affected": 1500,
    },
    "radio-side degradation": {
        "playbook_id": "qos.radio_retune",
        "title": "Re-tune neighbour list and RACH parameters",
        "description": (
            "Apply a conservative neighbour list and RACH parameter retune so "
            "handover quality recovers."
        ),
        "risk_level": RiskLevel.MEDIUM,
        "impact_radius": ImpactRadius.SECTOR,
        "is_reversible": True,
        "estimated_users_affected": 1200,
    },
    "pre-peak warning": {
        "playbook_id": "qos.preemptive_shift",
        "title": "Pre-emptively shift traffic to neighbouring cell",
        "description": (
            "Move part of the load to a neighbouring cell ahead of the evening "
            "peak so we stay clear of the breach line."
        ),
        "risk_level": RiskLevel.LOW,
        "impact_radius": ImpactRadius.LOCAL,
        "is_reversible": True,
        "estimated_users_affected": 250,
    },
}

_DEFAULT_PLAYBOOK: dict[str, Any] = {
    "playbook_id": "qos.investigate",
    "title": "Open a focused investigation on the affected cell",
    "description": (
        "Pin a 10-minute investigation window so we capture full radio and "
        "transport telemetry while the issue is live."
    ),
    "risk_level": RiskLevel.LOW,
    "impact_radius": ImpactRadius.LOCAL,
    "is_reversible": True,
    "estimated_users_affected": 0,
}


def recommend(
    alert: AlertEvent,
    diagnosis: DiagnosisEvent,
    metric: MetricEvent,
) -> ProposedActionEvent:
    pattern_key = (diagnosis.pattern_label or "").lower()
    playbook = _PLAYBOOKS.get(pattern_key, _DEFAULT_PLAYBOOK)

    safety = _safety_checks(alert, playbook)
    verdict = _verdict(alert, playbook, safety)
    counterfactual = _counterfactual(metric, alert)
    sla_burn = _estimate_sla_burn(alert)

    return ProposedActionEvent(
        producer="synthesis",
        producer_version="0.1",
        correlation_id=alert.correlation_id,
        causation_id=alert.event_id,
        tenant_id=alert.tenant_id,
        zone_id=alert.zone_id,
        cell_id=alert.cell_id,
        node_id=alert.node_id,
        insight_id=None,
        title=playbook["title"],
        description=playbook["description"],
        risk_level=playbook["risk_level"],
        impact_radius=playbook["impact_radius"],
        is_reversible=playbook["is_reversible"],
        rollback_available=playbook["is_reversible"],
        confidence=alert.confidence,
        estimated_users_affected=playbook.get("estimated_users_affected"),
        estimated_sla_burn_pct=sla_burn,
        safety_checks=safety,
        verdict=verdict,
        counterfactual=counterfactual,
        playbook_id=playbook["playbook_id"],
        playbook_params={"cell_id": alert.cell_id or "default"},
    )


def _safety_checks(alert: AlertEvent, playbook: dict[str, Any]) -> list[SafetyCheck]:
    checks: list[SafetyCheck] = []
    checks.append(
        SafetyCheck(
            name="reversibility",
            display_label="Action is reversible",
            passed=playbook["is_reversible"],
            reason=(
                "Auto-rollback is available if the change does not improve KPIs."
                if playbook["is_reversible"]
                else "No rollback path — change cannot be undone automatically."
            ),
        )
    )
    impact = playbook["impact_radius"]
    impact_ok = impact in (ImpactRadius.LOCAL, ImpactRadius.SECTOR)
    checks.append(
        SafetyCheck(
            name="blast_radius",
            display_label="Blast radius is contained",
            passed=impact_ok,
            reason=(
                f"Change limited to {impact.value} scope."
                if impact_ok
                else f"Change spans {impact.value} scope — needs explicit approval."
            ),
        )
    )
    confidence_ok = alert.confidence >= 0.6
    checks.append(
        SafetyCheck(
            name="confidence",
            display_label="Detection confidence is sufficient",
            passed=confidence_ok,
            reason=(
                f"Confidence {alert.confidence:.0%} clears the bar."
                if confidence_ok
                else f"Confidence {alert.confidence:.0%} is below the bar — review recommended."
            ),
        )
    )
    return checks


def _verdict(
    alert: AlertEvent,
    playbook: dict[str, Any],
    safety: list[SafetyCheck],
) -> PolicyVerdict:
    if alert.confidence < 0.4:
        return PolicyVerdict.REJECTED
    if not playbook["is_reversible"] and playbook["risk_level"] == RiskLevel.HIGH:
        return PolicyVerdict.REJECTED
    all_pass = all(s.passed for s in safety)
    low_risk = playbook["risk_level"] == RiskLevel.LOW
    local = playbook["impact_radius"] == ImpactRadius.LOCAL
    high_conf = alert.confidence >= 0.8
    if all_pass and low_risk and local and high_conf:
        return PolicyVerdict.AUTO
    return PolicyVerdict.DEFERRED


def _counterfactual(metric: MetricEvent, alert: AlertEvent) -> Counterfactual | None:
    """Project two short series for the headline KPI: with-action vs no-action."""
    field = alert.breach_metric or "latency_ms"
    current = getattr(metric, field, None)
    if current is None:
        return None
    horizon = 60
    no_action: list[float] = []
    with_action: list[float] = []
    for step in range(horizon // 5):
        # Without action: continues drifting in the bad direction
        no_action.append(round(float(current) * (1.0 + 0.05 * step), 3))
        # With action: recovers exponentially toward baseline
        with_action.append(round(float(current) * (0.85 ** step), 3))
    return Counterfactual(
        metric=field,
        horizon_seconds=horizon,
        series_no_action=no_action,
        series_with_action=with_action,
    )


def _estimate_sla_burn(alert: AlertEvent) -> float:
    severity_to_burn = {
        "info": 0.0,
        "low": 0.5,
        "medium": 1.5,
        "high": 4.0,
        "critical": 9.0,
    }
    sev = alert.severity if isinstance(alert.severity, str) else getattr(alert.severity, "value", "medium")
    return severity_to_burn.get(str(sev), 1.5)
