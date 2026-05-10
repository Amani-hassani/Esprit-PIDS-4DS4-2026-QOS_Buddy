"""Legacy shim — callers are migrating to deployment.store. Kept so old imports still resolve
while stage 2/3 rewrite the agent/noc paths to use the SQLite store directly. No new code
should import from here."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .core.clock import utc_now_iso
from .store.repos import AlertsRepo, ApprovalsRepo, DecisionsRepo, ReasoningsRepo


RUNTIME_DIR = Path(__file__).resolve().parents[1] / "deployment_runtime"


def append_action_log(entry: dict[str, Any]) -> None:
    """Deprecated — new pipeline writes decisions via DecisionsRepo. Kept for import stability."""
    raise RuntimeError(
        "append_action_log is retired. Use deployment.store.repos.DecisionsRepo / ToolCallsRepo / ReasoningsRepo."
    )


def read_action_log(limit: int = 100) -> list[dict[str, Any]]:
    return [
        {
            "logged_at": row.created_at,
            "tool_execution": {
                "cell_id": row.cell_id,
                "action_code": row.selected_action,
                "id": row.id,
            },
            "policy_gate": {"decision": row.gate_decision, "reason": row.gate_reason},
        }
        for row in DecisionsRepo.list_recent(limit=limit)
    ]


def pending_approvals(limit: int = 100) -> list[dict[str, Any]]:
    return ApprovalsRepo.pending(limit=limit)


__all__ = [
    "RUNTIME_DIR",
    "append_action_log",
    "read_action_log",
    "pending_approvals",
    "AlertsRepo",
    "ApprovalsRepo",
    "DecisionsRepo",
    "ReasoningsRepo",
    "utc_now_iso",
]
