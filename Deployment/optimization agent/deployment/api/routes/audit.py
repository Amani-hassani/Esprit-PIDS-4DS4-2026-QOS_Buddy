from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query

from ...core.access import Principal
from ...store.repos import ChangeTicketsRepo, DecisionsRepo, ReasoningsRepo, ToolCallsRepo
from .._json import json_safe
from ..deps import viewer_required


router = APIRouter(prefix="/api", tags=["audit"])


def _decision_with_ticket(row) -> dict:
    payload = asdict(row)
    tickets = ChangeTicketsRepo.for_decision(row.id)
    if tickets:
        ticket = tickets[0]
        evidence = ticket.get("evidence") or {}
        payload["ticket_provider"] = evidence.get("provider")
        payload["ticket_key"] = evidence.get("ticket_key")
        payload["ticket_url"] = evidence.get("ticket_url")
        payload["ticket_local_id"] = ticket.get("id")
        payload["ticket_status"] = ticket.get("status")
    else:
        payload["ticket_provider"] = None
        payload["ticket_key"] = None
        payload["ticket_url"] = None
        payload["ticket_local_id"] = None
        payload["ticket_status"] = None
    return payload


@router.get("/decisions")
def list_decisions(
    cell_id: str | None = Query(default=None),
    gate: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    principal: Principal = Depends(viewer_required),
):
    rows = DecisionsRepo.list_recent(limit=limit, cell_id=cell_id, gate=gate)
    return {"items": json_safe([_decision_with_ticket(r) for r in rows])}


@router.get("/decisions/{decision_id}")
def get_decision(decision_id: str, principal: Principal = Depends(viewer_required)):
    row = DecisionsRepo.get(decision_id)
    if not row:
        raise HTTPException(status_code=404, detail="decision not found")
    tool_calls = ToolCallsRepo.for_decision(decision_id)
    reasonings = ReasoningsRepo.for_decision(decision_id, limit=8)
    return json_safe(
        {
            "decision": _decision_with_ticket(row),
            "tool_calls": tool_calls,
            "reasonings": reasonings,
        }
    )


@router.get("/reasonings")
def list_reasonings(
    kind: str | None = Query(default=None),
    after_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    principal: Principal = Depends(viewer_required),
):
    return {
        "items": json_safe(ReasoningsRepo.list_recent(limit=limit, kind=kind, after_id=after_id)),
    }


@router.get("/reasonings/{reasoning_id}")
def get_reasoning(reasoning_id: str, principal: Principal = Depends(viewer_required)):
    row = ReasoningsRepo.get(reasoning_id)
    if not row:
        raise HTTPException(status_code=404, detail="reasoning not found")
    return {"reasoning": json_safe(row)}
