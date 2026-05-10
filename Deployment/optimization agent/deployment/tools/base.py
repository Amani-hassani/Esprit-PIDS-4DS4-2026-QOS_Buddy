from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from ..store.repos import ToolCallsRepo
from ..tracing import set_outputs, tool_span


class ToolInvocationError(RuntimeError):
    """Raised when a tool cannot complete its contract."""


@dataclass
class ToolContext:
    """Per-agent-invocation context passed to every tool call."""

    decision_id: str | None = None
    principal_token: str | None = None
    principal_role: str | None = None
    seq: int = 0
    trace: list[dict[str, Any]] = field(default_factory=list)

    def next_seq(self) -> int:
        self.seq += 1
        return self.seq


class Tool(Protocol):
    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    minimum_role: str  # viewer | engineer | lead

    def run(self, inputs: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class ToolDef:
    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    minimum_role: str
    handler: Callable[[dict[str, Any], ToolContext], dict[str, Any]]

    def run(self, inputs: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
        return self.handler(inputs, ctx)


def invoke(tool: ToolDef, inputs: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """Run a tool, capture its output into the ToolCallsRepo (if a decision is being traced),
    append an in-memory trace entry, and emit an MLflow TOOL span so the GenAI dashboard
    can render this tool call under the parent agent trace."""
    seq = ctx.next_seq()
    started = time.perf_counter()
    error: str | None = None
    output: dict[str, Any] = {}
    span_attrs = {
        "qos.tool.seq": seq,
        "qos.tool.minimum_role": tool.minimum_role,
    }
    if ctx.decision_id:
        span_attrs["qos.decision_id"] = ctx.decision_id
    if ctx.principal_role:
        span_attrs["qos.caller_role"] = ctx.principal_role
    with tool_span(tool.name, inputs=inputs, attributes=span_attrs) as span:
        try:
            output = tool.run(inputs, ctx) or {}
        except ToolInvocationError as exc:
            error = str(exc)
            output = {"error": error}
        except Exception as exc:  # noqa: BLE001 — we intentionally catch to persist the failure
            error = f"{type(exc).__name__}: {exc}"
            output = {"error": error}
        duration_ms = (time.perf_counter() - started) * 1000.0
        if span is not None:
            set_outputs(span, output)
            try:
                span.set_attribute("qos.tool.duration_ms", duration_ms)
                if error:
                    span.set_attribute("qos.tool.error", error)
            except Exception:
                pass
    entry = {
        "seq": seq,
        "tool": tool.name,
        "input": inputs,
        "output": output,
        "duration_ms": round(duration_ms, 3),
        "error": error,
    }
    ctx.trace.append(entry)
    if ctx.decision_id:
        ToolCallsRepo.insert(
            decision_id=ctx.decision_id,
            seq=seq,
            tool_name=tool.name,
            input_payload=inputs,
            output_payload=output,
            duration_ms=duration_ms,
            error=error,
        )
    return output
