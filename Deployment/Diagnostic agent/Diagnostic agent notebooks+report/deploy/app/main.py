from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .dynamic_runtime import build_runtime


STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(
    title="QoS Buddy Diagnostic Agent",
    version="1.0.0",
    description="Random Forest + GRU + mandatory FAISS deployment for 8 root-cause contracts.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

runtime = build_runtime()

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class PredictionRequest(BaseModel):
    features: dict[str, Any]


class IngestRequest(BaseModel):
    event_id: str | None = None
    timestamp: str | None = None
    node_id: str | None = None
    cell_id: str | None = None
    zone_id: str | None = None
    monitoring: dict[str, Any] = Field(default_factory=dict)
    detection: dict[str, Any] = Field(default_factory=dict)
    prediction: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


@app.get("/")
def root() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "faiss_required": True,
        "faiss_backend": "faiss.IndexFlatL2",
        "faiss_vectors": int(runtime.faiss_index.ntotal),
        "root_causes": list(runtime.contracts.keys()),
        "dynamic_ingestion": True,
        "llm": runtime.llm.status,
    }


@app.get("/api/dashboard")
def dashboard() -> dict[str, Any]:
    return runtime.dashboard()


@app.get("/api/incidents")
def incidents() -> list[dict[str, Any]]:
    return runtime.incidents


@app.get("/api/incidents/{incident_id}")
def incident_detail(incident_id: str) -> dict[str, Any]:
    detail = runtime.incident_detail(incident_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return detail


@app.get("/api/model-health")
def model_health() -> dict[str, Any]:
    return runtime.model_health()


@app.post("/api/predict")
def predict(payload: PredictionRequest) -> dict[str, Any]:
    return runtime.ingest_event({"monitoring": payload.features, "detection": {}, "prediction": {}})


@app.post("/api/ingest")
def ingest(payload: IngestRequest) -> dict[str, Any]:
    return runtime.receive_agent_event(payload.model_dump(), source_hint="combined")


@app.post("/api/open/diagnose")
def open_diagnose(payload: IngestRequest) -> dict[str, Any]:
    return runtime.receive_agent_event(payload.model_dump(), source_hint="combined")


@app.post("/api/monitoring-agent/events")
def monitoring_agent_event(payload: IngestRequest) -> dict[str, Any]:
    return runtime.receive_agent_event(payload.model_dump(), source_hint="monitoring")


@app.post("/api/prediction-detection/events")
def prediction_detection_event(payload: IngestRequest) -> dict[str, Any]:
    return runtime.receive_agent_event(payload.model_dump(), source_hint="prediction_detection")


@app.post("/api/detection-agent/events")
def detection_agent_event(payload: IngestRequest) -> dict[str, Any]:
    return runtime.receive_agent_event(payload.model_dump(), source_hint="detection")


@app.post("/api/prediction-agent/events")
def prediction_agent_event(payload: IngestRequest) -> dict[str, Any]:
    return runtime.receive_agent_event(payload.model_dump(), source_hint="prediction")


@app.post("/api/demo/ingest-next")
def demo_ingest_next() -> dict[str, Any]:
    return runtime.demo_ingest_next()


@app.post("/api/incidents/{incident_id}/send-to-optimization")
def send_to_optimization(incident_id: str) -> dict[str, Any]:
    try:
        return runtime.send_to_optimization(incident_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Incident not found")


@app.get("/api/optimization/outbox")
def optimization_outbox() -> list[dict[str, Any]]:
    return runtime.optimization_outbox


@app.post("/api/optimization/outbox/{handoff_id}/ack")
def ack_optimization(handoff_id: str) -> dict[str, Any]:
    try:
        return runtime.ack_optimization(handoff_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Optimization handoff not found")
