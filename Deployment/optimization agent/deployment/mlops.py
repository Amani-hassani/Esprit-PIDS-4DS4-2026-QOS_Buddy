from __future__ import annotations

import json
import tempfile
from dataclasses import asdict
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import url2pathname

import mlflow
from mlflow.entities import ViewType
from mlflow.tracking import MlflowClient

from .contracts import PolicyDecision
from .core.settings import get_settings


def _json_default(obj: Any) -> str:
    if hasattr(obj, "value"):
        return obj.value
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return str(obj)


def _tracking_uri() -> str:
    settings = get_settings()
    return settings.mlflow_tracking_uri


def _artifact_root_for_uri(tracking_uri: str) -> Path | None:
    settings = get_settings()
    parsed = urlparse(tracking_uri)
    if parsed.scheme == "file":
        return Path(url2pathname(parsed.path))
    if parsed.scheme == "sqlite":
        if tracking_uri == settings.mlflow_tracking_uri:
            return settings.paths.mlflow_dir
        return settings.paths.mlflow_dir.parent / "mlartifacts-recovered"
    return None


def _ensure_tracking_storage(tracking_uri: str) -> None:
    settings = get_settings()
    parsed = urlparse(tracking_uri)
    if parsed.scheme == "sqlite":
        db_path = Path(url2pathname(parsed.path))
        db_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_root = _artifact_root_for_uri(tracking_uri)
    if artifact_root is not None:
        artifact_root.mkdir(parents=True, exist_ok=True)


def _backend_scheme(uri: str) -> str:
    parsed = urlparse(uri)
    return parsed.scheme or "file"


def _local_artifact_location(tracking_uri: str) -> str | None:
    backend = _backend_scheme(tracking_uri)
    if backend in {"", "file", "sqlite"}:
        artifact_root = _artifact_root_for_uri(tracking_uri)
        return artifact_root.as_uri() if artifact_root is not None else None
    return None


def _config_signature() -> tuple[str, str | None, str]:
    settings = get_settings()
    return (
        settings.mlflow_tracking_uri,
        settings.mlflow_registry_uri,
        settings.mlflow_experiment,
    )


def _is_local_sqlite_revision_error(exc: Exception) -> bool:
    settings = get_settings()
    if _backend_scheme(settings.mlflow_tracking_uri) != "sqlite":
        return False
    message = str(exc)
    return "Can't locate revision identified by" in message or "No such revision" in message


def _configure_mlflow_runtime(
    *,
    tracking_uri: str,
    registry_uri: str | None,
    experiment_name: str,
) -> dict[str, Any]:
    backend = _backend_scheme(tracking_uri)
    _ensure_tracking_storage(tracking_uri)
    mlflow.set_tracking_uri(tracking_uri)
    if registry_uri:
        mlflow.set_registry_uri(registry_uri)
    client = MlflowClient()
    experiment = client.get_experiment_by_name(experiment_name)
    if experiment is None:
        create_kwargs: dict[str, Any] = {}
        artifact_location = _local_artifact_location(tracking_uri)
        if artifact_location:
            create_kwargs["artifact_location"] = artifact_location
        experiment_id = client.create_experiment(experiment_name, **create_kwargs)
        experiment = client.get_experiment(experiment_id)
    mlflow.set_experiment(experiment_name)
    return {
        "available": experiment is not None,
        "tracking_uri": tracking_uri,
        "registry_uri": registry_uri,
        "experiment_name": experiment_name,
        "experiment_id": experiment.experiment_id if experiment else None,
        "artifact_location": experiment.artifact_location if experiment else None,
        "backend": backend,
        "error": None,
    }


@lru_cache(maxsize=8)
def _configure_mlflow_cached(signature: tuple[str, str | None, str]) -> dict[str, Any]:
    tracking_uri, registry_uri, experiment_name = signature
    return _configure_mlflow_runtime(
        tracking_uri=tracking_uri,
        registry_uri=registry_uri,
        experiment_name=experiment_name,
    )


def configure_mlflow(*, raise_on_error: bool = False) -> dict[str, Any]:
    settings = get_settings()
    backend = _backend_scheme(settings.mlflow_tracking_uri)
    try:
        return dict(_configure_mlflow_cached(_config_signature()))
    except Exception as exc:
        if _is_local_sqlite_revision_error(exc):
            recovered_uri = f"sqlite:///{(settings.paths.mlflow_db.parent / 'mlflow_recovered.db').as_posix()}"
            try:
                return _configure_mlflow_runtime(
                    tracking_uri=recovered_uri,
                    registry_uri=settings.mlflow_registry_uri,
                    experiment_name=settings.mlflow_experiment,
                )
            except Exception as retry_exc:
                exc = retry_exc
        if raise_on_error:
            raise
        return {
            "available": False,
            "tracking_uri": settings.mlflow_tracking_uri,
            "registry_uri": settings.mlflow_registry_uri,
            "experiment_name": settings.mlflow_experiment,
            "experiment_id": None,
            "artifact_location": None,
            "backend": backend,
            "error": str(exc),
        }


def reset_mlflow_cache() -> None:
    _configure_mlflow_cached.cache_clear()


def mlops_status() -> dict[str, Any]:
    settings = get_settings()
    config = configure_mlflow()
    warning = None
    if config["backend"] == "file":
        warning = "filesystem backend is suitable for local deployment but not ideal for shared production tracking"
    trace_count: int | None = None
    if config["available"] and config.get("experiment_id"):
        try:
            client = MlflowClient()
            traces = client.search_traces(
                experiment_ids=[config["experiment_id"]],
                max_results=1,
            )
            # search_traces returns a PagedList; len() is cheap
            trace_count = len(traces)
        except Exception:
            trace_count = None
    return {
        "available": config["available"],
        "tracking_uri": config["tracking_uri"],
        "registry_uri": config["registry_uri"],
        "experiment_name": config["experiment_name"],
        "experiment_id": config["experiment_id"],
        "artifact_location": config["artifact_location"],
        "backend": config["backend"],
        "warning": warning,
        "error": config["error"],
        "tracing_ready": config["available"],
        "traces_present": (trace_count or 0) > 0 if trace_count is not None else None,
    }


def recent_runs(limit: int = 20) -> list[dict[str, Any]]:
    settings = get_settings()
    config = configure_mlflow()
    if not config["available"]:
        return []
    client = MlflowClient()
    experiment = client.get_experiment_by_name(settings.mlflow_experiment)
    if experiment is None:
        return []
    runs = client.search_runs(
        experiment_ids=[experiment.experiment_id],
        order_by=["attributes.start_time DESC"],
        max_results=limit,
        run_view_type=ViewType.ACTIVE_ONLY,
    )
    items: list[dict[str, Any]] = []
    for run in runs:
        items.append(
            {
                "run_id": run.info.run_id,
                "status": run.info.status,
                "start_time": run.info.start_time,
                "end_time": run.info.end_time,
                "artifact_uri": run.info.artifact_uri,
                "params": dict(run.data.params),
                "metrics": dict(run.data.metrics),
                "tags": {k: v for k, v in run.data.tags.items() if not k.startswith("mlflow.")},
            }
        )
    return items


def recent_traces(limit: int = 20) -> list[dict[str, Any]]:
    """Return recent GenAI traces (agent / tool / LLM spans) for the experiment.

    Empty list when MLflow is offline or no traces have been recorded yet — used
    by the ops dashboard to confirm the GenAI pipeline is wired end-to-end.
    """
    settings = get_settings()
    config = configure_mlflow()
    if not config["available"]:
        return []
    try:
        client = MlflowClient()
        experiment = client.get_experiment_by_name(settings.mlflow_experiment)
        if experiment is None:
            return []
        traces = client.search_traces(
            experiment_ids=[experiment.experiment_id],
            max_results=limit,
            order_by=["attributes.timestamp_ms DESC"],
        )
    except Exception:
        return []
    items: list[dict[str, Any]] = []
    for trace in traces:
        info = trace.info
        execution_ms = getattr(info, "execution_time_ms", None) or getattr(info, "execution_duration", None)
        try:
            tags = dict(info.tags) if info.tags else {}
        except Exception:
            tags = {}
        try:
            metadata = dict(info.request_metadata) if info.request_metadata else {}
        except Exception:
            metadata = {}
        usage = metadata.get("mlflow.trace.tokenUsage") or metadata.get("mlflow.chat.tokenUsage")
        try:
            usage_payload = json.loads(usage) if isinstance(usage, str) else usage
        except Exception:
            usage_payload = None
        items.append(
            {
                "trace_id": getattr(info, "trace_id", None) or getattr(info, "request_id", None),
                "name": getattr(info, "trace_name", None) or tags.get("mlflow.traceName"),
                "status": str(getattr(info, "state", "")) or str(getattr(info, "status", "")),
                "timestamp_ms": getattr(info, "timestamp_ms", None) or getattr(info, "request_time", None),
                "execution_time_ms": execution_ms,
                "session_id": tags.get("mlflow.trace.session") or tags.get("session.id"),
                "tags": {k: v for k, v in tags.items() if not k.startswith("mlflow.")},
                "token_usage": usage_payload,
            }
        )
    return items


def log_decision(
    decision: PolicyDecision,
    llm_source: str,
    llm_available: bool,
    *,
    metadata: dict[str, Any] | None = None,
) -> str:
    config = configure_mlflow(raise_on_error=True)
    payload = asdict(decision)
    extras = metadata or {}
    with mlflow.start_run(
        run_name=f"{decision.request.cell_id}_{decision.request.action_code}",
        tags={
            "service": "qos-buddy",
            "stage": "deployment",
            "tracking_backend": urlparse(config["tracking_uri"]).scheme or "file",
        },
    ) as run:
        mlflow.log_param("root_cause", decision.request.root_cause)
        mlflow.log_param("action_code", decision.request.action_code)
        mlflow.log_param("risk_level", decision.request.risk_level.value)
        mlflow.log_param("impact_radius", decision.request.estimated_impact.value)
        mlflow.log_param("decision", decision.decision.value)
        mlflow.log_param("llm_source", llm_source)
        mlflow.log_param("cell_id", decision.request.cell_id)
        mlflow.log_param("requires_human", str(decision.request.requires_human).lower())
        mlflow.log_param("is_reversible", str(decision.request.is_reversible).lower())

        mlflow.log_metric("llm_available", 1.0 if llm_available else 0.0)
        mlflow.log_metric("validators_passed", float(sum(1 for validator in decision.validators if validator.passed)))
        mlflow.log_metric("validators_total", float(len(decision.validators)))
        mlflow.log_metric("human_approved", 1.0 if decision.request.human_approved else 0.0)

        numeric_metrics = {
            "hybrid_score": extras.get("hybrid_score"),
            "rc_confidence": extras.get("rc_confidence"),
            "health_before": extras.get("health_before"),
            "health_after": extras.get("health_after"),
        }
        for key, value in numeric_metrics.items():
            if isinstance(value, (int, float)):
                mlflow.log_metric(key, float(value))

        string_params = {
            "selected_source": extras.get("selected_source"),
            "selected_tool": extras.get("selected_tool"),
            "diagnostic_action": extras.get("diagnostic_action"),
        }
        for key, value in string_params.items():
            if isinstance(value, str) and value:
                mlflow.log_param(key, value)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            (tmp_dir / "policy_decision.json").write_text(
                json.dumps(payload, indent=2, default=_json_default),
                encoding="utf-8",
            )
            (tmp_dir / "decision_context.json").write_text(
                json.dumps(extras, indent=2, default=_json_default),
                encoding="utf-8",
            )
            mlflow.log_artifact(str(tmp_dir / "policy_decision.json"), artifact_path="decision")
            mlflow.log_artifact(str(tmp_dir / "decision_context.json"), artifact_path="decision")
        return run.info.run_id
