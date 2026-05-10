from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from ..contracts import ACTION_TOOLS, ActionHistoryEntry, Decision, PolicyRequest, RiskLevel, action_contract
from ..data import latest_cell_row, latest_cell_snapshot
from ..policy_gate import evaluate_policy
from ..store.repos import DecisionsRepo
from .base import ToolContext, ToolDef, ToolInvocationError


_RISK_ALIASES = {r.value: r for r in RiskLevel}


def _recent_history(cell_id: str, limit: int = 30) -> list[ActionHistoryEntry]:
    entries: list[ActionHistoryEntry] = []
    for row in DecisionsRepo.list_recent(limit=limit, cell_id=cell_id):
        try:
            ts = datetime.fromisoformat(row.created_at.replace("Z", "+00:00"))
        except ValueError:
            ts = datetime.now(timezone.utc)
        try:
            decision = Decision(row.gate_decision)
        except ValueError:
            decision = Decision.APPROVED
        entries.append(
            ActionHistoryEntry(
                cell_id=row.cell_id,
                action_code=row.selected_action,
                timestamp=ts,
                decision=decision,
            )
        )
    return entries


def _run(inputs: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    action_code = inputs.get("action_code")
    if not action_code:
        raise ToolInvocationError("action_code is required")
    if str(action_code) not in ACTION_TOOLS:
        raise ToolInvocationError(f"unknown action_code: {action_code}")
    cell_id = inputs.get("cell_id")
    row = latest_cell_row(cell_id)
    snapshot = latest_cell_snapshot(cell_id)
    rc = str(inputs.get("root_cause") or snapshot["root_cause"])
    contract = action_contract(str(action_code))
    override_risk = inputs.get("risk_level")
    risk = _RISK_ALIASES.get(str(override_risk)) if override_risk else contract.risk_level
    human_approved = bool(inputs.get("human_approved", False))
    req = PolicyRequest(
        root_cause=rc,
        action_code=str(action_code),
        risk_level=risk or contract.risk_level,
        is_reversible=contract.is_reversible,
        estimated_impact=contract.estimated_impact,
        current_time=datetime.now(timezone.utc),
        action_history=_recent_history(str(row.get("cell_id", cell_id or "unknown"))),
        human_approved=human_approved,
        cell_id=str(row.get("cell_id", cell_id or "unknown")),
        requires_human=contract.requires_human,
        rollback_available=contract.is_reversible,
        metadata={"source": "check_policy_tool"},
    )
    gate = evaluate_policy(req)
    return {
        "decision": gate.decision.value,
        "reason": gate.reason,
        "validators": [asdict(v) for v in gate.validators],
        "risk_level": req.risk_level.value,
        "impact_radius": req.estimated_impact.value,
        "requires_human": req.requires_human,
        "is_reversible": req.is_reversible,
    }


CHECK_POLICY = ToolDef(
    name="check_policy",
    description="Preview the policy-gate verdict for an action against the current cell context.",
    input_schema={
        "type": "object",
        "properties": {
            "cell_id": {"type": ["string", "null"]},
            "action_code": {"type": "string"},
            "root_cause": {"type": ["string", "null"]},
            "risk_level": {"type": ["string", "null"]},
            "human_approved": {"type": "boolean"},
        },
        "required": ["action_code"],
        "additionalProperties": False,
    },
    output_schema={
        "type": "object",
        "properties": {
            "decision": {"type": "string"},
            "reason": {"type": "string"},
            "validators": {"type": "array"},
            "risk_level": {"type": "string"},
            "impact_radius": {"type": "string"},
            "requires_human": {"type": "boolean"},
            "is_reversible": {"type": "boolean"},
        },
    },
    minimum_role="viewer",
    handler=_run,
)
