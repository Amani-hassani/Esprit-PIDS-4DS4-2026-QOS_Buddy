from __future__ import annotations

from typing import Any

from ..store.repos import DecisionsRepo
from .base import ToolContext, ToolDef


def _run(inputs: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    cell_id = inputs.get("cell_id")
    limit = int(inputs.get("limit", 10))
    limit = max(1, min(limit, 100))
    rows = DecisionsRepo.list_recent(limit=limit, cell_id=cell_id)
    return {
        "count": len(rows),
        "history": [
            {
                "id": r.id,
                "created_at": r.created_at,
                "cell_id": r.cell_id,
                "root_cause": r.root_cause,
                "selected_action": r.selected_action,
                "selected_source": r.selected_source,
                "gate_decision": r.gate_decision,
                "auto_executed": r.auto_executed,
                "health_before": r.health_before,
                "health_after": r.health_after,
            }
            for r in rows
        ],
    }


FETCH_HISTORY = ToolDef(
    name="fetch_history",
    description="Return recent decisions for a cell from the audit store.",
    input_schema={
        "type": "object",
        "properties": {
            "cell_id": {"type": ["string", "null"]},
            "limit": {"type": "integer", "minimum": 1, "maximum": 100},
        },
        "additionalProperties": False,
    },
    output_schema={
        "type": "object",
        "properties": {
            "count": {"type": "integer"},
            "history": {"type": "array"},
        },
    },
    minimum_role="viewer",
    handler=_run,
)
