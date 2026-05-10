from __future__ import annotations

from deployment import telemetry_cache as cache_mod


def test_telemetry_snapshot_payload_caches_by_source_signature(monkeypatch):
    cache_mod.reset_telemetry_cache()

    calls = {"count": 0}

    monkeypatch.setattr(cache_mod.MonitoringSnapshotsRepo, "latest", lambda cell_id=None: {"id": "mon-1", "cell_id": cell_id})
    monkeypatch.setattr(cache_mod.DiagnosticContractsRepo, "latest", lambda cell_id=None: None)

    def fake_snapshot(cell_id=None):
        calls["count"] += 1
        return {
            "root_cause": "RC_TRANSPORT_DELAY",
            "confidence": 0.9,
            "evidence": ["queue pressure"],
            "recommended_action": "ACT_REDUCE_BUFFER_SIZE",
            "action_spec": type(
                "Spec",
                (),
                {
                    "action_code": "ACT_REDUCE_BUFFER_SIZE",
                    "risk_level": type("Risk", (), {"value": "low"})(),
                    "estimated_impact": type("Impact", (), {"value": "local"})(),
                    "requires_human": False,
                    "is_reversible": True,
                    "autonomy": "auto",
                    "reason": "reversible",
                },
            )(),
            "state": {"latency_ms": 120.0},
        }

    monkeypatch.setattr(cache_mod, "latest_cell_snapshot", fake_snapshot)
    monkeypatch.setattr(cache_mod, "health_score", lambda state: 77.0)

    first = cache_mod.telemetry_snapshot_payload("CELL-1")
    second = cache_mod.telemetry_snapshot_payload("CELL-1")

    assert calls["count"] == 1
    assert first["health_score"] == 77.0
    assert second["action_spec"]["action_code"] == "ACT_REDUCE_BUFFER_SIZE"
