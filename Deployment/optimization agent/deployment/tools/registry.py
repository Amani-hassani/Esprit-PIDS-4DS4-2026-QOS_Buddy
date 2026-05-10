from __future__ import annotations

from typing import Any

from ..core.access import ROLE_RANK
from .base import ToolContext, ToolDef, ToolInvocationError, invoke
from .check_policy import CHECK_POLICY
from .fetch_history import FETCH_HISTORY
from .fetch_incidents import FETCH_INCIDENTS
from .open_change_ticket import OPEN_CHANGE_TICKET
from .query_topology import QUERY_TOPOLOGY
from .read_kpis import READ_KPIS
from .stage_buffer_profile_apply import STAGE_BUFFER_PROFILE_APPLY
from .stage_handover_param_apply import STAGE_HANDOVER_PARAM_APPLY
from .stage_qci_priority_apply import STAGE_QCI_PRIORITY_APPLY


ALL_TOOLS: tuple[ToolDef, ...] = (
    READ_KPIS,
    QUERY_TOPOLOGY,
    CHECK_POLICY,
    FETCH_HISTORY,
    FETCH_INCIDENTS,
    OPEN_CHANGE_TICKET,
    STAGE_BUFFER_PROFILE_APPLY,
    STAGE_HANDOVER_PARAM_APPLY,
    STAGE_QCI_PRIORITY_APPLY,
)

TOOL_REGISTRY: dict[str, ToolDef] = {tool.name: tool for tool in ALL_TOOLS}


def get_tool(name: str) -> ToolDef:
    if name not in TOOL_REGISTRY:
        raise KeyError(f"unknown tool: {name}")
    return TOOL_REGISTRY[name]


def _role_permits(required: str, role: str | None) -> bool:
    if role is None:
        return False
    return ROLE_RANK.get(role, 0) >= ROLE_RANK.get(required, 99)


def run_tool(name: str, inputs: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    tool = get_tool(name)
    if not _role_permits(tool.minimum_role, ctx.principal_role):
        return {
            "error": (
                f"tool '{name}' requires role '{tool.minimum_role}' but caller role is "
                f"'{ctx.principal_role or 'anonymous'}'"
            ),
            "tool": name,
            "minimum_role": tool.minimum_role,
            "caller_role": ctx.principal_role,
        }
    return invoke(tool, inputs, ctx)


def describe_tools() -> list[dict[str, Any]]:
    return [
        {
            "name": t.name,
            "description": t.description,
            "input_schema": t.input_schema,
            "output_schema": t.output_schema,
            "minimum_role": t.minimum_role,
        }
        for t in ALL_TOOLS
    ]
