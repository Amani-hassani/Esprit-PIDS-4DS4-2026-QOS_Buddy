"""ACT_OPTIMIZE_HO_PARAMS — handover parameter patch.

Adjusts the A3 offset and Time-To-Trigger (TTT) timer for the cell. Each
candidate set must satisfy the cell-engineering bounds (offsets in dB,
TTT in 3GPP-defined ms steps) and yield a non-regressing handover success
rate forecast. Validation cross-checks the simulator's deterministic deltas.
"""
from __future__ import annotations

from typing import Any

from ._apply_profile import ProfileGuard, apply_profile
from .base import ToolContext, ToolDef


PROFILE_KIND = "handover_profile"
ACTION_CODE = "ACT_OPTIMIZE_HO_PARAMS"

VALID_TTT_MS = (40, 64, 80, 100, 128, 160, 256, 320, 480, 512, 640, 1024, 1280, 2560, 5120)


def _build_parameters(inputs: dict[str, Any]) -> dict[str, Any]:
    a3_offset_db = float(inputs.get("a3_offset_db") if inputs.get("a3_offset_db") is not None else 3.0)
    ttt_ms = int(inputs.get("ttt_ms") or 256)
    hysteresis_db = float(inputs.get("hysteresis_db") if inputs.get("hysteresis_db") is not None else 1.0)
    if not -3.0 <= a3_offset_db <= 9.0:
        raise ValueError("a3_offset_db must be between -3.0 and 9.0 dB")
    if ttt_ms not in VALID_TTT_MS:
        raise ValueError(f"ttt_ms must be one of {VALID_TTT_MS}")
    if not 0.0 <= hysteresis_db <= 5.0:
        raise ValueError("hysteresis_db must be between 0.0 and 5.0 dB")
    return {
        "a3_offset_db": a3_offset_db,
        "ttt_ms": ttt_ms,
        "hysteresis_db": hysteresis_db,
        "report_amount": 1,
    }


_GUARDS = [
    ProfileGuard(name="ho_success_rate_must_rise", kpi="ho_success_rate_pct", rule="increase", min_delta=2.0),
    ProfileGuard(name="jitter_non_increase", kpi="jitter_ms", rule="non_increase"),
]


def _run(inputs: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    return apply_profile(
        inputs=inputs,
        ctx=ctx,
        profile_kind=PROFILE_KIND,
        action_code=ACTION_CODE,
        description="Tune A3 offset, TTT timer, and hysteresis to stabilise handovers.",
        guards=_GUARDS,
        parameter_builder=_build_parameters,
    )


STAGE_HANDOVER_PARAM_APPLY = ToolDef(
    name="stage_handover_param_apply",
    description="Apply A3-offset/TTT handover tuning with validation against the handover success rate.",
    input_schema={
        "type": "object",
        "required": ["cell_id"],
        "properties": {
            "cell_id": {"type": "string"},
            "a3_offset_db": {"type": "number", "minimum": -3.0, "maximum": 9.0},
            "ttt_ms": {"type": "integer", "enum": list(VALID_TTT_MS)},
            "hysteresis_db": {"type": "number", "minimum": 0.0, "maximum": 5.0},
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
