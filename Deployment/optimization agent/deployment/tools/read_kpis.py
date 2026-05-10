from __future__ import annotations

from typing import Any

from ..data import latest_cell_snapshot
from .base import ToolContext, ToolDef, ToolInvocationError


def _run(inputs: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    cell_id = inputs.get("cell_id")
    try:
        snapshot = latest_cell_snapshot(cell_id)
    except Exception as exc:  # noqa: BLE001
        raise ToolInvocationError(f"latest snapshot unavailable: {exc}") from exc
    return {
        "cell_id": snapshot["state"].get("cell_id"),
        "timestamp": snapshot["state"].get("timestamp"),
        "kpis": snapshot["state"],
        "root_cause": snapshot["root_cause"],
        "root_cause_confidence": snapshot["confidence"],
        "evidence": snapshot["evidence"],
    }


READ_KPIS = ToolDef(
    name="read_kpis",
    description="Return the latest telemetry snapshot for a cell, with an inferred root cause.",
    input_schema={
        "type": "object",
        "properties": {"cell_id": {"type": ["string", "null"]}},
        "additionalProperties": False,
    },
    output_schema={
        "type": "object",
        "properties": {
            "cell_id": {"type": ["string", "null"]},
            "timestamp": {"type": ["string", "null"]},
            "kpis": {"type": "object"},
            "root_cause": {"type": "string"},
            "root_cause_confidence": {"type": "number"},
            "evidence": {"type": "array", "items": {"type": "string"}},
        },
    },
    minimum_role="viewer",
    handler=_run,
)
