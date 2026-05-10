from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ...agent import decide
from ...core.access import Principal
from ...tools.registry import describe_tools
from .._json import json_safe
from ..deps import engineer_required, get_reasoner
from ..events import get_bus


router = APIRouter(prefix="/api/agent", tags=["agent"])


class DecideRequest(BaseModel):
    cell_id: str | None = Field(default=None, description="Optional cell filter; defaults to latest available.")
    human_approved: bool = Field(default=False, description="Lead-level pre-approval bit (skips pending gate).")


@router.post("/decide")
def run_decide(
    body: DecideRequest,
    principal: Principal = Depends(engineer_required),
):
    result = decide(
        cell_id=body.cell_id,
        principal_token=principal.token,
        principal_role=principal.role,
        human_approved=body.human_approved and principal.at_least("lead"),
        reasoner=get_reasoner(),
    )
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
    return json_safe(result.to_dict())


@router.get("/tools")
def list_tools(principal: Principal = Depends(engineer_required)):
    return {"items": describe_tools()}
