"""ACT_REDUCE_BUFFER_SIZE — bufferbloat mitigation profile.

Applies a CoDel-style queue profile that lowers the per-flow buffer size and
biases the AQM towards earlier marking. The deterministic forecast in
`simulation.py:ACTION_EFFECTS` is the source of truth for KPI deltas; this
tool wraps that math behind a real apply/validate/rollback contract.
"""
from __future__ import annotations

from typing import Any

from ._apply_profile import ProfileGuard, apply_profile
from .base import ToolContext, ToolDef


PROFILE_KIND = "buffer_profile"
ACTION_CODE = "ACT_REDUCE_BUFFER_SIZE"


def _build_parameters(inputs: dict[str, Any]) -> dict[str, Any]:
    target_queue_pkts = int(inputs.get("target_queue_pkts") or 64)
    codel_target_ms = int(inputs.get("codel_target_ms") or 5)
    codel_interval_ms = int(inputs.get("codel_interval_ms") or 100)
    if not 8 <= target_queue_pkts <= 1024:
        raise ValueError("target_queue_pkts must be between 8 and 1024")
    if not 1 <= codel_target_ms <= 50:
        raise ValueError("codel_target_ms must be between 1 and 50 ms")
    if not 20 <= codel_interval_ms <= 500:
        raise ValueError("codel_interval_ms must be between 20 and 500 ms")
    return {
        "target_queue_pkts": target_queue_pkts,
        "codel_target_ms": codel_target_ms,
        "codel_interval_ms": codel_interval_ms,
        "ecn_marking": True,
    }


_GUARDS = [
    ProfileGuard(name="latency_must_drop", kpi="latency_ms", rule="decrease", min_delta=2.0),
    ProfileGuard(name="jitter_non_increase", kpi="jitter_ms", rule="non_increase"),
    ProfileGuard(name="loss_non_increase", kpi="packet_loss_pct", rule="non_increase"),
    ProfileGuard(name="queue_must_drop", kpi="queue_length", rule="decrease"),
]


def _run(inputs: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    return apply_profile(
        inputs=inputs,
        ctx=ctx,
        profile_kind=PROFILE_KIND,
        action_code=ACTION_CODE,
        description="CoDel-style buffer profile to mitigate bufferbloat at the cell.",
        guards=_GUARDS,
        parameter_builder=_build_parameters,
    )


STAGE_BUFFER_PROFILE_APPLY = ToolDef(
    name="stage_buffer_profile_apply",
    description="Apply a reversible CoDel buffer profile to a cell with KPI validation and auto-rollback.",
    input_schema={
        "type": "object",
        "required": ["cell_id"],
        "properties": {
            "cell_id": {"type": "string"},
            "target_queue_pkts": {"type": "integer", "minimum": 8, "maximum": 1024},
            "codel_target_ms": {"type": "integer", "minimum": 1, "maximum": 50},
            "codel_interval_ms": {"type": "integer", "minimum": 20, "maximum": 500},
            "force": {"type": "boolean"},
        },
        "additionalProperties": False,
    },
    output_schema={
        "type": "object",
        "properties": {
            "applied": {"type": "boolean"},
            "rolled_back": {"type": "boolean"},
            "snapshot_id": {"type": "string"},
            "execution_state_id": {"type": "string"},
            "rollback_token": {"type": "string"},
            "validation": {"type": "object"},
        },
    },
    minimum_role="engineer",
    handler=_run,
)
