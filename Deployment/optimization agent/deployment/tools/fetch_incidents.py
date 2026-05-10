from __future__ import annotations

from typing import Any

import pandas as pd

from ..data import load_incidents
from .base import ToolContext, ToolDef


def _run(inputs: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    cell_id = inputs.get("cell_id")
    limit = int(inputs.get("limit", 20))
    limit = max(1, min(limit, 200))
    df = load_incidents()
    if df.empty:
        return {"count": 0, "incidents": []}
    frame = df.copy()
    if cell_id and "cell_id" in frame.columns:
        frame = frame[frame["cell_id"].astype(str) == str(cell_id)]
    if "start_timestamp" in frame.columns:
        frame = frame.sort_values("start_timestamp", ascending=False)
    frame = frame.head(limit)
    incidents = []
    for _, row in frame.iterrows():
        incidents.append(
            {
                "cell_id": row.get("cell_id"),
                "start": str(row.get("start_timestamp")) if "start_timestamp" in frame.columns else None,
                "end": str(row.get("end_timestamp")) if "end_timestamp" in frame.columns else None,
                "anomaly_type": row.get("anomaly_type"),
                "severity": row.get("severity"),
                "root_cause": row.get("root_cause"),
                "source_file": row.get("source_file"),
            }
        )
    return {"count": len(incidents), "incidents": incidents}


FETCH_INCIDENTS = ToolDef(
    name="fetch_incidents",
    description="Return recent incidents reported in the captured incident CSVs.",
    input_schema={
        "type": "object",
        "properties": {
            "cell_id": {"type": ["string", "null"]},
            "limit": {"type": "integer", "minimum": 1, "maximum": 200},
        },
        "additionalProperties": False,
    },
    output_schema={
        "type": "object",
        "properties": {
            "count": {"type": "integer"},
            "incidents": {"type": "array"},
        },
    },
    minimum_role="viewer",
    handler=_run,
)
