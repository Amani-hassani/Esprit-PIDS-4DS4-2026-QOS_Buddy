from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ...actions import execute_action
from ...core.access import Principal
from ...integrations import open_change_ticket
from ...store.repos import ApprovalsRepo, ChangeTicketsRepo, DecisionsRepo, ReasoningsRepo, ToolCallsRepo
from .._json import json_safe
from ..deps import engineer_required, viewer_required
from ..events import get_bus


router = APIRouter(prefix="/api/approvals", tags=["approvals"])


class DecideBody(BaseModel):
    status: str = Field(..., description="APPROVED | REJECTED | DEFERRED")
    reason: str | None = Field(default=None, max_length=500)


@router.get("/pending")
def pending(
    limit: int = Query(default=50, ge=1, le=200),
    principal: Principal = Depends(viewer_required),
):
    return {"items": json_safe(ApprovalsRepo.pending(limit=limit))}


@router.get("/{approval_id}")
def get_one(approval_id: str, principal: Principal = Depends(viewer_required)):
    approval = ApprovalsRepo.get(approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="approval not found")
    decision_row = DecisionsRepo.get(approval["decision_id"])
    decision = asdict(decision_row) if decision_row else None
    tool_calls = ToolCallsRepo.for_decision(approval["decision_id"]) if decision_row else []
    reasonings = ReasoningsRepo.for_decision(approval["decision_id"], limit=8) if decision_row else []
    tickets = ChangeTicketsRepo.for_decision(approval["decision_id"]) if decision_row else []
    return json_safe(
        {
            "approval": approval,
            "decision": decision,
            "tool_calls": tool_calls,
            "reasonings": reasonings,
            "tickets": tickets,
        }
    )


@router.post("/{approval_id}/decide")
def decide_approval(
    approval_id: str,
    body: DecideBody,
    principal: Principal = Depends(engineer_required),
):
    status = body.status.upper()
    if status not in {"APPROVED", "REJECTED", "DEFERRED"}:
        raise HTTPException(status_code=400, detail="status must be APPROVED, REJECTED, or DEFERRED")
    if status == "APPROVED" and not principal.at_least("lead"):
        raise HTTPException(status_code=403, detail="Role 'engineer' cannot approve actions (need 'lead').")
    existing = ApprovalsRepo.get(approval_id)
    if not existing:
        raise HTTPException(status_code=404, detail="approval not found")
    if existing["status"] != "PENDING_APPROVAL":
        raise HTTPException(status_code=409, detail=f"approval already {existing['status']}")
    updated = ApprovalsRepo.decide(approval_id, status, principal.token, body.reason)

    gate_reason = (body.reason or "").strip() or f"approval resolved as {status.lower()}"
    DecisionsRepo.update_gate_state(
        existing["decision_id"],
        gate_decision=status,
        gate_reason=gate_reason,
        auto_executed=(status == "APPROVED"),
    )
    decision_row = DecisionsRepo.get(existing["decision_id"])
    execution = None
    deferred_ticket = None
    if status == "APPROVED" and decision_row is not None:
        execution = execute_action(
            decision_id=decision_row.id,
            cell_id=decision_row.cell_id,
            action_code=decision_row.selected_action,
            actor=principal.token,
            reasoning="human approval execution",
            evidence=list(decision_row.evidence),
            kpis=decision_row.kpi_before,
            risk_level=decision_row.risk_level,
            create_ticket=True,
            source_system="qos-buddy-approval",
        )
    elif status == "DEFERRED" and decision_row is not None:
        motif = (body.reason or "").strip() or "operator deferred without an explicit motif"
        deferred_ticket = open_change_ticket(
            decision_id=decision_row.id,
            cell_id=decision_row.cell_id,
            action_code=decision_row.selected_action,
            summary=(
                f"[DEFERRED:{decision_row.risk_level.upper()}] "
                f"{decision_row.selected_action} on {decision_row.cell_id}"
            ),
            reasoning=f"Deferred by {principal.role or 'operator'}. Motif: {motif}",
            evidence=list(decision_row.evidence),
            kpis=decision_row.kpi_before,
            risk_level=decision_row.risk_level,
            opened_by=principal.token,
            extra_labels=["deferred", f"rc-{decision_row.root_cause.lower()}"],
        )

    bus = get_bus()
    bus.publish(
        "approvals",
        {
            "approval_id": approval_id,
            "decision_id": existing["decision_id"],
            "status": status,
            "actor": principal.role,
            "reason": body.reason,
        },
    )
    return {
        "approval": json_safe(updated),
        "execution": json_safe(execution),
        "deferred_ticket": json_safe(deferred_ticket),
    }


@router.get("")
def list_all(
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    principal: Principal = Depends(viewer_required),
):
    # Simple passthrough: if status is PENDING_APPROVAL, reuse the helper; otherwise use pending+recent-decision overlay.
    if status in (None, "PENDING_APPROVAL"):
        return {"items": json_safe(ApprovalsRepo.pending(limit=limit))}
    # For other statuses, inspect decisions joined via decision_id.
    rows = []
    for dec in DecisionsRepo.list_recent(limit=limit):
        appr = ApprovalsRepo.for_decision(dec.id)
        if appr and (status is None or appr["status"] == status):
            rows.append({**appr, "cell_id": dec.cell_id, "selected_action": dec.selected_action})
    return {"items": json_safe(rows)}
