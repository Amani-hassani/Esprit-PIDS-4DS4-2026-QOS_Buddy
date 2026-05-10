"""ACT_PRIORITY_VOLTE_SCHEDULING — QCI scheduler priority profile.

Promotes VoLTE/voice-class QCIs in the scheduler weight table without
touching radio config. Validation enforces that loss and jitter both fall
and that no other KPI regresses meaningfully (health-score check).
"""
from __future__ import annotations

from typing import Any

from ._apply_profile import ProfileGuard, apply_profile
from .base import ToolContext, ToolDef


PROFILE_KIND = "qci_scheduler_profile"
ACTION_CODE = "ACT_PRIORITY_VOLTE_SCHEDULING"


def _build_parameters(inputs: dict[str, Any]) -> dict[str, Any]:
    volte_weight = int(inputs.get("volte_weight") or 80)
    best_effort_weight = int(inputs.get("best_effort_weight") or 30)
    guaranteed_bitrate_kbps = int(inputs.get("guaranteed_bitrate_kbps") or 128)
    if not 50 <= volte_weight <= 100:
        raise ValueError("volte_weight must be between 50 and 100")
    if not 10 <= best_effort_weight <= 80:
        raise ValueError("best_effort_weight must be between 10 and 80")
    if not 64 <= guaranteed_bitrate_kbps <= 512:
        raise ValueError("guaranteed_bitrate_kbps must be between 64 and 512 kbps")
    if best_effort_weight >= volte_weight:
        raise ValueError("volte_weight must exceed best_effort_weight")
    return {
        "volte_qci": 1,
        "volte_weight": volte_weight,
        "best_effort_weight": best_effort_weight,
        "guaranteed_bitrate_kbps": guaranteed_bitrate_kbps,
    }


_GUARDS = [
    ProfileGuard(name="loss_must_drop", kpi="packet_loss_pct", rule="decrease", min_delta=0.05),
    ProfileGuard(name="jitter_must_drop", kpi="jitter_ms", rule="decrease", min_delta=0.5),
    ProfileGuard(name="throughput_non_decrease", kpi="throughput_mbps", rule="non_decrease"),
]


def _run(inputs: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    return apply_profile(
        inputs=inputs,
        ctx=ctx,
        profile_kind=PROFILE_KIND,
        action_code=ACTION_CODE,
        description="Promote voice-class QCI in the cell scheduler weight table.",
        guards=_GUARDS,
        parameter_builder=_build_parameters,
    )


STAGE_QCI_PRIORITY_APPLY = ToolDef(
    name="stage_qci_priority_apply",
    description="Apply a VoLTE-priority scheduler profile with loss/jitter validation and rollback.",
    input_schema={
        "type": "object",
        "required": ["cell_id"],
        "properties": {
            "cell_id": {"type": "string"},
            "volte_weight": {"type": "integer", "minimum": 50, "maximum": 100},
            "best_effort_weight": {"type": "integer", "minimum": 10, "maximum": 80},
            "guaranteed_bitrate_kbps": {"type": "integer", "minimum": 64, "maximum": 512},
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
