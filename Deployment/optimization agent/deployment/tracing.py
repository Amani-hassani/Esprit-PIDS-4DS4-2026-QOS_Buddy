"""MLflow GenAI tracing helpers.

These wrap `mlflow.start_span` with the agent's vocabulary (agent / tool / llm)
and degrade silently when MLflow is unreachable so the call path is never
blocked. Spans set on the active experiment populate the GenAI dashboard
(Traces, Sessions, Token Usage, Cost Over Time, Tool calls).
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Generator

import mlflow
from mlflow.entities import SpanType
from mlflow.tracing.constant import SpanAttributeKey

from .core.settings import get_settings


logger = logging.getLogger("qos_buddy.tracing")


_TRACING_READY = False


def _ensure_ready() -> bool:
    """Lazy-init MLflow on first use; cache success so we don't re-probe each call."""
    global _TRACING_READY
    if _TRACING_READY:
        return True
    try:
        from .mlops import configure_mlflow

        info = configure_mlflow()
        _TRACING_READY = bool(info.get("available"))
    except Exception:
        _TRACING_READY = False
    return _TRACING_READY


def _set_session(span: Any, session_id: str | None) -> None:
    if not session_id:
        return
    try:
        span.set_attribute(SpanAttributeKey.SESSION_ID, session_id)
    except Exception:
        pass


def _set_inputs(span: Any, inputs: dict[str, Any] | None) -> None:
    if inputs is None:
        return
    try:
        span.set_inputs(inputs)
    except Exception:
        pass


def _set_outputs(span: Any, outputs: Any) -> None:
    if outputs is None:
        return
    try:
        span.set_outputs(outputs)
    except Exception:
        pass


def _set_attributes(span: Any, attributes: dict[str, Any] | None) -> None:
    if not attributes:
        return
    for key, value in attributes.items():
        try:
            span.set_attribute(key, value)
        except Exception:
            continue


@contextmanager
def _noop_span() -> Generator[None, None, None]:
    yield None


@contextmanager
def agent_span(
    name: str,
    *,
    session_id: str | None = None,
    inputs: dict[str, Any] | None = None,
    attributes: dict[str, Any] | None = None,
) -> Generator[Any, None, None]:
    """Root span for an agent invocation. Children (tools, LLM) auto-nest under it."""
    if not _ensure_ready():
        yield None
        return
    try:
        cm = mlflow.start_span(name=name, span_type=SpanType.AGENT)
    except Exception:
        yield None
        return
    try:
        with cm as span:
            _set_session(span, session_id)
            _set_inputs(span, inputs)
            _set_attributes(span, attributes)
            try:
                yield span
            except Exception as exc:
                try:
                    span.set_attribute("error.message", str(exc))
                except Exception:
                    pass
                raise
    except Exception:
        # Any tracing-side failure must not break the call path.
        logger.debug("agent_span failed", exc_info=True)
        yield None


@contextmanager
def tool_span(
    name: str,
    *,
    inputs: dict[str, Any] | None = None,
    attributes: dict[str, Any] | None = None,
) -> Generator[Any, None, None]:
    if not _ensure_ready():
        yield None
        return
    try:
        cm = mlflow.start_span(name=f"tool.{name}", span_type=SpanType.TOOL)
    except Exception:
        yield None
        return
    try:
        with cm as span:
            _set_inputs(span, inputs)
            _set_attributes(span, attributes)
            try:
                yield span
            except Exception as exc:
                try:
                    span.set_attribute("error.message", str(exc))
                except Exception:
                    pass
                raise
    except Exception:
        logger.debug("tool_span failed", exc_info=True)
        yield None


@contextmanager
def llm_span(
    name: str,
    *,
    model: str,
    provider: str = "ollama",
    inputs: dict[str, Any] | None = None,
    attributes: dict[str, Any] | None = None,
) -> Generator[Any, None, None]:
    if not _ensure_ready():
        yield None
        return
    try:
        cm = mlflow.start_span(name=name, span_type=SpanType.LLM)
    except Exception:
        yield None
        return
    try:
        with cm as span:
            try:
                span.set_attribute(SpanAttributeKey.MODEL, model)
                span.set_attribute(SpanAttributeKey.MODEL_PROVIDER, provider)
            except Exception:
                pass
            _set_inputs(span, inputs)
            _set_attributes(span, attributes)
            try:
                yield span
            except Exception as exc:
                try:
                    span.set_attribute("error.message", str(exc))
                except Exception:
                    pass
                raise
    except Exception:
        logger.debug("llm_span failed", exc_info=True)
        yield None


def set_token_usage(
    span: Any,
    *,
    input_tokens: int | None,
    output_tokens: int | None,
    total_tokens: int | None = None,
) -> None:
    """Record token usage on an LLM span so the GenAI Token Usage chart populates."""
    if span is None:
        return
    try:
        usage: dict[str, int] = {}
        if isinstance(input_tokens, int) and input_tokens >= 0:
            usage["input_tokens"] = int(input_tokens)
        if isinstance(output_tokens, int) and output_tokens >= 0:
            usage["output_tokens"] = int(output_tokens)
        if total_tokens is None and "input_tokens" in usage and "output_tokens" in usage:
            total_tokens = usage["input_tokens"] + usage["output_tokens"]
        if isinstance(total_tokens, int) and total_tokens >= 0:
            usage["total_tokens"] = int(total_tokens)
        if usage:
            span.set_attribute(SpanAttributeKey.CHAT_USAGE, usage)
    except Exception:
        logger.debug("set_token_usage failed", exc_info=True)


def set_outputs(span: Any, outputs: Any) -> None:
    if span is None:
        return
    _set_outputs(span, outputs)


def set_attributes(span: Any, attributes: dict[str, Any]) -> None:
    if span is None:
        return
    _set_attributes(span, attributes)


def tracing_status() -> dict[str, Any]:
    settings = get_settings()
    ready = _ensure_ready()
    return {
        "ready": ready,
        "experiment_name": settings.mlflow_experiment,
    }
