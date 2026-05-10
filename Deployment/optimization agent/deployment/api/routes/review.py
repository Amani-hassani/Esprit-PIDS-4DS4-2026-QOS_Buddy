from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
import pandas as pd

from ...actions import execute_action
from ...contracts import ACTION_TOOLS, Decision, PolicyRequest, action_catalog, action_contract
from ...core.access import Principal
from ...core.clock import utc_now
from ...data import latest_cell_row, latest_cell_snapshot
from ...llmops.client import LLMCall
from ...policy_gate import evaluate_policy
from ...simulation import simulate_action
from ...store.repos import ApprovalsRepo, DecisionsRepo
from .._json import json_safe
from ..deps import engineer_required, get_reasoner, viewer_required


router = APIRouter(prefix="/api/review", tags=["review"])
REVIEW_LLM_TIMEOUT_S = 8.0


class PreviewBody(BaseModel):
    approval_id: str | None = None
    cell_id: str | None = None
    action_code: str = Field(..., min_length=3, max_length=120)
    human_approved: bool = False


class ExecuteBody(PreviewBody):
    pass


def _recent_history(cell_id: str, limit: int = 20) -> list[dict[str, Any]]:
    return [
        {
            "action": row.selected_action,
            "gate": row.gate_decision,
            "created_at": row.created_at,
        }
        for row in DecisionsRepo.list_recent(limit=limit, cell_id=cell_id)
    ]


def _heuristic_review(
    *,
    action_code: str,
    policy_decision: str,
    policy_reason: str,
    before_health: float,
    after_health: float,
    changed_kpis: dict[str, Any],
) -> str:
    delta = after_health - before_health
    verdict = "improves" if delta > 0 else ("regresses" if delta < 0 else "holds")
    lines = [
        f"Previewed action {action_code}.",
        f"Policy gate returns {policy_decision}: {policy_reason}",
        f"Deterministic forecast {verdict} health by {delta:+.2f} ({before_health:.2f} -> {after_health:.2f}).",
    ]
    if changed_kpis:
        bits: list[str] = []
        for key, value in list(changed_kpis.items())[:4]:
            try:
                bits.append(f"{key} {float(value.get('before', 0.0)):.1f}->{float(value.get('after', 0.0)):.1f}")
            except Exception:
                continue
        if bits:
            lines.append("Changed KPIs: " + ", ".join(bits))
    return " ".join(lines)


def _with_policy_outcome(reasoning: str, *, decision: str, reason: str) -> str:
    suffix = f"Policy outcome: {decision}. {reason}"
    if suffix in reasoning:
        return reasoning
    return f"{reasoning}\n{suffix}".strip()


def _series_from_kpis(kpis: dict[str, Any]) -> pd.Series:
    row = dict(kpis)
    if "timestamp" in row:
        row["timestamp"] = pd.to_datetime(row.get("timestamp"), errors="coerce", utc=True)
    return pd.Series(row)


def _review_context(body: PreviewBody | ExecuteBody) -> tuple[pd.Series, dict[str, Any], str]:
    if body.approval_id:
        approval = ApprovalsRepo.get(body.approval_id)
        if not approval:
            raise HTTPException(status_code=404, detail="approval not found")
        if approval.get("status") != "PENDING_APPROVAL":
            raise HTTPException(status_code=409, detail="approval_id must reference a pending approval")
        decision_row = DecisionsRepo.get(approval["decision_id"])
        if decision_row is None:
            raise HTTPException(status_code=404, detail="approval decision not found")
        if body.action_code != decision_row.selected_action:
            raise HTTPException(status_code=400, detail="action_code must match the pending approval action")
        row = _series_from_kpis(decision_row.kpi_before)
        snapshot = {
            "root_cause": decision_row.root_cause,
            "confidence": decision_row.rc_confidence,
            "evidence": list(decision_row.evidence),
            "recommended_action": decision_row.selected_action,
        }
        return row, snapshot, decision_row.selected_action

    row = latest_cell_row(body.cell_id)
    snapshot = latest_cell_snapshot(body.cell_id)
    return row, snapshot, body.action_code


@router.get("/catalog")
def catalog(principal: Principal = Depends(viewer_required)):
    return {"items": json_safe(action_catalog())}


@router.post("/preview")
def preview_action(
    body: PreviewBody,
    principal: Principal = Depends(engineer_required),
):
    if body.action_code not in ACTION_TOOLS:
        raise HTTPException(status_code=400, detail=f"unknown action_code: {body.action_code}")
    row, snapshot, action_code = _review_context(body)
    root_cause = str(snapshot["root_cause"])
    contract = action_contract(action_code)
    sim = simulate_action(row, action_code)
    req = PolicyRequest(
        root_cause=root_cause,
        action_code=action_code,
        risk_level=contract.risk_level,
        is_reversible=contract.is_reversible,
        estimated_impact=contract.estimated_impact,
        current_time=utc_now(),
        human_approved=body.human_approved,
        cell_id=str(row.get("cell_id", body.cell_id or "unknown")),
        requires_human=contract.requires_human,
        rollback_available=contract.is_reversible,
        metadata={"source": "review.preview"},
    )
    gate = evaluate_policy(req)
    kpis = row.to_dict()
    reasoner = get_reasoner()
    llm_call = LLMCall(
        prompt_name="review.assessment",
        kind="review",
        variables={
            "cell_id": str(row.get("cell_id", body.cell_id or "unknown")),
            "root_cause": root_cause,
            "action_code": action_code,
            "policy_decision": gate.decision.value,
            "policy_reason": gate.reason,
            "kpis": {k: kpis.get(k) for k in ("rssi_dbm", "sinr_db", "throughput_mbps", "latency_ms", "packet_loss_pct", "jitter_ms", "queue_length")},
            "evidence": [f"{root_cause} current context"] + [entry["action"] for entry in _recent_history(str(row.get("cell_id", body.cell_id or "unknown")), limit=3)],
            "before_health": float(sim["before_health_score"]),
            "after_health": float(sim["after_health_score"]),
            "changed_kpis": sim.get("changed_kpis", {}),
        },
        timeout_s=REVIEW_LLM_TIMEOUT_S,
    )
    response = reasoner.call(llm_call)
    llm_reasoning = ""
    review_recommendation = "test"
    review_risks: list[str] = []
    if response.available and isinstance(response.content, dict):
        llm_reasoning = str(response.content.get("reasoning") or "")
        recommendation = response.content.get("recommendation")
        if isinstance(recommendation, str) and recommendation in {"approve", "reject", "defer", "test"}:
            review_recommendation = recommendation
        risks = response.content.get("risks")
        if isinstance(risks, list):
            review_risks = [str(item) for item in risks]
    if not llm_reasoning:
        llm_reasoning = _heuristic_review(
            action_code=action_code,
            policy_decision=gate.decision.value,
            policy_reason=gate.reason,
            before_health=float(sim["before_health_score"]),
            after_health=float(sim["after_health_score"]),
            changed_kpis=sim.get("changed_kpis", {}),
        )
    llm_reasoning = _with_policy_outcome(
        llm_reasoning,
        decision=gate.decision.value,
        reason=gate.reason,
    )

    return json_safe(
        {
            "cell_id": str(row.get("cell_id", body.cell_id or "unknown")),
            "zone_id": row.get("zone_id"),
            "node_id": row.get("node_id"),
            "root_cause": root_cause,
            "proposed_action": action_code,
            "tool_name": ACTION_TOOLS.get(action_code),
            "policy": {
                "decision": gate.decision.value,
                "reason": gate.reason,
                "validators": [asdict(v) for v in gate.validators],
            },
            "forecast": sim,
            "llm": {
                "available": response.available,
                "model": response.model,
                "reasoning": llm_reasoning,
                "recommendation": review_recommendation,
                "risks": review_risks,
                "reasoning_id": response.reasoning_id,
            },
            "history": _recent_history(str(row.get("cell_id", body.cell_id or "unknown"))),
        }
    )


@router.post("/execute")
def execute_review_action(
    body: ExecuteBody,
    principal: Principal = Depends(engineer_required),
):
    if body.action_code not in ACTION_TOOLS:
        raise HTTPException(status_code=400, detail=f"unknown action_code: {body.action_code}")
    row, snapshot, action_code = _review_context(body)
    root_cause = str(snapshot["root_cause"])
    contract = action_contract(action_code)
    sim = simulate_action(row, action_code)
    req = PolicyRequest(
        root_cause=root_cause,
        action_code=action_code,
        risk_level=contract.risk_level,
        is_reversible=contract.is_reversible,
        estimated_impact=contract.estimated_impact,
        current_time=utc_now(),
        human_approved=body.human_approved and principal.at_least("lead"),
        cell_id=str(row.get("cell_id", body.cell_id or "unknown")),
        requires_human=contract.requires_human,
        rollback_available=contract.is_reversible,
        metadata={"source": "review.execute"},
    )
    gate = evaluate_policy(req)
    kpi_before = {key: value for key, value in row.to_dict().items() if not str(key).startswith("__")}
    kpi_after = dict(kpi_before)
    for key, delta in sim.get("changed_kpis", {}).items():
        kpi_after[key] = delta["after"]
    decision_id = DecisionsRepo.insert(
        cell_id=str(row.get("cell_id", body.cell_id or "unknown")),
        root_cause=root_cause,
        rc_confidence=float(snapshot.get("confidence") or 0.0),
        selected_action=action_code,
        selected_source="review.execute",
        hybrid_score=1.0,
        gate_decision=gate.decision.value,
        gate_reason=gate.reason,
        risk_level=contract.risk_level.value,
        impact_radius=contract.estimated_impact.value,
        auto_executed=gate.decision == Decision.APPROVED,
        principal=principal.token,
        evidence=list(snapshot.get("evidence") or []),
        candidates=[{"source": "review.execute", "action_code": body.action_code, "tool_name": ACTION_TOOLS.get(body.action_code)}],
        validators=[asdict(v) for v in gate.validators],
        kpi_before=kpi_before,
        kpi_after=kpi_after,
        health_before=float(sim["before_health_score"]),
        health_after=float(sim["after_health_score"]),
        mlflow_run_id=None,
    )
    approval_id = None
    execution = None
    if gate.decision == Decision.PENDING_APPROVAL:
        approval_id = ApprovalsRepo.insert(decision_id=decision_id, sla_deadline_iso=utc_now().isoformat())
    elif gate.decision == Decision.APPROVED:
        execution = execute_action(
            decision_id=decision_id,
            cell_id=str(row.get("cell_id", body.cell_id or "unknown")),
            action_code=action_code,
            actor=principal.token,
            reasoning=f"Manual execution from review workspace for {action_code}",
            evidence=list(snapshot.get("evidence") or []),
            kpis=kpi_before,
            risk_level=contract.risk_level.value,
            create_ticket=False,
            source_system="qos-buddy-review",
        )
    return json_safe(
        {
            "decision_id": decision_id,
            "approval_id": approval_id,
            "execution": execution,
            "policy": {"decision": gate.decision.value, "reason": gate.reason},
            "forecast": sim,
        }
    )
