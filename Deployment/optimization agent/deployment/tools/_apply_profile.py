"""Shared engine for executable, validated, rollback-capable action tools.

Each `stage_*_apply` tool routes through `apply_profile()`. The pipeline is:
    1. Read the latest authoritative snapshot for the cell.
    2. Build a deterministic post-change KPI map via `simulate_action`.
    3. Persist a NEW monitoring_snapshots row reflecting the post-change KPIs
       (so the dashboard, topology, and downstream models see the change).
    4. Validate post-change health vs. pre-change health and against the
       per-profile KPI guards.
    5. Persist an `execution_state` row keyed by `(cell_id, profile_kind)` with
       a rollback token. If validation fails, immediately roll back the live
       snapshot and mark the row as `rolled_back`.

This module is intentionally pure-Python; no external services are touched."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import pandas as pd

from ..core.clock import utc_now_iso
from ..core.ids import short_id
from ..data import latest_cell_row
from ..simulation import simulate_action
from ..store.repos import ExecutionStateRepo, MonitoringSnapshotsRepo
from ..tools.base import ToolContext, ToolInvocationError
from ..tools.query_topology import clear_topology_cache


HEALTH_REGRESSION_TOLERANCE = -0.5


@dataclass(frozen=True)
class ProfileGuard:
    """A KPI-level validation rule. Compares before/after deterministically."""

    name: str
    kpi: str
    rule: str  # "decrease" | "increase" | "non_increase" | "non_decrease"
    min_delta: float = 0.0  # absolute delta floor, applied to the rule direction


def _check_guard(guard: ProfileGuard, before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    raw_b = before.get(guard.kpi)
    raw_a = after.get(guard.kpi)
    if raw_b is None or raw_a is None:
        return {
            "name": guard.name,
            "kpi": guard.kpi,
            "rule": guard.rule,
            "passed": False,
            "reason": f"{guard.kpi} missing in snapshot",
        }
    try:
        b = float(raw_b)
        a = float(raw_a)
    except (TypeError, ValueError):
        return {
            "name": guard.name,
            "kpi": guard.kpi,
            "rule": guard.rule,
            "passed": False,
            "reason": f"{guard.kpi} not numeric",
        }
    delta = a - b
    if guard.rule == "decrease":
        ok = delta <= -abs(guard.min_delta) if guard.min_delta else delta < 0
    elif guard.rule == "increase":
        ok = delta >= abs(guard.min_delta) if guard.min_delta else delta > 0
    elif guard.rule == "non_increase":
        ok = delta <= abs(guard.min_delta) if guard.min_delta else delta <= 0
    elif guard.rule == "non_decrease":
        ok = delta >= -abs(guard.min_delta) if guard.min_delta else delta >= 0
    else:
        return {
            "name": guard.name,
            "kpi": guard.kpi,
            "rule": guard.rule,
            "passed": False,
            "reason": f"unknown rule {guard.rule}",
        }
    return {
        "name": guard.name,
        "kpi": guard.kpi,
        "rule": guard.rule,
        "before": b,
        "after": a,
        "delta": round(delta, 4),
        "passed": bool(ok),
        "reason": "ok" if ok else f"delta {delta:+.3f} fails {guard.rule}",
    }


def _payload_from_row(row: pd.Series) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in row.to_dict().items():
        if key in {"timestamp", "source_file", "zone_id", "node_id", "cell_id"} or str(key).startswith("__"):
            continue
        if value is None:
            continue
        try:
            if pd.isna(value):
                continue
        except (TypeError, ValueError):
            pass
        payload[str(key)] = value.item() if hasattr(value, "item") else value
    return payload


def apply_profile(
    *,
    inputs: dict[str, Any],
    ctx: ToolContext,
    profile_kind: str,
    action_code: str,
    description: str,
    guards: list[ProfileGuard],
    parameter_builder: Callable[[dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    cell_id = inputs.get("cell_id")
    if not isinstance(cell_id, str) or not cell_id:
        raise ToolInvocationError("cell_id is required")

    parameters = parameter_builder(inputs)

    existing = ExecutionStateRepo.get_active(cell_id, profile_kind)
    if existing and not bool(inputs.get("force", False)):
        return {
            "applied": False,
            "reason": "profile already active for cell",
            "cell_id": cell_id,
            "profile_kind": profile_kind,
            "active_record_id": existing["id"],
            "active_parameters": existing.get("parameters", {}),
        }

    row = latest_cell_row(cell_id)
    before_payload = _payload_from_row(row)
    sim = simulate_action(row, action_code)

    after_payload = dict(before_payload)
    for kpi, change in sim.get("changed_kpis", {}).items():
        after_payload[kpi] = change["after"]

    snapshot_id = MonitoringSnapshotsRepo.insert(
        observed_at=utc_now_iso(),
        source_system=f"qos-buddy-tool/{profile_kind}",
        zone_id=str(row.get("zone_id", "ZONE-1")),
        node_id=str(row.get("node_id", "NODE-1")),
        cell_id=cell_id,
        payload=after_payload,
    )
    clear_topology_cache()

    guard_results = [_check_guard(g, before_payload, after_payload) for g in guards]
    health_delta = float(sim["after_health_score"]) - float(sim["before_health_score"])
    health_pass = health_delta >= HEALTH_REGRESSION_TOLERANCE

    validation = {
        "guards": guard_results,
        "health_before": round(float(sim["before_health_score"]), 4),
        "health_after": round(float(sim["after_health_score"]), 4),
        "health_delta": round(health_delta, 4),
        "health_pass": health_pass,
        "all_passed": health_pass and all(g["passed"] for g in guard_results),
    }

    rollback_token = short_id("rb")
    state_record_id = ExecutionStateRepo.insert(
        cell_id=cell_id,
        profile_kind=profile_kind,
        action_code=action_code,
        state="active" if validation["all_passed"] else "staged",
        decision_id=ctx.decision_id,
        snapshot_id=snapshot_id,
        parameters=parameters,
        before_kpis=before_payload,
        after_kpis=after_payload,
        validation=validation,
        rollback_token=rollback_token,
        actor=ctx.principal_token,
    )

    rolled_back = False
    if not validation["all_passed"]:
        # Auto-rollback: emit a snapshot that restores the pre-change KPIs and
        # mark the state row as rolled_back. Live UI converges back instantly.
        MonitoringSnapshotsRepo.insert(
            observed_at=utc_now_iso(),
            source_system=f"qos-buddy-tool/{profile_kind}/rollback",
            zone_id=str(row.get("zone_id", "ZONE-1")),
            node_id=str(row.get("node_id", "NODE-1")),
            cell_id=cell_id,
            payload=before_payload,
        )
        clear_topology_cache()
        ExecutionStateRepo.mark_rolled_back(state_record_id, ctx.principal_token or "system-tool")
        rolled_back = True

    return {
        "applied": validation["all_passed"],
        "rolled_back": rolled_back,
        "cell_id": cell_id,
        "profile_kind": profile_kind,
        "action_code": action_code,
        "description": description,
        "parameters": parameters,
        "snapshot_id": snapshot_id,
        "execution_state_id": state_record_id,
        "rollback_token": rollback_token,
        "validation": validation,
        "before_kpis": before_payload,
        "after_kpis": after_payload,
        "simulator": sim,
    }
