from __future__ import annotations

from pathlib import Path

from backend.service import PredictionPlatformService


def test_seed_monitoring_agent_kpis_writes_minimum_rows(tmp_path: Path):
    service = PredictionPlatformService()
    service.monitoring_kpi_path = tmp_path / "monitoring_agent_kpis.csv"

    result = service.seed_monitoring_agent_kpis(min_rows=100)

    assert result["status"] == "seeded"
    assert result["row_count"] >= 100
    assert result["node_count"] >= 1
    assert service.monitoring_kpi_path.exists()


def test_health_exposes_monitoring_and_mlflow_sections(monkeypatch):
    service = PredictionPlatformService()
    monkeypatch.setattr(service, "mlflow_status", lambda: {"available": True, "status": "running"})
    monkeypatch.setattr(service, "monitoring_status", lambda: {"status": "ready", "row_count": 120, "node_count": 3})

    payload = service.health()

    assert "mlflow" in payload
    assert "monitoring" in payload
    assert payload["mlflow"]["status"] == "running"
    assert payload["monitoring"]["row_count"] == 120
