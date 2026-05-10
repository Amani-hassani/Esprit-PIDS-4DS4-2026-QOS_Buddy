from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from backend.service import PredictionPlatformService
from scripts.replay_monitoring import build_replay_frame, iter_replay_batches


def _monitoring_rows() -> list[dict[str, object]]:
    return [
        {
            "timestamp": "2026-04-27T10:00:00Z",
            "node_id": "N1",
            "latency_ms": 20.0,
            "jitter_ms": 4.0,
            "throughput_mbps": 8.0,
            "packet_loss_pct": 0.0,
            "mos_estimate": 4.2,
            "queue_length": 11,
            "active_connections": 20,
        },
        {
            "timestamp": "2026-04-27T10:00:00Z",
            "node_id": "N2",
            "latency_ms": 24.0,
            "jitter_ms": 5.0,
            "throughput_mbps": 7.5,
            "packet_loss_pct": 0.0,
            "mos_estimate": 4.1,
            "queue_length": 12,
            "active_connections": 21,
        },
        {
            "timestamp": "2026-04-27T10:00:30Z",
            "node_id": "N1",
            "latency_ms": 27.0,
            "jitter_ms": 6.0,
            "throughput_mbps": 7.2,
            "packet_loss_pct": 0.1,
            "mos_estimate": 4.0,
            "queue_length": 13,
            "active_connections": 19,
        },
        {
            "timestamp": "2026-04-27T10:00:30Z",
            "node_id": "N2",
            "latency_ms": 29.0,
            "jitter_ms": 7.0,
            "throughput_mbps": 6.9,
            "packet_loss_pct": 0.1,
            "mos_estimate": 3.9,
            "queue_length": 14,
            "active_connections": 18,
        },
    ]


def test_ingest_monitoring_records_rejects_missing_columns(tmp_path: Path):
    service = PredictionPlatformService()
    service.monitoring_kpi_path = tmp_path / "monitoring.csv"

    with pytest.raises(ValueError, match="missing required columns"):
        service.ingest_monitoring_records([{"timestamp": "2026-04-27T10:00:00Z", "node_id": "N1"}], persist=False)


def test_ingest_monitoring_records_rewrites_timestamp_by_source_step(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    service = PredictionPlatformService()
    service.monitoring_kpi_path = tmp_path / "monitoring.csv"

    def fake_live_qos() -> pd.DataFrame:
        frame = pd.read_csv(service.monitoring_kpi_path)
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
        return frame

    captured: dict[str, object] = {}

    monkeypatch.setattr(service, "_load_live_qos", fake_live_qos)

    def fake_predict_frames(grouped_frames, *, generate_llm, persist):
        captured["grouped_frames"] = grouped_frames
        captured["generate_llm"] = generate_llm
        captured["persist"] = persist

        class Summary:
            predictions = [{"node_id": "N1"}, {"node_id": "N2"}]
            processed_nodes = ["N1", "N2"]
            skipped_nodes = []

        return Summary()

    monkeypatch.setattr(service, "_predict_frames", fake_predict_frames)

    result = service.ingest_monitoring_records(
        _monitoring_rows(),
        generate_llm=False,
        persist=True,
        cadence_seconds=30,
        window_rows=10,
    )

    written = pd.read_csv(service.monitoring_kpi_path)
    assert len(written) == 4
    assert written.loc[0, "timestamp"] == written.loc[1, "timestamp"]
    assert written.loc[2, "timestamp"] == written.loc[3, "timestamp"]
    assert written.loc[0, "timestamp"] != written.loc[2, "timestamp"]
    assert result["prediction_count"] == 2
    assert result["processed_nodes"] == ["N1", "N2"]

    grouped = captured["grouped_frames"]
    assert set(grouped) == {"N1", "N2"}
    assert len(grouped["N1"]) == 2
    assert len(grouped["N2"]) == 2
    assert captured["generate_llm"] is False
    assert captured["persist"] is True


def test_ingest_monitoring_records_optionally_syncs_incidents(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    service = PredictionPlatformService()
    service.monitoring_kpi_path = tmp_path / "monitoring.csv"

    monkeypatch.setattr(service, "_load_live_qos", lambda: pd.DataFrame(_monitoring_rows()))
    monkeypatch.setattr(
        service,
        "_predict_frames",
        lambda grouped_frames, *, generate_llm, persist: type(
            "Summary",
            (),
            {"predictions": [], "processed_nodes": [], "skipped_nodes": []},
        )(),
    )
    monkeypatch.setattr(service, "sync_incidents", lambda replace=False: {"status": "ok", "ingested": 7})

    result = service.ingest_monitoring_records(
        _monitoring_rows()[:1],
        generate_llm=False,
        persist=False,
        sync_incidents=True,
    )

    assert result["incident_sync"]["status"] == "ok"
    assert result["incident_sync"]["ingested"] == 7


def test_build_replay_frame_prefers_incident_aligned_rows():
    qos = pd.DataFrame(
        [
            {"timestamp": "2026-04-27T10:00:00Z", "node_id": "N1", "latency_ms": 20},
            {"timestamp": "2026-04-27T10:00:30Z", "node_id": "N1", "latency_ms": 21},
            {"timestamp": "2026-04-27T10:01:00Z", "node_id": "N2", "latency_ms": 30},
            {"timestamp": "2026-04-27T10:01:30Z", "node_id": "N2", "latency_ms": 31},
        ]
    )
    incidents = pd.DataFrame(
        [
            {
                "incident_id": "INC-1",
                "node_id": "N1",
                "start_timestamp": "2026-04-27T10:00:15Z",
                "end_timestamp": "2026-04-27T10:00:45Z",
            }
        ]
    )

    replay = build_replay_frame(qos, incidents, min_rows=2, lookback_minutes=1, lookahead_minutes=1)

    assert list(replay["node_id"].unique()) == ["N1"]
    assert len(replay) == 2


def test_iter_replay_batches_groups_timestamps():
    frame = pd.DataFrame(_monitoring_rows())
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)

    batches = list(iter_replay_batches(frame, timestamps_per_step=2))

    assert len(batches) == 1
    assert len(batches[0]) == 4
    assert batches[0]["timestamp"].nunique() == 2


def test_build_replay_frame_interleaves_multiple_scenarios():
    qos = pd.DataFrame(
        [
            {"timestamp": "2026-04-27T10:00:00Z", "node_id": "N1", "latency_ms": 20},
            {"timestamp": "2026-04-27T10:00:30Z", "node_id": "N1", "latency_ms": 21},
            {"timestamp": "2026-04-27T10:01:00Z", "node_id": "N2", "latency_ms": 40},
            {"timestamp": "2026-04-27T10:01:30Z", "node_id": "N2", "latency_ms": 41},
            {"timestamp": "2026-04-27T10:02:00Z", "node_id": "N1", "latency_ms": 22},
            {"timestamp": "2026-04-27T10:02:30Z", "node_id": "N2", "latency_ms": 42},
        ]
    )
    incidents = pd.DataFrame(
        [
            {
                "incident_id": "INC-1",
                "node_id": "N1",
                "incident_type": "weak_signal",
                "severity": "critical",
                "max_score": 0.9,
                "start_timestamp": "2026-04-27T10:00:15Z",
                "end_timestamp": "2026-04-27T10:00:45Z",
            },
            {
                "incident_id": "INC-2",
                "node_id": "N2",
                "incident_type": "low_throughput",
                "severity": "high",
                "max_score": 0.8,
                "start_timestamp": "2026-04-27T10:01:05Z",
                "end_timestamp": "2026-04-27T10:01:35Z",
            },
        ]
    )

    replay = build_replay_frame(qos, incidents, min_rows=4, lookback_minutes=1, lookahead_minutes=1, max_scenarios=2)

    assert set(replay["node_id"].astype(str).unique()) == {"N1", "N2"}
    assert replay["node_id"].astype(str).iloc[0] != replay["node_id"].astype(str).iloc[1]
