from __future__ import annotations

from typing import Any

from ..store.repos import ChangeTicketsRepo
from .base import ToolContext, ToolDef, ToolInvocationError


def _run(inputs: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    action_code = inputs.get("action_code")
    cell_id = inputs.get("cell_id")
    summary = inputs.get("summary")
    if not action_code or not cell_id or not summary:
        raise ToolInvocationError("action_code, cell_id, summary are all required")
    if ctx.principal_role not in {"engineer", "lead"}:
        raise ToolInvocationError("change tickets can only be opened by engineer or lead principals")
    ticket_id = ChangeTicketsRepo.insert(
        decision_id=ctx.decision_id,
        cell_id=str(cell_id),
        action_code=str(action_code),
        summary=str(summary),
        evidence=inputs.get("evidence") or {},
        opened_by=ctx.principal_token or "unknown",
    )
    return {
        "ticket_id": ticket_id,
        "status": "OPEN",
        "decision_id": ctx.decision_id,
        "cell_id": cell_id,
        "action_code": action_code,
    }


OPEN_CHANGE_TICKET = ToolDef(
    name="open_change_ticket",
    description="Persist an OPEN change ticket in the audit store — use when a human-approval action is queued.",
    input_schema={
        "type": "object",
        "properties": {
            "cell_id": {"type": "string"},
            "action_code": {"type": "string"},
            "summary": {"type": "string"},
            "evidence": {"type": "object"},
        },
        "required": ["cell_id", "action_code", "summary"],
        "additionalProperties": False,
    },
    output_schema={
        "type": "object",
        "properties": {
            "ticket_id": {"type": "string"},
            "status": {"type": "string"},
            "decision_id": {"type": ["string", "null"]},
            "cell_id": {"type": "string"},
            "action_code": {"type": "string"},
        },
    },
    minimum_role="engineer",
    handler=_run,
)
