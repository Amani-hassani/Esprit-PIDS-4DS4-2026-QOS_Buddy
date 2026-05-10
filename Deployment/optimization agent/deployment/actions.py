from __future__ import annotations

from typing import Any

import pandas as pd

from .contracts import ACTION_TOOLS, action_contract
from .core.clock import utc_now_iso
from .data import latest_cell_row
from .integrations import open_change_ticket
from .simulation import simulate_action
from .store.repos import MonitoringSnapshotsRepo
from .tools import ToolContext, run_tool
from .tools.query_topology import clear_topology_cache


STAGED_TOOL_PREFIXES = ("stage_", "simulate_and_stage_")
TICKET_TOOL_PREFIXES = ("create_",)


# Maps action codes that have a fully executable tool to the tool name we
# should invoke. The agent loop already gates by policy/risk; reaching this
# branch means we've been authorised to execute.
EXECUTABLE_ACTION_TOOLS: dict[str, str] = {
    "ACT_REDUCE_BUFFER_SIZE": "stage_buffer_profile_apply",
    "ACT_OPTIMIZE_HO_PARAMS": "stage_handover_param_apply",
    "ACT_PRIORITY_VOLTE_SCHEDULING": "stage_qci_priority_apply",
}


def _row_from_kpis(cell_id: str, kpis: dict[str, Any]) -> pd.Series:
    row = dict(kpis or {})
    row.setdefault("cell_id", cell_id)
    row.setdefault("zone_id", "ZONE-1")
    row.setdefault("node_id", "NODE-1")
    if "timestamp" in row:
        row["timestamp"] = pd.to_datetime(row.get("timestamp"), errors="coerce", utc=True)
    return pd.Series(row)


def _base_payload(row: pd.Series) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in row.to_dict().items():
        if key in {"timestamp", "source_file", "zone_id", "node_id", "cell_id"} or str(key).startswith("__"):
            continue
        if pd.isna(value):
            continue
        payload[str(key)] = value.item() if hasattr(value, "item") else value
    return payload


def _staged_payload(row: pd.Series, action_code: str) -> tuple[dict[str, Any], dict[str, Any]]:
    sim = simulate_action(row, action_code)
    payload = _base_payload(row)
    for key, delta in sim.get("changed_kpis", {}).items():
        payload[key] = delta["after"]
    return payload, sim


def execute_action(
    *,
    decision_id: str | None,
    cell_id: str,
    action_code: str,
    actor: str,
    reasoning: str,
    evidence: list[str],
    kpis: dict[str, Any],
    risk_level: str,
    create_ticket: bool,
    source_system: str,
) -> dict[str, Any]:
    tool_name = ACTION_TOOLS.get(action_code, "observe_kpi_stream")
    contract = action_contract(action_code)
    row = _row_from_kpis(cell_id, kpis) if kpis else latest_cell_row(cell_id)
    result: dict[str, Any] = {
        "action_code": action_code,
        "tool_name": tool_name,
        "mode": "observe",
        "executed": action_code == "ACT_NO_OP",
        "snapshot_id": None,
        "ticket": None,
        "requires_ticket": False,
        "reason": None,
    }

    if action_code == "ACT_NO_OP":
        return result

    executable_tool = EXECUTABLE_ACTION_TOOLS.get(action_code)
    if executable_tool is not None:
        ctx = ToolContext(
            decision_id=decision_id,
            principal_token=actor,
            principal_role="engineer",
        )
        tool_output = run_tool(executable_tool, {"cell_id": cell_id}, ctx)
        validation = tool_output.get("validation", {})
        result.update(
            {
                "mode": "executed" if tool_output.get("applied") else (
                    "rolled_back" if tool_output.get("rolled_back") else "staged"
                ),
                "executed": bool(tool_output.get("applied")),
                "snapshot_id": tool_output.get("snapshot_id"),
                "tool_output": tool_output,
                "validation": validation,
                "rollback_token": tool_output.get("rollback_token"),
            }
        )
        if tool_output.get("rolled_back"):
            result["reason"] = "validation failed; auto-rolled-back"
        return result

    if tool_name.startswith(STAGED_TOOL_PREFIXES):
        payload, sim = _staged_payload(row, action_code)
        snapshot_id = MonitoringSnapshotsRepo.insert(
            observed_at=utc_now_iso(),
            source_system=source_system,
            zone_id=str(row.get("zone_id", "ZONE-1")),
            node_id=str(row.get("node_id", "NODE-1")),
            cell_id=cell_id,
            payload=payload,
        )
        clear_topology_cache()
        result.update(
            {
                "mode": "staged",
                "executed": True,
                "snapshot_id": snapshot_id,
                "simulator": sim,
            }
        )

    needs_ticket = tool_name.startswith(TICKET_TOOL_PREFIXES) or (create_ticket and not result["executed"])
    if needs_ticket:
        ticket = open_change_ticket(
            decision_id=decision_id,
            cell_id=cell_id,
            action_code=action_code,
            summary=f"[{risk_level.upper()}] {action_code} on {cell_id}",
            reasoning=reasoning,
            evidence=evidence,
            kpis=kpis,
            risk_level=risk_level,
            opened_by=actor,
            extra_labels=[contract.autonomy.replace(" ", "-")],
        )
        result["ticket"] = ticket
        result["requires_ticket"] = True
        result["reason"] = "manual-only action" if tool_name.startswith(TICKET_TOOL_PREFIXES) else "execution fallback"
        if result["mode"] == "observe":
            result["mode"] = "ticket"
            result["executed"] = True

    return result
