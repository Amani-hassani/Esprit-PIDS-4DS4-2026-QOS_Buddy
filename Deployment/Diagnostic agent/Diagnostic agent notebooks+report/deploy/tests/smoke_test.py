from __future__ import annotations

import json
import sys
import urllib.request


BASE_URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"


def get_json(path: str):
    with urllib.request.urlopen(BASE_URL + path, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def post_json(path: str, payload: dict | None = None):
    request = urllib.request.Request(
        BASE_URL + path,
        data=json.dumps(payload or {}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def assert_true(condition: bool, message: str):
    if not condition:
        raise AssertionError(message)


def main():
    health = get_json("/api/health")
    assert_true(health["status"] == "ok", "health status is not ok")
    assert_true(health["faiss_required"] is True, "FAISS must be mandatory")
    assert_true(health["faiss_backend"] == "faiss.IndexFlatL2", "native FAISS backend is not active")
    assert_true(health["faiss_vectors"] > 0, "FAISS index has no vectors")
    assert_true(len(health["root_causes"]) == 8, "expected 8 root causes")
    assert_true(health["dynamic_ingestion"] is True, "dynamic ingestion is not enabled")

    dashboard = get_json("/api/dashboard")
    assert_true(dashboard["summary"]["active_incidents"] > 0, "dashboard has no incidents")
    assert_true(dashboard["faiss"]["backend"] == "faiss.IndexFlatL2", "dashboard FAISS backend mismatch")

    incidents = get_json("/api/incidents")
    assert_true(len(incidents) >= 8, "expected at least 8 testable incidents")
    first = get_json(f"/api/incidents/{incidents[0]['id']}")
    assert_true("prototype_neighbors" in first, "incident detail missing prototype neighbors")
    assert_true(len(first["prototype_neighbors"]) == 5, "expected 5 FAISS neighbors")
    assert_true("llm_explanation" in first, "incident detail missing LLM explanation")
    assert_true("protocol_pipeline" in first, "incident detail missing protocol pipeline")
    assert_true("fusion" in first, "incident detail missing fusion output")
    assert_true("autoencoder_evidence" in first, "incident detail missing autoencoder evidence")

    live_payload = {
        "event_id": "smoke-live-event",
        "monitoring": {
            "timestamp": "2026-04-28T18:20:00Z",
            "node_id": "N-SMOKE",
            "cell_id": "CELL-SMOKE",
            "zone_id": "Z-SMOKE",
            "latency_ms": 310,
            "jitter_ms": 78,
            "packet_loss_pct": 1.2,
            "throughput_mbps": 1.4,
            "bandwidth_util_pct": 91,
            "queue_length": 188,
            "active_connections": 145,
            "tcp_retransmit_rate": 3.1,
            "bler_proxy_pct": 2.2,
            "sinr_db": 15,
            "cqi": 9,
            "mcs": 16,
            "rssi_dbm": -72,
            "rsrp_dbm": -92,
            "signal_health_score": 78,
            "wifi_signal_score": 80,
            "cellular_signal_score": 78,
            "mos_estimate": 2.8,
        },
        "detection": {
            "anomaly_detected": True,
            "anomaly_type": "capacity_latency_smoke",
            "anomaly_score": 0.91,
        },
        "prediction": {
            "horizon_minutes": 15,
            "sla_risk": 0.84,
            "confidence": 0.88,
        },
    }
    live_incident = post_json("/api/ingest", live_payload)
    assert_true(live_incident["source"] == "live", "ingested incident did not use live source")
    assert_true(live_incident["source_event_id"] == "smoke-live-event", "source event id was not preserved")
    assert_true("optimization_handoff" in live_incident, "optimization handoff was not queued")
    assert_true("data_quality" in live_incident, "data quality gate output missing")
    assert_true("fusion" in live_incident, "fusion output missing")
    assert_true("memory_guided_autoencoder" in live_incident["protocol_pipeline"], "autoencoder protocol output missing")

    split_event_id = "smoke-split-event"
    waiting_detection = post_json(
        "/api/detection-agent/events",
        {
            "event_id": split_event_id,
            "timestamp": "2026-04-28T18:21:00Z",
            "node_id": "N-SMOKE",
            "cell_id": "CELL-SMOKE",
            "zone_id": "Z-SMOKE",
            "detection": {
                "anomaly_detected": True,
                "anomaly_type": "radio_packet_loss_split",
                "anomaly_score": 0.87,
            },
        },
    )
    assert_true(waiting_detection["status"] == "waiting_for_monitoring", "detection-only event should wait for monitoring")

    waiting_prediction = post_json(
        "/api/prediction-agent/events",
        {
            "event_id": split_event_id,
            "timestamp": "2026-04-28T18:21:00Z",
            "node_id": "N-SMOKE",
            "cell_id": "CELL-SMOKE",
            "zone_id": "Z-SMOKE",
            "prediction": {
                "root_cause": "RC_PACKET_LOSS",
                "confidence": 0.72,
                "horizon_minutes": 10,
                "sla_risk": 0.79,
            },
        },
    )
    assert_true(waiting_prediction["status"] == "waiting_for_monitoring", "prediction-only event should wait for monitoring")

    split_incident = post_json(
        "/api/monitoring-agent/events",
        {
            "event_id": split_event_id,
            "timestamp": "2026-04-28T18:21:03Z",
            "node_id": "N-SMOKE",
            "cell_id": "CELL-SMOKE",
            "zone_id": "Z-SMOKE",
            "monitoring": {
                "latency_ms": 180,
                "jitter_ms": 42,
                "packet_loss_pct": 6.8,
                "throughput_mbps": 4.6,
                "bandwidth_util_pct": 63,
                "queue_length": 71,
                "active_connections": 91,
                "tcp_retransmit_rate": 8.4,
                "bler_proxy_pct": 11.2,
                "sinr_db": 8,
                "cqi": 5,
                "mcs": 17,
                "rssi_dbm": -84,
                "rsrp_dbm": -107,
                "signal_health_score": 55,
                "wifi_signal_score": 58,
                "cellular_signal_score": 52,
                "mos_estimate": 2.6,
            },
        },
    )
    assert_true(split_incident["source_event_id"] == split_event_id, "split event id was not preserved")
    assert_true("detection" in split_incident["pipeline_inputs"], "split detection input missing")
    assert_true("prediction" in split_incident["pipeline_inputs"], "split prediction input missing")
    assert_true(
        {"detection", "monitoring", "prediction"}.issubset(
            set(split_incident["protocol_pipeline"]["context_fusion"]["present_sources"])
        ),
        "context fusion did not merge all separate agent sources",
    )

    send_result = post_json(f"/api/incidents/{live_incident['id']}/send-to-optimization")
    assert_true(send_result["status"].startswith("queued"), "optimization handoff was not queued")

    outbox = get_json("/api/optimization/outbox")
    assert_true(len(outbox) > 0, "optimization outbox is empty")

    print("Smoke test passed")
    print(json.dumps({
        "faiss_vectors": health["faiss_vectors"],
        "incident_count": len(incidents),
        "first_incident": first["id"],
        "first_root_cause": first["root_cause"],
        "live_incident": live_incident["id"],
        "live_root_cause": live_incident["root_cause"],
    }, indent=2))


if __name__ == "__main__":
    main()
