"""Backend API smoke tests that do not require model inference."""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.api_enhanced import app, service


client = TestClient(app)


def test_health_endpoint_returns_platform_status():
    response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert "status" in payload
    assert "models" in payload
    assert "mlflow" in payload
    assert "monitoring" in payload
    assert "storage" in payload
    assert "required_qos_columns" in payload


def test_qos_schema_endpoint_lists_required_columns():
    response = client.get("/schema/qos")
    assert response.status_code == 200
    payload = response.json()
    assert "required_columns" in payload
    assert "node_id" in payload["required_columns"]
    assert "timestamp" in payload["required_columns"]


def test_predict_endpoint_rejects_missing_node_id():
    response = client.post(
        "/predict",
        json={"records": [{"timestamp": "2026-04-27T10:00:00Z"}], "generate_llm": False, "persist": False},
    )
    assert response.status_code == 400
    assert "node_id" in response.json()["detail"]


def test_feedback_endpoint_accepts_payload():
    response = client.post(
        "/predictions/1/feedback",
        json={"feedback_type": "useful", "outcome_status": "pending", "notes": "smoke test"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["prediction_id"] == 1
    assert "feedback" in payload


def test_monitoring_ingest_endpoint_delegates_to_service(monkeypatch):
    monkeypatch.setattr(
        service,
        "ingest_monitoring_records",
        lambda records, **kwargs: {
            "record_count": len(records),
            "nodes": ["N1"],
            "processed_nodes": ["N1"],
            "skipped_nodes": [],
            "prediction_count": 1,
            "predictions": [],
            "monitoring": {"row_count": 1},
        },
    )
    response = client.post(
        "/api/monitoring/ingest",
        json={
            "records": [
                {
                    "timestamp": "2026-04-27T10:00:00Z",
                    "node_id": "N1",
                    "latency_ms": 10.0,
                    "jitter_ms": 1.0,
                    "throughput_mbps": 5.0,
                    "packet_loss_pct": 0.0,
                    "mos_estimate": 4.0,
                    "queue_length": 3,
                    "active_connections": 10,
                }
            ],
            "generate_llm": True,
            "persist": True,
            "sync_incidents": False,
            "cadence_seconds": 30,
            "window_rows": 60,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["record_count"] == 1
    assert payload["prediction_count"] == 1


def test_monitoring_reset_endpoint_delegates_to_service(monkeypatch):
    monkeypatch.setattr(
        service,
        "reset_monitoring_feed",
        lambda: {"status": "reset", "monitoring": {"row_count": 0}},
    )
    response = client.post("/api/monitoring/reset")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "reset"
