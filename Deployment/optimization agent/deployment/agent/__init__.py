"""Agentic decision loop that orchestrates the trained hybrid ensemble, the typed tool registry,
and the local Qwen reasoner, and persists every artifact (decision, tool calls, reasonings,
approvals) into the SQLite event store."""
from .loop import AgentResult, decide


__all__ = ["AgentResult", "decide"]
