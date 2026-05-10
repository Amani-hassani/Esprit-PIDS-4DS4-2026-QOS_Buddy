"""FastAPI application for the standalone QoS Buddy prediction agent."""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from pydantic import BaseModel, Field

from backend.service import PredictionPlatformService, QOS_REQUIRED_COLUMNS, sanitize_json
from config import PROJECT_ROOT


class MonitoringBatchRequest(BaseModel):
    records: List[Dict[str, Any]] = Field(default_factory=list)
    generate_llm: bool = True
    persist: bool = True


class MonitoringIngestRequest(MonitoringBatchRequest):
    sync_incidents: bool = False
    cadence_seconds: int = Field(default=30, ge=1, le=3600)
    window_rows: int = Field(default=60, ge=20, le=720)


class AutonomousRunRequest(BaseModel):
    window_rows: int = Field(default=60, ge=20, le=720)
    generate_llm: bool = True
    persist: bool = True
    inject_monitoring: bool = True
    monitoring_rows: int = Field(default=120, ge=100, le=2000)


class IncidentSyncRequest(BaseModel):
    replace: bool = False


class FeedbackRequest(BaseModel):
    feedback_type: str
    outcome_status: str = ""
    notes: str = ""


app = FastAPI(
    title="QoS Buddy Prediction Agent",
    version="4.1.0",
    description="Standalone risk intelligence, trust scoring, incident memory, and LLM NOC synthesis.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

service = PredictionPlatformService()


@app.on_event("startup")
def startup_runtime_services() -> None:
    service.ensure_mlflow_running()


@app.get("/health")
@app.get("/api/health")
def health() -> Dict[str, Any]:
    return service.quick_health()


@app.get("/health/full")
@app.get("/api/health/full")
def health_full() -> Dict[str, Any]:
    return service.health()


@app.get("/schema/qos")
@app.get("/api/schema/qos")
def qos_schema() -> Dict[str, Any]:
    return {
        "required_columns": list(QOS_REQUIRED_COLUMNS),
        "notes": [
            "Provide at least 20 rows per node for LSTM-backed inference.",
            "Prediction quality improves with radio, transport, and anomaly columns.",
            "The agent outputs standalone risk, trust, evidence, temporal, and fleet context fields.",
        ],
    }


@app.get("/dashboard/summary")
@app.get("/api/dashboard/summary")
def dashboard_summary(
    days_back: int = Query(default=7, ge=1, le=90),
    recent_limit: int = Query(default=25, ge=1, le=200),
) -> Dict[str, Any]:
    return service.dashboard_summary(days_back=days_back, recent_limit=recent_limit)


@app.get("/dashboard/timeseries")
@app.get("/api/dashboard/timeseries")
def dashboard_timeseries(
    node_id: str = Query(..., description="Node ID to retrieve risk timeline for"),
    target: str = Query(default="", description="Optional risk target filter"),
    limit: int = Query(default=120, ge=10, le=720),
) -> Dict[str, Any]:
    return service.node_timeseries(node_id=node_id, target=target or None, limit=limit)


@app.get("/dashboard/fleet")
@app.get("/api/dashboard/fleet")
def dashboard_fleet(days_back: int = Query(default=7, ge=1, le=90)) -> Dict[str, Any]:
    return service.fleet_overview(days_back=days_back)


@app.get("/dashboard/models")
@app.get("/api/dashboard/models")
def dashboard_models() -> Dict[str, Any]:
    return service.model_overview()


@app.get("/dashboard/incidents/sample")
@app.get("/api/dashboard/incidents/sample")
def incident_sample(limit: int = Query(default=10, ge=1, le=100)) -> Dict[str, Any]:
    return service.incident_sample(limit=limit)


@app.get("/dashboard/qos-feed")
@app.get("/api/dashboard/qos-feed")
def qos_feed(
    node_id: str = Query(default="", description="Optional node filter"),
    limit: int = Query(default=120, ge=10, le=720),
) -> Dict[str, Any]:
    return service.qos_feed(node_id=node_id or None, limit=limit)


@app.get("/dashboard/drivers")
@app.get("/api/dashboard/drivers")
def dashboard_drivers(
    node_id: str = Query(...),
    target: str = Query(default=""),
    days_back: int = Query(default=14, ge=1, le=90),
) -> Dict[str, Any]:
    return service.driver_frequency(node_id=node_id, target=target or None, days_back=days_back)


@app.get("/predictions")
@app.get("/api/predictions")
def recent_predictions(limit: int = Query(default=25, ge=1, le=200)) -> List[Dict[str, Any]]:
    return service.recent_prediction_feed(limit=limit)


@app.get("/predictions/{prediction_id}")
@app.get("/api/predictions/{prediction_id}")
def prediction_detail(prediction_id: int) -> Dict[str, Any]:
    payload = service.get_prediction_detail(prediction_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="prediction not found")
    return payload


@app.post("/predict")
@app.post("/api/predict")
def predict_batch(request: MonitoringBatchRequest) -> Dict[str, Any]:
    try:
        result = service.predict_records(
            request.records,
            generate_llm=request.generate_llm,
            persist=request.persist,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "prediction_count": len(result.predictions),
        "processed_nodes": result.processed_nodes,
        "skipped_nodes": result.skipped_nodes,
        "predictions": result.predictions,
    }


@app.post("/monitoring/predict")
@app.post("/api/monitoring/predict")
def monitoring_predict(request: MonitoringBatchRequest) -> Dict[str, Any]:
    return predict_batch(request)


@app.post("/monitoring/ingest")
@app.post("/api/monitoring/ingest")
def monitoring_ingest(request: MonitoringIngestRequest) -> Dict[str, Any]:
    try:
        return service.ingest_monitoring_records(
            request.records,
            generate_llm=request.generate_llm,
            persist=request.persist,
            sync_incidents=request.sync_incidents,
            cadence_seconds=request.cadence_seconds,
            window_rows=request.window_rows,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/monitoring/incidents/sync")
@app.post("/api/monitoring/incidents/sync")
def sync_incidents(request: IncidentSyncRequest) -> Dict[str, Any]:
    return service.sync_incidents(replace=request.replace)


@app.post("/monitoring/reset")
@app.post("/api/monitoring/reset")
def reset_monitoring() -> Dict[str, Any]:
    return service.reset_monitoring_feed()


@app.post("/ops/autonomous/run-once")
@app.post("/api/ops/autonomous/run-once")
def autonomous_run(request: AutonomousRunRequest) -> Dict[str, Any]:
    return service.autonomous_run_once(
        window_rows=request.window_rows,
        generate_llm=request.generate_llm,
        persist=request.persist,
        inject_monitoring=request.inject_monitoring,
        monitoring_rows=request.monitoring_rows,
    )


@app.post("/predictions/{prediction_id}/feedback")
@app.post("/api/predictions/{prediction_id}/feedback")
def add_feedback(prediction_id: int, request: FeedbackRequest) -> Dict[str, Any]:
    return service.add_feedback(
        prediction_id=prediction_id,
        feedback_type=request.feedback_type,
        outcome_status=request.outcome_status,
        notes=request.notes,
    )


@app.get("/ops/status")
@app.get("/api/ops/status")
def ops_status() -> Dict[str, Any]:
    return sanitize_json(
        {
            "health": service.health(),
            "summary": service.dashboard_summary(days_back=7, recent_limit=10),
        }
    )


# ────────────────────────────────────────────────────────────
# Static frontend (built SvelteKit dashboard)
# ────────────────────────────────────────────────────────────
_FRONTEND_BUILD = PROJECT_ROOT / "frontend" / "build"
if _FRONTEND_BUILD.exists():
    app.mount(
        "/_app",
        StaticFiles(directory=_FRONTEND_BUILD / "_app"),
        name="frontend_app",
    )

    @app.get("/", include_in_schema=False)
    def serve_root() -> FileResponse:
        return FileResponse(_FRONTEND_BUILD / "index.html")

    @app.get("/{full_path:path}", include_in_schema=False)
    def serve_spa(full_path: str) -> FileResponse:
        candidate = _FRONTEND_BUILD / full_path
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_FRONTEND_BUILD / "index.html")
