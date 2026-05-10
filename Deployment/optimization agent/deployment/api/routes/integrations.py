from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from ...agent import decide
from ...contracts import ACTION_TOOLS, PHASE3_ACTIONS, action_contract
from ...core.access import Principal
from ...store.repos import AlertsRepo, DiagnosticContractsRepo, MonitoringSnapshotsRepo
from .._json import json_safe
from ..deps import engineer_required, viewer_required
from ..events import get_bus


router = APIRouter(prefix="/api/integrations", tags=["integrations"])


def _iso_or_now(value: str | None) -> str:
    if not value:
        return datetime.now(timezone.utc).isoformat()
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
    except ValueError:
        return datetime.now(timezone.utc).isoformat()


class MonitoringSnapshotIn(BaseModel):
    source_system: str = Field(default="monitoring-agent", max_length=100)
    observed_at: str | None = None
    zone_id: str
    node_id: str
    cell_id: str
    latency_ms: float | None = None
    jitter_ms: float | None = None
    packet_loss_pct: float | None = None
    throughput_mbps: float | None = None
    bandwidth_util_pct: float | None = None
    queue_length: float | None = None
    rssi_dbm: float | None = None
    sinr_db: float | None = None
    cqi: float | None = None
    bler_proxy_pct: float | None = None
    ho_success_rate_pct: float | None = None
    active_connections: float | None = None
    anomaly_score: float | None = None
    signal_health_score: float | None = None


class DiagnosticContractIn(BaseModel):
    source_system: str = Field(default="diagnostic-agent", max_length=100)
    observed_at: str | None = None
    zone_id: str | None = None
    node_id: str | None = None
    cell_id: str
    root_cause: str
    confidence: float = Field(ge=0.0, le=1.0)
    recommended_action: str | None = None
    summary: str | None = None
    evidence: list[str] = Field(default_factory=list)


class TestDriveIn(BaseModel):
    monitoring: MonitoringSnapshotIn
    diagnostic: DiagnosticContractIn
    run_agent: bool = True


def _publish_live_diagnostic_alert(*, cell_id: str, root_cause: str, confidence: float, recommended_action: str | None) -> str | None:
    if root_cause == "RC_NONE" or confidence < 0.75:
        return None
    try:
        contract = action_contract(recommended_action or PHASE3_ACTIONS[root_cause].action_code)
    except Exception:
        contract = action_contract(PHASE3_ACTIONS[root_cause].action_code)
    severity = {
        "critical": "critical",
        "high": "critical",
        "medium": "warning",
        "low": "info",
    }.get(contract.risk_level.value, "warning")
    return AlertsRepo.insert(
        severity=severity,
        kind="live_diagnostic",
        subject=f"{root_cause} detected on {cell_id}",
        body=(
            f"Live diagnostic contract flagged {root_cause} on {cell_id} "
            f"with confidence {confidence:.2f}. Recommended action: {recommended_action or contract.action_code}."
        ),
    )


@router.get("/status")
def status(principal: Principal = Depends(viewer_required)):
    monitoring = MonitoringSnapshotsRepo.latest()
    diagnostic = DiagnosticContractsRepo.latest()
    return json_safe(
        {
            "monitoring": monitoring,
            "diagnostic": diagnostic,
            "monitoring_cells": len(MonitoringSnapshotsRepo.latest_per_cell()),
        }
    )


@router.post("/monitoring/snapshot")
def ingest_monitoring_snapshot(
    body: MonitoringSnapshotIn,
    principal: Principal = Depends(engineer_required),
):
    payload = body.model_dump(exclude={"source_system", "observed_at", "zone_id", "node_id", "cell_id"}, exclude_none=True)
    observed_at = _iso_or_now(body.observed_at)
    snapshot_id = MonitoringSnapshotsRepo.insert(
        observed_at=observed_at,
        source_system=body.source_system,
        zone_id=body.zone_id,
        node_id=body.node_id,
        cell_id=body.cell_id,
        payload=payload,
    )
    bus = get_bus()
    bus.publish(
        "telemetry",
        {
            "snapshot_id": snapshot_id,
            "source_system": body.source_system,
            "observed_at": observed_at,
            "zone_id": body.zone_id,
            "node_id": body.node_id,
            "cell_id": body.cell_id,
            "snapshot": payload,
        },
    )
    return {"ok": True, "snapshot_id": snapshot_id}


@router.post("/diagnostic/contract")
def ingest_diagnostic_contract(
    body: DiagnosticContractIn,
    principal: Principal = Depends(engineer_required),
):
    root_cause = body.root_cause if body.root_cause in PHASE3_ACTIONS else "RC_NONE"
    observed_at = _iso_or_now(body.observed_at)
    recommended = body.recommended_action
    if recommended and recommended not in ACTION_TOOLS:
        recommended = None
    if not recommended and root_cause in PHASE3_ACTIONS:
        recommended = PHASE3_ACTIONS[root_cause].action_code
    contract_id = DiagnosticContractsRepo.insert(
        observed_at=observed_at,
        source_system=body.source_system,
        zone_id=body.zone_id,
        node_id=body.node_id,
        cell_id=body.cell_id,
        root_cause=root_cause,
        confidence=body.confidence,
        recommended_action=recommended,
        summary=body.summary,
        evidence=body.evidence,
    )
    bus = get_bus()
    bus.publish(
        "reasoning",
        {
            "kind": "diagnostic-contract",
            "available": True,
            "decision_id": None,
            "reasoning_id": contract_id,
            "chosen": recommended,
            "text": body.summary or "",
            "cell_id": body.cell_id,
            "root_cause": root_cause,
            "confidence": body.confidence,
        },
    )
    alert_id = _publish_live_diagnostic_alert(
        cell_id=body.cell_id,
        root_cause=root_cause,
        confidence=body.confidence,
        recommended_action=recommended,
    )
    if alert_id:
        bus.publish(
            "alerts",
            {
                "alert_id": alert_id,
                "cell_id": body.cell_id,
                "kind": "live_diagnostic",
                "root_cause": root_cause,
                "confidence": body.confidence,
            },
        )
    return {"ok": True, "contract_id": contract_id, "alert_id": alert_id}


@router.post("/test-drive")
def ingest_test_drive(
    body: TestDriveIn,
    principal: Principal = Depends(engineer_required),
):
    monitoring = ingest_monitoring_snapshot(body.monitoring, principal)
    diagnostic = ingest_diagnostic_contract(body.diagnostic, principal)
    decision = None
    if body.run_agent:
        result = decide(
            cell_id=body.monitoring.cell_id,
            principal_token=principal.token,
            principal_role=principal.role,
        )
        decision = json_safe(result.to_dict())
        bus = get_bus()
        bus.publish(
            "decisions",
            {
                "decision_id": result.decision_id,
                "cell_id": result.cell_id,
                "action": result.selected_action,
                "gate": result.gate_decision,
                "risk": result.risk_level,
                "auto_executed": result.auto_executed,
                "health_delta": round(result.health_after - result.health_before, 3),
                "llm_available": result.llm_available,
                "reasoning_id": result.reasoning_id,
                "ticket_provider": result.ticket_provider,
                "ticket_key": result.ticket_key,
                "ticket_url": result.ticket_url,
            },
        )
        if result.approval_id:
            bus.publish(
                "approvals",
                {
                    "approval_id": result.approval_id,
                    "decision_id": result.decision_id,
                    "cell_id": result.cell_id,
                    "action": result.selected_action,
                    "risk_level": result.risk_level,
                },
            )
        if result.reasoning_id:
            bus.publish(
                "reasoning",
                {
                    "reasoning_id": result.reasoning_id,
                    "decision_id": result.decision_id,
                    "kind": "agent",
                    "available": result.llm_available,
                    "chosen": result.selected_action,
                    "text": result.llm_reasoning,
                },
            )
    return {
        "ok": True,
        "monitoring": monitoring,
        "diagnostic": diagnostic,
        "cell_id": body.monitoring.cell_id,
        "decision": decision,
    }


@router.get("/monitoring/recent")
def list_monitoring(
    cell_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    principal: Principal = Depends(viewer_required),
):
    return {"items": json_safe(MonitoringSnapshotsRepo.list_recent(limit=limit, cell_id=cell_id))}


@router.get("/diagnostic/recent")
def list_diagnostics(
    cell_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    principal: Principal = Depends(viewer_required),
):
    return {"items": json_safe(DiagnosticContractsRepo.list_recent(limit=limit, cell_id=cell_id))}
