"""Unified backend service layer for the standalone prediction agent."""

from __future__ import annotations

import logging
import json
import math
import os
import runpy
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Iterable, List

import numpy as np
import pandas as pd
import requests

from config import (
    DATA_INCIDENTS_DIR,
    DATA_RAW_DIR,
    LLM_CONFIG,
    LSTM_WINDOW,
    MLFLOW_ARTIFACTS_DIR,
    MLFLOW_DB_PATH,
    MLFLOW_TRACKING_URI,
    MLFLOW_UI_URL,
    MONITORING_KPI_PATH,
    OLLAMA_DEFAULT_URL,
    RAG_CHROMA_DIR,
    SAVED_MODELS_DIR,
    TARGET_NAMES,
)
from data_pipeline.loader import apply_qos_schema_cleaning, load_incidents, load_qos
from storage import ResultsStore

if TYPE_CHECKING:
    from agent.prediction_agent import PredictionAgent
    from agent.result import PredictionResult
    from rag.incident_store import IncidentStore

logger = logging.getLogger(__name__)
SEVERITY_RANK = {"critical": 4, "high": 3, "warning": 2, "watch": 1, "normal": 0, "unknown": -1}

QOS_REQUIRED_COLUMNS: tuple[str, ...] = (
    "timestamp",
    "node_id",
    "latency_ms",
    "jitter_ms",
    "throughput_mbps",
    "packet_loss_pct",
    "mos_estimate",
    "queue_length",
    "active_connections",
)


def sanitize_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): sanitize_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize_json(v) for v in value]
    if isinstance(value, tuple):
        return [sanitize_json(v) for v in value]
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return value


@dataclass
class BatchPredictionSummary:
    predictions: List[Dict[str, Any]]
    processed_nodes: List[str]
    skipped_nodes: List[Dict[str, str]]


class PredictionPlatformService:
    """Single orchestration layer used by the API and NOC dashboard."""

    def __init__(
        self,
        model_dir: Path | None = None,
        db_path: Path | None = None,
        auto_train_if_missing: bool = False,
    ) -> None:
        self.model_dir = Path(model_dir) if model_dir is not None else SAVED_MODELS_DIR
        self.store = ResultsStore(db_path)
        self.auto_train_if_missing = auto_train_if_missing
        self.monitoring_kpi_path = MONITORING_KPI_PATH
        self.mlflow_tracking_uri = MLFLOW_TRACKING_URI
        self.mlflow_ui_url = MLFLOW_UI_URL
        self.mlflow_db_path = MLFLOW_DB_PATH
        self.mlflow_artifacts_dir = MLFLOW_ARTIFACTS_DIR
        self._mlflow_bootstrap_attempted = False
        self._mlflow_last_error = ""
        self._mlflow_runtime_config: Dict[str, Any] | None = None
        self._agent: PredictionAgent | None = None
        self._incident_store: IncidentStore | None = None

    def _load_monitoring_kpis(self) -> pd.DataFrame:
        if not self.monitoring_kpi_path.exists():
            return pd.DataFrame()
        try:
            frame = pd.read_csv(self.monitoring_kpi_path)
        except Exception:
            logger.exception("Failed to load monitoring KPI store from %s", self.monitoring_kpi_path)
            return pd.DataFrame()
        if frame.empty:
            return frame
        if "timestamp" in frame.columns:
            frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
        if "node_id" in frame.columns:
            frame = frame[~frame["node_id"].astype(str).str.startswith("MON-", na=False)].copy()
        return frame

    def _load_live_qos(self) -> pd.DataFrame:
        frames = [load_qos(DATA_RAW_DIR), self._load_monitoring_kpis()]
        frames = [frame for frame in frames if not frame.empty]
        if not frames:
            return pd.DataFrame()
        combined = pd.concat(frames, ignore_index=True, sort=False)
        if "timestamp" in combined.columns:
            combined["timestamp"] = pd.to_datetime(combined["timestamp"], utc=True, errors="coerce")
        dedupe_keys = [key for key in ("timestamp", "node_id") if key in combined.columns]
        if dedupe_keys:
            combined = combined.drop_duplicates(subset=dedupe_keys, keep="last")
        return combined.sort_values(["timestamp", "node_id"], na_position="last").reset_index(drop=True)

    @staticmethod
    def _port_open(host: str, port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            return sock.connect_ex((host, port)) == 0

    @staticmethod
    def _sqlite_uri_from_path(path: Path) -> str:
        return f"sqlite:///{path.as_posix()}"

    def _mlflow_fallback_paths(self) -> tuple[Path, Path]:
        root = Path(tempfile.gettempdir()) / "qos_prediction_agent_mlflow"
        return root / "mlflow.db", root / "mlruns"

    def _sqlite_path_writable(self, path: Path) -> tuple[bool, str]:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(path) as conn:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("CREATE TABLE IF NOT EXISTS codex_runtime_probe (id INTEGER PRIMARY KEY, value TEXT)")
                conn.execute("INSERT INTO codex_runtime_probe(value) VALUES ('ok')")
                conn.execute("DELETE FROM codex_runtime_probe")
                conn.commit()
            return True, ""
        except Exception as exc:
            return False, f"{type(exc).__name__}: {exc}"

    def _resolve_mlflow_runtime_config(self) -> Dict[str, Any]:
        primary_ok, primary_error = self._sqlite_path_writable(self.mlflow_db_path)
        if primary_ok:
            return {
                "db_path": self.mlflow_db_path,
                "artifact_root": self.mlflow_artifacts_dir,
                "tracking_uri": self.mlflow_tracking_uri,
                "using_fallback": False,
                "fallback_reason": None,
            }

        fallback_db_path, fallback_artifacts_dir = self._mlflow_fallback_paths()
        fallback_ok, fallback_error = self._sqlite_path_writable(fallback_db_path)
        if not fallback_ok:
            return {
                "db_path": fallback_db_path,
                "artifact_root": fallback_artifacts_dir,
                "tracking_uri": self._sqlite_uri_from_path(fallback_db_path),
                "using_fallback": True,
                "fallback_reason": f"primary failed: {primary_error}; fallback failed: {fallback_error}",
            }

        return {
            "db_path": fallback_db_path,
            "artifact_root": fallback_artifacts_dir,
            "tracking_uri": self._sqlite_uri_from_path(fallback_db_path),
            "using_fallback": True,
            "fallback_reason": primary_error,
        }

    def ensure_mlflow_running(self) -> Dict[str, Any]:
        from urllib.parse import urlparse

        parsed = urlparse(self.mlflow_ui_url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 5000
        runtime = self._resolve_mlflow_runtime_config()
        self._mlflow_runtime_config = runtime
        status = {
            "available": False,
            "tracking_uri": runtime["tracking_uri"],
            "ui_url": self.mlflow_ui_url,
            "artifact_root": str(runtime["artifact_root"]),
            "db_path": str(runtime["db_path"]),
            "using_fallback": bool(runtime["using_fallback"]),
            "fallback_reason": runtime["fallback_reason"],
        }

        if self._port_open(host, port):
            status["available"] = True
            status["status"] = "running"
            if self._mlflow_last_error:
                status["last_error"] = self._mlflow_last_error
            return status

        if not self._mlflow_bootstrap_attempted:
            runtime["db_path"].parent.mkdir(parents=True, exist_ok=True)
            runtime["artifact_root"].mkdir(parents=True, exist_ok=True)
            command = [
                sys.executable,
                "-m",
                "mlflow",
                "server",
                "--backend-store-uri",
                runtime["tracking_uri"],
                "--default-artifact-root",
                runtime["artifact_root"].as_posix(),
                "--host",
                host,
                "--port",
                str(port),
            ]
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
            try:
                subprocess.Popen(
                    command,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=creationflags,
                )
                self._mlflow_bootstrap_attempted = True
                self._mlflow_last_error = ""
                for _ in range(10):
                    time.sleep(0.5)
                    if self._port_open(host, port):
                        break
            except Exception as exc:
                status["status"] = "failed_to_start"
                status["error"] = f"{type(exc).__name__}: {exc}"
                self._mlflow_last_error = status["error"]
                return status

        status["available"] = self._port_open(host, port)
        if status["available"]:
            status["status"] = "running"
        elif runtime["fallback_reason"] and not runtime["using_fallback"]:
            status["status"] = "degraded"
        else:
            status["status"] = "starting" if self._mlflow_bootstrap_attempted else "stopped"
        if self._mlflow_bootstrap_attempted and not status["available"]:
            status["last_error"] = self._mlflow_last_error or runtime["fallback_reason"]
        return status

    def mlflow_status(self) -> Dict[str, Any]:
        return self.ensure_mlflow_running()

    def monitoring_status(self) -> Dict[str, Any]:
        frame = self._load_monitoring_kpis()
        if frame.empty:
            return {
                "status": "empty",
                "path": str(self.monitoring_kpi_path),
                "row_count": 0,
                "node_count": 0,
                "cadence_seconds": 30,
                "history_retained": False,
            }
        timestamps = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce") if "timestamp" in frame.columns else pd.Series(dtype="datetime64[ns, UTC]")
        return sanitize_json(
            {
                "status": "ready",
                "path": str(self.monitoring_kpi_path),
                "row_count": int(len(frame)),
                "node_count": int(frame["node_id"].astype(str).nunique()) if "node_id" in frame.columns else 0,
                "latest_timestamp": timestamps.max().isoformat() if not timestamps.empty and timestamps.notna().any() else None,
                "cadence_seconds": 30,
                "history_retained": True,
            }
        )

    def seed_monitoring_agent_kpis(self, min_rows: int = 100) -> Dict[str, Any]:
        base = load_qos(DATA_RAW_DIR)
        incidents = load_incidents(DATA_INCIDENTS_DIR)
        if base.empty:
            return {"status": "no_source_data", "rows_written": 0, "path": str(self.monitoring_kpi_path)}

        base = base.sort_values(["node_id", "timestamp"]).reset_index(drop=True)
        total_rows = max(int(min_rows), 100)
        frames: List[pd.DataFrame] = []

        if not incidents.empty and {"node_id", "start_timestamp"}.issubset(incidents.columns):
            incidents = incidents.sort_values(["start_timestamp", "node_id"]).reset_index(drop=True)
            incident_nodes = sorted({str(node_id) for node_id in incidents["node_id"].dropna().astype(str).tolist()})
            if incident_nodes:
                incident_scoped = base[base["node_id"].astype(str).isin(incident_nodes)].copy()
                start_bound = incidents["start_timestamp"].min()
                end_series = incidents["end_timestamp"] if "end_timestamp" in incidents.columns else incidents["start_timestamp"]
                end_bound = end_series.max()
                if not pd.isna(start_bound):
                    incident_scoped = incident_scoped[incident_scoped["timestamp"] >= (pd.Timestamp(start_bound) - pd.Timedelta(minutes=15))]
                if not pd.isna(end_bound):
                    incident_scoped = incident_scoped[incident_scoped["timestamp"] <= (pd.Timestamp(end_bound) + pd.Timedelta(minutes=15))]
                if incident_scoped.empty:
                    incident_scoped = base[base["node_id"].astype(str).isin(incident_nodes)].copy()
                incident_scoped = incident_scoped.sort_values(["timestamp", "node_id"]).tail(total_rows).copy()
                if not incident_scoped.empty:
                    if "data_source" in incident_scoped.columns:
                        incident_scoped["data_source"] = "monitoring_agent_replay"
                    frames.append(incident_scoped)

        if not frames:
            fallback = (
                base.groupby("node_id", group_keys=False)
                .tail(max(LSTM_WINDOW + 10, math.ceil(total_rows / max(base["node_id"].nunique(), 1))))
                .sort_values(["timestamp", "node_id"])
            )
            frames = [fallback]

        frame = pd.concat(frames, ignore_index=True, sort=False)
        frame = frame.sort_values(["timestamp", "node_id"]).reset_index(drop=True)

        # Replay the exact source values with a fresh 30-second monitoring cadence and real node ids.
        existing = self._load_monitoring_kpis()
        if not existing.empty and "timestamp" in existing.columns:
            next_ts = existing["timestamp"].max() + pd.Timedelta(seconds=30)
        else:
            next_ts = pd.Timestamp.now(tz="UTC").floor("30s") - pd.Timedelta(seconds=max(len(frame) - 1, 0) * 30)

        frame = frame.tail(total_rows).reset_index(drop=True)
        frame["timestamp"] = [next_ts + pd.Timedelta(seconds=30 * idx) for idx in range(len(frame))]
        if "data_source" in frame.columns:
            frame["data_source"] = "monitoring_agent_replay"
        if "baseline_phase" in frame.columns:
            frame["baseline_phase"] = False
        if "anomaly_type" in frame.columns:
            frame["anomaly_type"] = frame["anomaly_type"].fillna("incident_aligned_replay")

        combined = pd.concat([existing, frame], ignore_index=True, sort=False) if not existing.empty else frame
        combined = combined.sort_values(["timestamp", "node_id"]).drop_duplicates(subset=["timestamp", "node_id"], keep="last")
        combined.to_csv(self.monitoring_kpi_path, index=False)
        status = self.monitoring_status()
        status["status"] = "seeded"
        status["mode"] = "incident_aligned_replay"
        status["rows_written"] = int(len(frame))
        status["cadence_seconds"] = 30
        status["history_retained"] = True
        return status

    @property
    def incident_store(self) -> IncidentStore:
        from rag.incident_store import IncidentStore

        if self._incident_store is None:
            self._incident_store = IncidentStore()
        return self._incident_store

    def _required_artifacts(self) -> List[Path]:
        files = [
            self.model_dir / "preprocessor.joblib",
            self.model_dir / "xgb_feature_columns.joblib",
            self.model_dir / "lstm_qos.pt",
            self.model_dir / "decision_thresholds.joblib",
        ]
        files.extend(self.model_dir / f"xgb_{target}_calibrated.joblib" for target in TARGET_NAMES)
        return files

    def model_status(self) -> Dict[str, Any]:
        required = self._required_artifacts()
        missing = [str(path.relative_to(self.model_dir.parent.parent)) for path in required if not path.exists()]
        latest_mtime = max((path.stat().st_mtime for path in required if path.exists()), default=None)
        return {
            "model_dir": str(self.model_dir),
            "ready": not missing,
            "missing_artifacts": missing,
            "artifact_count": sum(1 for path in required if path.exists()),
            "required_artifact_count": len(required),
            "latest_artifact_mtime_epoch": latest_mtime,
        }

    def _bootstrap_models(self) -> None:
        if self.model_status()["ready"] or not self.auto_train_if_missing:
            return
        logger.warning("Model artifacts missing. Starting automated bootstrap training run.")
        runpy.run_path(str(Path(__file__).resolve().parents[1] / "main.py"), run_name="__main__")
        self._agent = None

    def get_agent(self) -> PredictionAgent:
        from agent.prediction_agent import PredictionAgent

        self._bootstrap_models()
        if self._agent is None:
            self._agent = PredictionAgent(model_dir=self.model_dir, incident_store=self.incident_store)
        return self._agent

    def sync_incidents(self, replace: bool = False) -> Dict[str, Any]:
        incidents = load_incidents(DATA_INCIDENTS_DIR)
        if incidents.empty:
            return {"ingested": 0, "source_dir": str(DATA_INCIDENTS_DIR), "status": "no_incidents"}
        try:
            store = self.incident_store
            ingested = store.ingest(incidents, replace=replace)
            status = "disabled" if getattr(store, "disabled_reason", None) else "ok"
            return {
                "ingested": ingested,
                "source_dir": str(DATA_INCIDENTS_DIR),
                "replace": replace,
                "status": status,
                "disabled_reason": getattr(store, "disabled_reason", None),
            }
        except Exception as exc:
            logger.exception("Incident sync failed")
            return {
                "ingested": 0,
                "source_dir": str(DATA_INCIDENTS_DIR),
                "replace": replace,
                "status": "error",
                "error": f"{type(exc).__name__}: {exc}",
            }

    def reset_monitoring_feed(self) -> Dict[str, Any]:
        try:
            if self.monitoring_kpi_path.exists():
                self.monitoring_kpi_path.unlink()
            return {
                "status": "reset",
                "path": str(self.monitoring_kpi_path),
                "monitoring": self.monitoring_status(),
            }
        except PermissionError:
            empty = pd.DataFrame(columns=list(QOS_REQUIRED_COLUMNS))
            empty.to_csv(self.monitoring_kpi_path, index=False)
            return {
                "status": "reset",
                "path": str(self.monitoring_kpi_path),
                "monitoring": self.monitoring_status(),
            }

    def ingest_monitoring_records(
        self,
        records: Iterable[Dict[str, Any]],
        *,
        generate_llm: bool = True,
        persist: bool = True,
        sync_incidents: bool = False,
        cadence_seconds: int = 30,
        window_rows: int = 60,
    ) -> Dict[str, Any]:
        frame = pd.DataFrame(list(records))
        if frame.empty:
            payload = {
                "record_count": 0,
                "nodes": [],
                "processed_nodes": [],
                "skipped_nodes": [],
                "prediction_count": 0,
                "predictions": [],
                "monitoring": self.monitoring_status(),
            }
            if sync_incidents:
                payload["incident_sync"] = self.sync_incidents(replace=False)
            return sanitize_json(payload)

        missing_columns = [column for column in QOS_REQUIRED_COLUMNS if column not in frame.columns]
        if missing_columns:
            raise ValueError(f"records missing required columns: {', '.join(missing_columns)}")

        frame = apply_qos_schema_cleaning(frame)
        if "timestamp" not in frame.columns:
            raise ValueError("records must include timestamp")
        frame = frame.loc[frame["timestamp"].notna()].copy()
        if frame.empty:
            raise ValueError("records must include at least one valid timestamp")

        frame = frame.sort_values(["timestamp", "node_id"], na_position="last").reset_index(drop=True)

        existing = self._load_monitoring_kpis()
        cadence = max(int(cadence_seconds), 1)
        if not existing.empty and "timestamp" in existing.columns and existing["timestamp"].notna().any():
            start_ts = existing["timestamp"].max() + pd.Timedelta(seconds=cadence)
        else:
            start_ts = pd.Timestamp.now(tz="UTC").floor(f"{cadence}s")

        source_timestamps = sorted(frame["timestamp"].dropna().unique().tolist())
        timestamp_map = {
            source_ts: start_ts + pd.Timedelta(seconds=cadence * idx)
            for idx, source_ts in enumerate(source_timestamps)
        }
        frame["timestamp"] = frame["timestamp"].map(timestamp_map)
        if "data_source" in frame.columns:
            frame["data_source"] = frame["data_source"].fillna("monitoring_agent_replay")
        else:
            frame["data_source"] = "monitoring_agent_replay"
        if "baseline_phase" in frame.columns:
            frame["baseline_phase"] = frame["baseline_phase"].fillna(False).astype(bool)
        if "anomaly_type" in frame.columns:
            frame["anomaly_type"] = frame["anomaly_type"].fillna("incident_aligned_replay")

        combined = pd.concat([existing, frame], ignore_index=True, sort=False) if not existing.empty else frame
        combined = (
            combined.sort_values(["timestamp", "node_id"], na_position="last")
            .drop_duplicates(subset=["timestamp", "node_id"], keep="last")
            .reset_index(drop=True)
        )
        combined.to_csv(self.monitoring_kpi_path, index=False)

        live = self._load_live_qos()
        touched_nodes = [str(node_id) for node_id in frame["node_id"].dropna().astype(str).unique().tolist()]
        grouped = {
            str(node_id): group.sort_values("timestamp").tail(window_rows).reset_index(drop=True)
            for node_id, group in live[live["node_id"].astype(str).isin(touched_nodes)].groupby("node_id", sort=False)
        }
        batch = self._predict_frames(grouped, generate_llm=generate_llm, persist=persist)

        payload = {
            "record_count": int(len(frame)),
            "nodes": touched_nodes,
            "processed_nodes": batch.processed_nodes,
            "skipped_nodes": batch.skipped_nodes,
            "prediction_count": len(batch.predictions),
            "predictions": batch.predictions,
            "monitoring": self.monitoring_status(),
        }
        if sync_incidents:
            payload["incident_sync"] = self.sync_incidents(replace=False)
        return sanitize_json(payload)

    def llm_status(self) -> Dict[str, Any]:
        base_url = str(LLM_CONFIG.get("url", OLLAMA_DEFAULT_URL)).rstrip("/")
        model = str(LLM_CONFIG.get("model", ""))
        try:
            response = requests.get(f"{base_url}/api/tags", timeout=2)
            response.raise_for_status()
            payload = response.json() or {}
            models = [entry.get("name", "") for entry in payload.get("models", [])]
            return {
                "available": True,
                "base_url": base_url,
                "configured_model": model,
                "configured_model_available": model in models if model else False,
                "catalog_size": len(models),
            }
        except Exception as exc:
            return {
                "available": False,
                "base_url": base_url,
                "configured_model": model,
                "error": f"{type(exc).__name__}: {exc}",
            }

    def rag_status(self) -> Dict[str, Any]:
        if self._incident_store is None:
            return {"persist_dir": str(RAG_CHROMA_DIR), "status": "lazy", "incident_count": None}
        try:
            if getattr(self._incident_store, "disabled_reason", None):
                return {
                    "persist_dir": str(self._incident_store.persist_dir),
                    "status": "disabled",
                    "incident_count": 0,
                    "error": self._incident_store.disabled_reason,
                }
            collection = self.incident_store._collection
            return {
                "persist_dir": str(self.incident_store.persist_dir),
                "collection_name": collection.name,
                "incident_count": int(collection.count()),
            }
        except Exception as exc:
            return {"persist_dir": str(self.incident_store.persist_dir), "error": f"{type(exc).__name__}: {exc}"}

    def health(self) -> Dict[str, Any]:
        stats = self.store.get_statistics(days_back=7)
        models = self.model_status()
        return {
            "status": "ok" if models["ready"] else "degraded",
            "models": models,
            "rag": self.rag_status(),
            "llm": self.llm_status(),
            "mlflow": self.mlflow_status(),
            "monitoring": self.monitoring_status(),
            "storage": {
                **self.store.runtime_status(),
                "db_path": str(self.store.db_path),
                "total_predictions_7d": stats["total_predictions"],
            },
            "required_qos_columns": list(QOS_REQUIRED_COLUMNS),
        }

    def quick_health(self) -> Dict[str, Any]:
        models = self.model_status()
        return {
            "status": "ok" if models["ready"] else "degraded",
            "models_ready": bool(models["ready"]),
            "artifact_count": models["artifact_count"],
            "required_artifact_count": models["required_artifact_count"],
            "storage": {
                "db_path": str(self.store.db_path),
                "db_exists": self.store.db_path.exists(),
            },
        }

    def _serialize_result(self, result: PredictionResult) -> Dict[str, Any]:
        return sanitize_json(result.to_dict())

    def _enrich_fleet_context(self, results: List[PredictionResult]) -> None:
        if not results:
            return
        sorted_results = sorted(
            results,
            key=lambda item: (
                SEVERITY_RANK.get(item.severity, -1),
                item.primary_metric_probability,
                item.confidence_score,
            ),
            reverse=True,
        )
        average_risk_by_target = {
            target: round(float(np.mean([item.risk_probs.get(target, 0.0) for item in results])), 4)
            for target in TARGET_NAMES
        }
        domain_counts: Dict[str, int] = {}
        for item in results:
            if item.domain_hints:
                domain = str(item.domain_hints[0].get("domain", "unknown"))
                domain_counts[domain] = domain_counts.get(domain, 0) + 1
        pattern = "clustered" if len(results) > 1 and max(domain_counts.values(), default=0) > 1 else "isolated"

        for rank, item in enumerate(sorted_results, start=1):
            peer_nodes = [pred.node_id for pred in sorted_results[:5] if pred.node_id != item.node_id]
            item.fleet_context = {
                "fleet_rank": rank,
                "nodes_in_batch": len(results),
                "pattern_scope": pattern,
                "peer_nodes": peer_nodes,
                "average_risk_by_target": average_risk_by_target,
                "dominant_domains": domain_counts,
            }

    def _persist_results(self, results: List[PredictionResult]) -> None:
        for result in results:
            result.database_id = self.store.store_prediction(result)

    def _log_mlflow_prediction_batch(
        self,
        results: List[PredictionResult],
        processed_nodes: List[str],
        skipped_nodes: List[Dict[str, str]],
    ) -> None:
        try:
            import mlflow
            from mlflow.tracking import MlflowClient

            runtime = self._mlflow_runtime_config or self._resolve_mlflow_runtime_config()
            tracking_uri = str(runtime["tracking_uri"])
            artifact_root = Path(runtime["artifact_root"])
            artifact_root.mkdir(parents=True, exist_ok=True)

            experiment_name = "qos_prediction_inference"
            client = MlflowClient(tracking_uri)
            experiment = client.get_experiment_by_name(experiment_name)
            if experiment is None:
                experiment_id = client.create_experiment(
                    experiment_name,
                    artifact_location=artifact_root.as_uri(),
                )
            else:
                experiment_id = experiment.experiment_id

            mlflow.set_tracking_uri(tracking_uri)
            run_name = f"prediction-batch-{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}"
            with mlflow.start_run(experiment_id=experiment_id, run_name=run_name):
                mlflow.log_param("service", "prediction")
                mlflow.log_param("processed_nodes", ",".join(processed_nodes[:25]))
                mlflow.log_metric("prediction_count", float(len(results)))
                mlflow.log_metric("processed_node_count", float(len(processed_nodes)))
                mlflow.log_metric("skipped_node_count", float(len(skipped_nodes)))

                severity_counts: Dict[str, int] = {}
                for step, result in enumerate(results):
                    severity_counts[result.severity] = severity_counts.get(result.severity, 0) + 1
                    mlflow.log_metric(
                        "primary_metric_probability",
                        float(result.primary_metric_probability),
                        step=step,
                    )
                    mlflow.log_metric("confidence_score", float(result.confidence_score), step=step)
                    eta = result.primary_metric_eta_min
                    if isinstance(eta, (int, float)) and math.isfinite(float(eta)):
                        mlflow.log_metric("primary_metric_eta_min", float(eta), step=step)

                for severity, count in severity_counts.items():
                    safe_name = "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in severity)
                    mlflow.log_metric(f"severity_{safe_name}_count", float(count))

                payload = {
                    "created_at": datetime.utcnow().isoformat() + "Z",
                    "processed_nodes": processed_nodes,
                    "skipped_nodes": skipped_nodes,
                    "predictions": [self._serialize_result(result) for result in results],
                }
                with tempfile.TemporaryDirectory() as tmpdir:
                    artifact_path = Path(tmpdir) / "prediction_batch.json"
                    artifact_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
                    mlflow.log_artifact(str(artifact_path), artifact_path="prediction")
        except Exception:
            logger.exception("Failed to log prediction batch to MLflow")

    def _predict_frames(
        self,
        grouped_frames: Dict[str, Any],
        *,
        generate_llm: bool,
        persist: bool,
    ) -> BatchPredictionSummary:
        agent = self.get_agent()
        results: List[PredictionResult] = []
        processed_nodes: List[str] = []
        skipped_nodes: List[Dict[str, str]] = []

        for node_id, frame in grouped_frames.items():
            if len(frame) < LSTM_WINDOW:
                skipped_nodes.append({"node_id": str(node_id), "reason": f"need at least {LSTM_WINDOW} rows, got {len(frame)}"})
                continue
            try:
                result = agent.predict(node_id=str(node_id), history_raw=frame, generate_llm=generate_llm)
                results.append(result)
                processed_nodes.append(str(node_id))
            except Exception as exc:
                logger.exception("Prediction failed for node %s", node_id)
                skipped_nodes.append({"node_id": str(node_id), "reason": f"{type(exc).__name__}: {exc}"})

        self._enrich_fleet_context(results)
        if persist:
            self._persist_results(results)
        self._log_mlflow_prediction_batch(results, processed_nodes, skipped_nodes)
        return BatchPredictionSummary(
            predictions=[self._serialize_result(result) for result in results],
            processed_nodes=processed_nodes,
            skipped_nodes=skipped_nodes,
        )

    def predict_records(
        self,
        records: Iterable[Dict[str, Any]],
        *,
        generate_llm: bool = True,
        persist: bool = True,
    ) -> BatchPredictionSummary:
        import pandas as pd

        frame = pd.DataFrame(list(records))
        if frame.empty:
            return BatchPredictionSummary(predictions=[], processed_nodes=[], skipped_nodes=[])
        if "node_id" not in frame.columns:
            raise ValueError("records must include node_id")
        if "timestamp" not in frame.columns:
            raise ValueError("records must include timestamp")
        grouped = {
            str(node_id): group.sort_values("timestamp").reset_index(drop=True)
            for node_id, group in frame.groupby("node_id", sort=False)
        }
        return self._predict_frames(grouped, generate_llm=generate_llm, persist=persist)

    def predict_latest_from_repository(
        self,
        *,
        window_rows: int = 60,
        generate_llm: bool = True,
        persist: bool = True,
    ) -> BatchPredictionSummary:
        data = self._load_live_qos()
        if data.empty:
            return BatchPredictionSummary(predictions=[], processed_nodes=[], skipped_nodes=[])
        grouped = {
            str(node_id): group.sort_values("timestamp").tail(window_rows).reset_index(drop=True)
            for node_id, group in data.groupby("node_id", sort=False)
        }
        return self._predict_frames(grouped, generate_llm=generate_llm, persist=persist)

    def autonomous_run_once(
        self,
        *,
        window_rows: int = 60,
        generate_llm: bool = True,
        persist: bool = True,
        inject_monitoring: bool = False,
        monitoring_rows: int = 100,
    ) -> Dict[str, Any]:
        monitoring_seed = None
        if inject_monitoring:
            monitoring_seed = self.seed_monitoring_agent_kpis(min_rows=monitoring_rows)
        incident_sync = self.sync_incidents(replace=False)
        batch = self.predict_latest_from_repository(
            window_rows=window_rows,
            generate_llm=generate_llm,
            persist=persist,
        )
        return {
            "incident_sync": incident_sync,
            "monitoring_seed": monitoring_seed,
            "processed_nodes": batch.processed_nodes,
            "skipped_nodes": batch.skipped_nodes,
            "prediction_count": len(batch.predictions),
            "predictions": batch.predictions,
        }

    def recent_prediction_feed(self, limit: int = 25) -> List[Dict[str, Any]]:
        predictions = self.store.get_recent_predictions(limit=max(limit * 4, 100))
        visible = [
            prediction
            for prediction in predictions
            if prediction.node_id and not str(prediction.node_id).startswith("MON-")
        ]
        return [self._serialize_result(prediction) for prediction in visible[:limit]]

    def add_feedback(
        self,
        prediction_id: int,
        feedback_type: str,
        outcome_status: str = "",
        notes: str = "",
    ) -> Dict[str, Any]:
        feedback_id = self.store.add_feedback(prediction_id, feedback_type, outcome_status=outcome_status, notes=notes)
        prediction = self.store.get_prediction(prediction_id)
        return {
            "feedback_id": feedback_id,
            "prediction_id": prediction_id,
            "feedback": sanitize_json(self.store.get_feedback_for_prediction(prediction_id)),
            "prediction": self._serialize_result(prediction) if prediction else None,
        }

    def dashboard_summary(self, days_back: int = 7, recent_limit: int = 25) -> Dict[str, Any]:
        stats = self.store.get_statistics(days_back=days_back)
        recent = self.recent_prediction_feed(limit=recent_limit)
        latest_by_node: Dict[str, Dict[str, Any]] = {}
        for item in recent:
            node_id = str(item.get("node_id", ""))
            if not node_id:
                continue
            latest_by_node.setdefault(node_id, item)
        latest_packets = list(latest_by_node.values())
        top_candidates = sorted(
            latest_packets,
            key=lambda item: (
                SEVERITY_RANK.get(str(item.get("severity", "unknown")), -1),
                item.get("primary_metric_probability", 0.0),
                item.get("confidence_score", 0.0),
            ),
            reverse=True,
        )
        return {
            "period_days": days_back,
            "system_health": self.health(),
            "stats": sanitize_json(stats),
            "recent_predictions": recent,
            "latest_by_node": latest_packets,
            "priority_predictions": top_candidates[:10],
            "targets": list(TARGET_NAMES),
        }

    def get_prediction_detail(self, prediction_id: int) -> Dict[str, Any] | None:
        prediction = self.store.get_prediction(prediction_id)
        if prediction is None:
            return None
        return self._serialize_result(prediction)

    def node_timeseries(
        self,
        node_id: str,
        target: str | None = None,
        limit: int = 120,
    ) -> Dict[str, Any]:
        history = self.store.get_predictions_for_node(node_id, limit=limit)
        history = list(reversed(history))  # ascending time
        timestamps: List[str] = []
        primary_probs: List[float] = []
        confidences: List[float] = []
        severities: List[str] = []
        target_curve: List[float] = []
        per_target_curves: Dict[str, List[float]] = {name: [] for name in TARGET_NAMES}
        eta_curve: List[float | None] = []

        for item in history:
            timestamps.append(str(item.timestamp))
            primary_probs.append(float(item.primary_metric_probability))
            confidences.append(float(item.confidence_score))
            severities.append(str(item.severity))
            requested = target or item.primary_metric_name
            target_curve.append(float(item.risk_probs.get(requested, 0.0)))
            for name in TARGET_NAMES:
                per_target_curves[name].append(float(item.risk_probs.get(name, 0.0)))
            eta_value = item.primary_metric_eta_min
            eta_curve.append(
                float(eta_value) if isinstance(eta_value, (int, float)) and math.isfinite(float(eta_value)) else None
            )

        return sanitize_json(
            {
                "node_id": node_id,
                "target": target or (history[0].primary_metric_name if history else ""),
                "points": len(history),
                "timestamps": timestamps,
                "primary_probability": primary_probs,
                "confidence": confidences,
                "severity": severities,
                "target_probability": target_curve,
                "per_target": per_target_curves,
                "eta_minutes": eta_curve,
            }
        )

    def fleet_overview(self, days_back: int = 7) -> Dict[str, Any]:
        recent = self.recent_prediction_feed(limit=2000)
        latest_by_node: Dict[str, Dict[str, Any]] = {}
        for item in recent:
            node = str(item.get("node_id", ""))
            if not node or node.startswith("MON-"):
                continue
            latest_by_node.setdefault(node, item)

        nodes_payload: List[Dict[str, Any]] = []
        severity_counts: Dict[str, int] = {}
        domain_counts: Dict[str, int] = {}
        risk_aggregates: Dict[str, List[float]] = {name: [] for name in TARGET_NAMES}
        confidence_values: List[float] = []

        for node_id, item in latest_by_node.items():
            severity = str(item.get("severity", "unknown"))
            severity_counts[severity] = severity_counts.get(severity, 0) + 1
            confidence_values.append(float(item.get("confidence_score", 0.0)))
            for target, prob in (item.get("risk_probs") or {}).items():
                if target in risk_aggregates:
                    risk_aggregates[target].append(float(prob))
            domains = item.get("domain_hints") or []
            if domains:
                top_domain = str(domains[0].get("domain", "unknown"))
                domain_counts[top_domain] = domain_counts.get(top_domain, 0) + 1
            nodes_payload.append(
                {
                    "node_id": node_id,
                    "severity": severity,
                    "primary_metric": item.get("primary_metric_name", ""),
                    "primary_probability": item.get("primary_metric_probability", 0.0),
                    "confidence_score": item.get("confidence_score", 0.0),
                    "primary_eta_min": item.get("primary_metric_eta_min"),
                    "timestamp": item.get("timestamp", ""),
                    "top_domain": (domains[0].get("domain") if domains else ""),
                    "trend": (item.get("temporal_signals") or {}).get("trend_label", ""),
                    "fleet_rank": (item.get("fleet_context") or {}).get("fleet_rank"),
                    "risk_probs": item.get("risk_probs", {}),
                }
            )

        nodes_payload.sort(
            key=lambda entry: (
                SEVERITY_RANK.get(str(entry.get("severity", "unknown")), -1),
                float(entry.get("primary_probability") or 0.0),
            ),
            reverse=True,
        )
        average_risk = {
            name: round(float(np.mean(values)), 4) if values else 0.0
            for name, values in risk_aggregates.items()
        }
        return sanitize_json(
            {
                "period_days": days_back,
                "nodes": nodes_payload,
                "node_count": len(nodes_payload),
                "severity_distribution": severity_counts,
                "domain_distribution": domain_counts,
                "average_risk_by_target": average_risk,
                "average_confidence": round(float(np.mean(confidence_values)), 4) if confidence_values else 0.0,
            }
        )

    def model_overview(self) -> Dict[str, Any]:
        from config import (
            ENSEMBLE_LSTM_WEIGHT,
            ENSEMBLE_XGB_WEIGHT,
            LSTM_HYPERPARAMETERS,
            LSTM_WINDOW,
            PROPHET_CONFIG,
            RAG_CONFIG,
            SHAP_CONFIG,
            XGB_HYPERPARAMETERS,
        )

        models = self.model_status()
        artifacts = []
        if self.model_dir.exists():
            for path in sorted(self.model_dir.iterdir()):
                if not path.is_file():
                    continue
                stat = path.stat()
                artifacts.append(
                    {
                        "name": path.name,
                        "size_kb": round(stat.st_size / 1024.0, 1),
                        "modified_epoch": stat.st_mtime,
                    }
                )

        return sanitize_json(
            {
                "model_status": models,
                "ensemble_weights": {
                    "xgboost": ENSEMBLE_XGB_WEIGHT,
                    "lstm": ENSEMBLE_LSTM_WEIGHT,
                },
                "decision_paths": {
                    "snapshot_weight": ENSEMBLE_XGB_WEIGHT,
                    "sequence_weight": ENSEMBLE_LSTM_WEIGHT,
                    "history_window_rows": LSTM_WINDOW,
                    "forecast_ready": True,
                },
                "lstm": {
                    "window": LSTM_WINDOW,
                    "hyperparameters": LSTM_HYPERPARAMETERS,
                },
                "xgboost": {
                    "targets": list(TARGET_NAMES),
                    "hyperparameters": XGB_HYPERPARAMETERS,
                },
                "prophet": PROPHET_CONFIG,
                "shap": SHAP_CONFIG,
                "rag": {**RAG_CONFIG, **self.rag_status()},
                "llm": self.llm_status(),
                "mlflow": self.mlflow_status(),
                "monitoring": self.monitoring_status(),
                "artifacts": artifacts,
            }
        )

    def incident_sample(self, limit: int = 10) -> Dict[str, Any]:
        from data_pipeline.loader import load_incidents

        df = load_incidents(DATA_INCIDENTS_DIR)
        if df.empty:
            return {"count": 0, "incidents": []}
        sample = df.head(limit).to_dict(orient="records")
        return sanitize_json({"count": int(len(df)), "incidents": sample})

    def qos_feed(self, node_id: str | None = None, limit: int = 120) -> Dict[str, Any]:
        df = self._load_live_qos()
        if df.empty:
            return {"count": 0, "rows": []}
        if node_id:
            df = df[df["node_id"].astype(str) == str(node_id)]
        if df.empty:
            return {"count": 0, "rows": []}
        df = df.sort_values("timestamp").tail(limit)
        keep = [
            "timestamp",
            "node_id",
            "latency_ms",
            "jitter_ms",
            "throughput_mbps",
            "packet_loss_pct",
            "mos_estimate",
            "queue_length",
            "active_connections",
            "rsrp_dbm",
            "sinr_db",
            "anomaly_score",
        ]
        cols = [c for c in keep if c in df.columns]
        df = df[cols].copy()
        if "timestamp" in df.columns:
            df["timestamp"] = df["timestamp"].astype(str)
        return sanitize_json({"count": int(len(df)), "rows": df.to_dict(orient="records")})

    def driver_frequency(
        self,
        node_id: str,
        target: str | None = None,
        days_back: int = 14,
    ) -> Dict[str, Any]:
        from collections import defaultdict

        history = self.store.get_predictions_for_node(node_id, limit=500, days_back=days_back)
        if not history:
            return {"node_id": node_id, "target": target or "", "drivers": []}

        chosen_target = target or history[0].primary_metric_name
        bucket: Dict[str, Dict[str, float]] = defaultdict(lambda: {"count": 0.0, "impact_sum": 0.0})
        for prediction in history:
            drivers = prediction.top_3_drivers.get(chosen_target, [])
            for driver in drivers:
                feature = str(driver.get("feature", ""))
                if not feature:
                    continue
                bucket[feature]["count"] += 1.0
                try:
                    bucket[feature]["impact_sum"] += abs(float(driver.get("value", 0.0)))
                except (TypeError, ValueError):
                    pass

        rows = []
        for feature, agg in bucket.items():
            count = agg["count"]
            avg_impact = agg["impact_sum"] / max(count, 1.0)
            rows.append(
                {
                    "feature": feature,
                    "frequency": int(count),
                    "avg_impact": round(avg_impact, 4),
                }
            )
        rows.sort(key=lambda item: (item["frequency"], item["avg_impact"]), reverse=True)
        return sanitize_json(
            {
                "node_id": node_id,
                "target": chosen_target,
                "history_size": len(history),
                "drivers": rows[:15],
            }
        )
