from __future__ import annotations

import httpx
import pandas as pd
import pytest
from pathlib import Path

from deployment.api import create_app
from deployment.api.deps import reset_reasoner_for_tests
from deployment.api.events import reset_bus_for_tests
from deployment.api.routes.stream import _require_viewer_for_stream
from deployment.core import settings as settings_mod
from deployment.llmops import drift as drift_mod
from deployment.llmops.client import LLMCall, LLMResponse
from deployment.mlops import reset_mlflow_cache
from deployment.store.db import reset_for_tests
from deployment.store.repos import ApprovalsRepo, DecisionsRepo, MonitoringSnapshotsRepo, SessionsRepo
from deployment.telemetry_cache import reset_telemetry_cache


@pytest.fixture(autouse=True)
def clean():
    reset_for_tests()
    reset_bus_for_tests()
    reset_reasoner_for_tests()
    settings_mod.get_settings.cache_clear()
    drift_mod._training_stats.cache_clear()
    reset_mlflow_cache()
    reset_telemetry_cache()
    yield
    reset_for_tests()
    reset_bus_for_tests()
    reset_reasoner_for_tests()
    settings_mod.get_settings.cache_clear()
    drift_mod._training_stats.cache_clear()
    reset_mlflow_cache()
    reset_telemetry_cache()


class StubReasoner:
    def __init__(self) -> None:
        self.model = "stub-qwen"
        self.url = "stub"

    def call(self, call: LLMCall) -> LLMResponse:
        # Return unavailable so decide() uses the hybrid fallback (no network required).
        return LLMResponse(
            available=False,
            model=self.model,
            content={},
            prompt_hash="x" * 16,
            prompt_version="0",
            error="stubbed",
        )

    def _probe(self):
        return False, "stubbed"


def _write_temp_dotenv(contents: str):
    path = Path(".env")
    original = path.read_text(encoding="utf-8")

    class _Restore:
        def __enter__(self):
            path.write_text(contents, encoding="utf-8")
            settings_mod.get_settings.cache_clear()
            return path

        def __exit__(self, exc_type, exc, tb):
            path.write_text(original, encoding="utf-8")
            settings_mod.get_settings.cache_clear()

    return _Restore()


@pytest.fixture
def client():
    bridge = _make_client()
    try:
        yield bridge
    finally:
        bridge.close()


def _make_client():
    # Use httpx.AsyncClient with ASGITransport — compatible with httpx>=0.28 where
    # starlette's TestClient signature is incompatible. We wrap it in a tiny sync shim so
    # the tests stay synchronous and readable.
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async_client = httpx.AsyncClient(transport=transport, base_url="http://testserver")

    import asyncio

    class _SyncBridge:
        def __init__(self, inner: httpx.AsyncClient) -> None:
            self._inner = inner
            self._loop = asyncio.new_event_loop()
            self._lifespan = app.router.lifespan_context(app)
            self._loop.run_until_complete(self._lifespan.__aenter__())

        def _run(self, coro):
            return self._loop.run_until_complete(coro)

        def get(self, url, **kw):
            return self._run(self._inner.get(url, **kw))

        def post(self, url, **kw):
            return self._run(self._inner.post(url, **kw))

        def delete(self, url, **kw):
            return self._run(self._inner.delete(url, **kw))

        def close(self):
            try:
                self._loop.run_until_complete(self._lifespan.__aexit__(None, None, None))
            except Exception:
                pass
            self._loop.run_until_complete(self._inner.aclose())
            self._loop.close()

    return _SyncBridge(async_client)


def _headers(role: str = "engineer") -> dict[str, str]:
    return {"Authorization": f"Bearer {role}-dev-token"}


def test_ping_open(client):
    r = client.get("/api/ping")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_snapshot_requires_bearer(client):
    r = client.get("/api/snapshot")
    assert r.status_code == 401

    r = client.get("/api/snapshot", headers={"Authorization": "Bearer not-a-real-token"})
    assert r.status_code == 401


def test_snapshot_returns_for_viewer(client):
    r = client.get("/api/snapshot", headers=_headers("viewer"))
    assert r.status_code == 200
    payload = r.json()
    assert "root_cause" in payload and payload["root_cause"].startswith("RC_")
    assert "state" in payload
    assert "health_score" in payload


def test_prod_mode_requires_live_data_for_snapshot_and_topology(monkeypatch):
    monkeypatch.setenv("QOS_APP_MODE", "prod")
    monkeypatch.setenv("QOS_TOKENS_VIEWER", "viewer-dev-token")
    settings_mod.get_settings.cache_clear()

    from deployment import data as data_mod

    data_mod.load_qos.cache_clear()

    client = _make_client()
    try:
        snapshot = client.get("/api/snapshot", headers=_headers("viewer"))
        assert snapshot.status_code == 503
        assert "live telemetry is required in prod mode" in snapshot.json()["detail"]

        topology = client.get("/api/topology", headers=_headers("viewer"))
        assert topology.status_code == 503
        assert "live telemetry is required in prod mode" in topology.json()["detail"]
    finally:
        client.close()


def test_session_cookie_can_be_created_and_cleared(client):
    created = client.post("/api/session", headers=_headers("viewer"))
    assert created.status_code == 200
    assert created.json()["ok"] is True
    session_id = created.json()["session_id"]
    session = SessionsRepo.get_active(session_id)
    assert session is not None
    assert session["principal_role"] == "viewer"
    cookie_header = created.headers.get("set-cookie", "")
    assert f"qos_session={session_id}" in cookie_header
    assert "HttpOnly" in cookie_header

    cleared = client.delete("/api/session", cookies={"qos_session": session_id})
    assert cleared.status_code == 200
    assert cleared.json()["ok"] is True
    assert SessionsRepo.get_active(session_id) is None
    cleared_header = cleared.headers.get("set-cookie", "")
    assert "qos_session=" in cleared_header
    assert "Max-Age=0" in cleared_header or "expires=" in cleared_header.lower()


def test_stream_auth_prefers_session_cookie():
    from starlette.requests import Request

    session = SessionsRepo.create(principal_token="viewer-dev-token", principal_role="viewer")
    scope = {
        "type": "http",
        "headers": [(b"cookie", f"qos_session={session['id']}".encode("utf-8"))],
    }
    principal = _require_viewer_for_stream(Request(scope), token=None)
    assert principal.role == "viewer"
    assert principal.token == "viewer-dev-token"


def test_lead_can_list_and_revoke_sessions(client):
    created = client.post("/api/session", headers=_headers("viewer"))
    assert created.status_code == 200
    session_id = created.json()["session_id"]

    listing = client.get("/api/sessions", headers=_headers("lead"))
    assert listing.status_code == 200
    assert any(item["id"] == session_id for item in listing.json()["items"])

    revoked = client.delete(f"/api/sessions/{session_id}", headers=_headers("lead"))
    assert revoked.status_code == 200
    assert revoked.json()["session"]["revoked_by"] == "lead-dev-token"
    assert SessionsRepo.get_active(session_id) is None


def test_agent_decide_enforces_engineer(client):
    r = client.post("/api/agent/decide", json={}, headers=_headers("viewer"))
    assert r.status_code == 403


def test_agent_tools_lists_items(client):
    r = client.get("/api/agent/tools", headers=_headers("engineer"))
    assert r.status_code == 200
    body = r.json()
    assert "items" in body
    assert "tools" not in body
    assert any(item["name"] == "read_kpis" for item in body["items"])


def test_agent_decide_runs_and_publishes(client, monkeypatch):
    monkeypatch.setattr(
        "deployment.api.deps.get_reasoner",
        lambda: StubReasoner(),
    )
    monkeypatch.setattr(
        "deployment.api.routes.agent.get_reasoner",
        lambda: StubReasoner(),
    )
    r = client.post("/api/agent/decide", json={}, headers=_headers("engineer"))
    assert r.status_code == 200
    body = r.json()
    assert body["decision_id"]
    assert body["selected_action"].startswith("ACT_")
    # Decisions list should show it now.
    listing = client.get("/api/decisions?limit=5", headers=_headers("viewer"))
    assert listing.status_code == 200
    ids = [d["id"] for d in listing.json()["items"]]
    assert body["decision_id"] in ids


def test_approvals_role_escalation(client, monkeypatch):
    monkeypatch.setattr(
        "deployment.api.routes.agent.get_reasoner",
        lambda: StubReasoner(),
    )
    # Run decide() repeatedly to find a case that requires approval.
    target_approval_id = None
    for _ in range(6):
        r = client.post("/api/agent/decide", json={}, headers=_headers("engineer"))
        assert r.status_code == 200
        body = r.json()
        if body.get("approval_id"):
            target_approval_id = body["approval_id"]
            break
    if target_approval_id is None:
        pytest.skip("no PENDING_APPROVAL was produced under this fixture state")

    # Engineer cannot approve — only reject/defer.
    r = client.post(
        f"/api/approvals/{target_approval_id}/decide",
        json={"status": "APPROVED"},
        headers=_headers("engineer"),
    )
    assert r.status_code == 403
    assert "need 'lead'" in r.json()["detail"]

    r = client.post(
        f"/api/approvals/{target_approval_id}/decide",
        json={"status": "DEFERRED"},
        headers=_headers("engineer"),
    )
    assert r.status_code == 200
    assert r.json()["approval"]["status"] == "DEFERRED"


def test_approval_updates_decision_audit_state(client):
    decision_id = DecisionsRepo.insert(
        cell_id="CELL-A1",
        root_cause="RC_WEAK_SIGNAL",
        rc_confidence=0.81,
        selected_action="ACT_ALERT_COVERAGE_HOLE",
        selected_source="RuleLookup",
        hybrid_score=0.66,
        gate_decision="PENDING_APPROVAL",
        gate_reason="action contract requires NOC approval",
        risk_level="medium",
        impact_radius="sector",
        auto_executed=False,
        principal="engineer-dev-token",
        evidence=["rssi=-92"],
        candidates=[{"source": "RuleLookup", "action_code": "ACT_ALERT_COVERAGE_HOLE"}],
        validators=[{"name": "requires_human", "passed": False, "reason": "approval required"}],
        kpi_before={"latency_ms": 120.0},
        kpi_after={"latency_ms": 95.0},
        health_before=70.0,
        health_after=79.0,
        mlflow_run_id=None,
    )
    approval_id = ApprovalsRepo.insert(decision_id=decision_id, sla_deadline_iso="2026-04-25T00:00:00+00:00")

    r = client.post(
        f"/api/approvals/{approval_id}/decide",
        json={"status": "APPROVED", "reason": "lead approved"},
        headers=_headers("lead"),
    )
    assert r.status_code == 200

    decision = DecisionsRepo.get(decision_id)
    assert decision is not None
    assert decision.gate_decision == "APPROVED"
    assert decision.auto_executed is True
    assert decision.gate_reason == "lead approved"
    assert decision.kpi_after == {"latency_ms": 95.0}
    assert decision.health_after == 79.0


def test_approval_execute_runs_stage_action_without_ticket_for_automatic_action(client, monkeypatch):
    monkeypatch.setattr(
        "deployment.actions.latest_cell_row",
        lambda cell_id=None: pd.Series(
            {
                "cell_id": cell_id or "CELL-A2",
                "zone_id": "Z2",
                "node_id": "N2",
                "timestamp": pd.Timestamp("2026-04-25T11:00:00Z"),
                "throughput_mbps": 20.0,
                "latency_ms": 80.0,
                "sinr_db": 4.0,
                "bandwidth_util_pct": 90.0,
            }
        ),
    )
    decision_id = DecisionsRepo.insert(
        cell_id="CELL-A2",
        root_cause="RC_PRB_CONGESTION",
        rc_confidence=0.84,
        selected_action="ACT_LOADBALANCE_FREQ_BAND",
        selected_source="RuleLookup",
        hybrid_score=0.72,
        gate_decision="PENDING_APPROVAL",
        gate_reason="pending lead approval",
        risk_level="medium",
        impact_radius="sector",
        auto_executed=False,
        principal="engineer-dev-token",
        evidence=["utilization=92"],
        candidates=[{"source": "RuleLookup", "action_code": "ACT_LOADBALANCE_FREQ_BAND"}],
        validators=[{"name": "requires_human", "passed": False, "reason": "approval required"}],
        kpi_before={"latency_ms": 80.0, "throughput_mbps": 20.0, "sinr_db": 4.0},
        kpi_after={"latency_ms": 80.0, "throughput_mbps": 21.6, "sinr_db": 5.5},
        health_before=61.0,
        health_after=70.0,
        mlflow_run_id=None,
    )
    approval_id = ApprovalsRepo.insert(decision_id=decision_id, sla_deadline_iso="2026-04-25T00:00:00+00:00")

    r = client.post(
        f"/api/approvals/{approval_id}/decide",
        json={"status": "APPROVED", "reason": "lead approved"},
        headers=_headers("lead"),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["execution"]["mode"] == "staged"
    assert body["execution"]["ticket"] is None
    latest = MonitoringSnapshotsRepo.latest("CELL-A2")
    assert latest is not None
    assert latest["payload"]["throughput_mbps"] > 20.0


def test_approval_execute_opens_ticket_for_manual_action(client):
    decision_id = DecisionsRepo.insert(
        cell_id="CELL-A3",
        root_cause="RC_COVERAGE_HOLE",
        rc_confidence=0.88,
        selected_action="ACT_ALERT_COVERAGE_HOLE",
        selected_source="RuleLookup",
        hybrid_score=0.69,
        gate_decision="PENDING_APPROVAL",
        gate_reason="pending engineer approval",
        risk_level="medium",
        impact_radius="sector",
        auto_executed=False,
        principal="engineer-dev-token",
        evidence=["coverage drop"],
        candidates=[{"source": "RuleLookup", "action_code": "ACT_ALERT_COVERAGE_HOLE"}],
        validators=[{"name": "requires_human", "passed": False, "reason": "approval required"}],
        kpi_before={"latency_ms": 110.0, "throughput_mbps": 18.0},
        kpi_after={"latency_ms": 110.0, "throughput_mbps": 18.0},
        health_before=54.0,
        health_after=54.0,
        mlflow_run_id=None,
    )
    approval_id = ApprovalsRepo.insert(decision_id=decision_id, sla_deadline_iso="2026-04-25T00:00:00+00:00")

    r = client.post(
        f"/api/approvals/{approval_id}/decide",
        json={"status": "APPROVED", "reason": "engineer approved"},
        headers=_headers("engineer"),
    )
    assert r.status_code == 403
    assert "need 'lead'" in r.json()["detail"]

    r = client.post(
        f"/api/approvals/{approval_id}/decide",
        json={"status": "APPROVED", "reason": "lead approved"},
        headers=_headers("lead"),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["execution"]["ticket"] is not None
    assert body["execution"]["ticket"]["provider"] in {"local", "jira"}


def test_alerts_endpoint_lists_empty(client):
    r = client.get("/api/alerts", headers=_headers("viewer"))
    assert r.status_code == 200
    assert r.json()["items"] == []


def test_incidents_returns_503_for_tool_failure(client, monkeypatch):
    monkeypatch.setattr(
        "deployment.api.routes.network.run_tool",
        lambda name, inputs, ctx: {"error": "incident store unavailable"},
    )

    r = client.get("/api/incidents", headers=_headers("viewer"))

    assert r.status_code == 503
    assert r.json()["detail"] == "incident store unavailable"


def test_review_preview_returns_policy_and_reasoning(client, monkeypatch):
    monkeypatch.setattr(
        "deployment.api.deps.get_reasoner",
        lambda: StubReasoner(),
    )
    monkeypatch.setattr(
        "deployment.api.routes.review.get_reasoner",
        lambda: StubReasoner(),
    )
    monkeypatch.setattr(
        "deployment.api.routes.review.latest_cell_row",
        lambda cell_id=None: pd.Series(
            {
                "cell_id": cell_id or "CELL-R1",
                "zone_id": "Z1",
                "node_id": "N1",
                "latency_ms": 160.0,
                "jitter_ms": 52.0,
                "queue_length": 90.0,
                "throughput_mbps": 12.0,
            }
        ),
    )
    monkeypatch.setattr(
        "deployment.api.routes.review.latest_cell_snapshot",
        lambda cell_id=None: {"root_cause": "RC_TRANSPORT_DELAY"},
    )
    r = client.post(
        "/api/review/preview",
        json={"action_code": "ACT_NO_OP"},
        headers=_headers("engineer"),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["root_cause"] == "RC_TRANSPORT_DELAY"
    assert body["policy"]["decision"]
    assert body["llm"]["reasoning"]
    assert f"Policy outcome: {body['policy']['decision']}" in body["llm"]["reasoning"]
    assert body["forecast"]["before_health_score"] >= 0


def test_review_execute_stages_monitoring_snapshot(client, monkeypatch):
    monkeypatch.setattr(
        "deployment.api.routes.review.latest_cell_row",
        lambda cell_id=None: pd.Series(
            {
                "cell_id": cell_id or "CELL-R2",
                "zone_id": "Z1",
                "node_id": "N1",
                "timestamp": pd.Timestamp("2026-04-25T10:00:00Z"),
                "latency_ms": 160.0,
                "jitter_ms": 52.0,
                "packet_loss_pct": 2.0,
                "queue_length": 90.0,
                "throughput_mbps": 12.0,
            }
        ),
    )
    monkeypatch.setattr(
        "deployment.api.routes.review.latest_cell_snapshot",
        lambda cell_id=None: {
            "root_cause": "RC_TRANSPORT_DELAY",
            "confidence": 0.9,
            "evidence": ["queue pressure"],
        },
    )

    r = client.post(
        "/api/review/execute",
        json={"cell_id": "CELL-R2", "action_code": "ACT_REDUCE_BUFFER_SIZE"},
        headers=_headers("engineer"),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["policy"]["decision"] == "APPROVED"
    # The action stages a monitoring snapshot via the executable tool path; the
    # tool's mode reflects whether validation passed (`executed`) or whether the
    # change merely staged but did not pass guards (`staged`). Either is fine
    # here — what matters is the post-change snapshot exists.
    assert body["execution"]["mode"] in {"staged", "executed"}
    latest = MonitoringSnapshotsRepo.latest("CELL-R2")
    assert latest is not None
    assert latest["payload"]["latency_ms"] < 160.0


def test_review_preview_uses_pending_approval_snapshot(client, monkeypatch):
    monkeypatch.setattr(
        "deployment.api.deps.get_reasoner",
        lambda: StubReasoner(),
    )
    monkeypatch.setattr(
        "deployment.api.routes.review.get_reasoner",
        lambda: StubReasoner(),
    )
    decision_id = DecisionsRepo.insert(
        cell_id="CELL-PA1",
        root_cause="RC_SINR_DEGRADED",
        rc_confidence=0.87,
        selected_action="ACT_PRIORITY_VOLTE_SCHEDULING",
        selected_source="WeightedFusion",
        hybrid_score=0.61,
        gate_decision="PENDING_APPROVAL",
        gate_reason="approval required",
        risk_level="medium",
        impact_radius="local",
        auto_executed=False,
        principal="engineer-dev-token",
        evidence=["recorded evidence"],
        candidates=[{"source": "RuleLookup", "action_code": "ACT_PRIORITY_VOLTE_SCHEDULING"}],
        validators=[{"name": "requires_human", "passed": False, "reason": "approval required"}],
        kpi_before={
            "cell_id": "CELL-PA1",
            "zone_id": "Z9",
            "node_id": "N9",
            "timestamp": "2026-04-25T10:00:00+00:00",
            "latency_ms": 91.0,
            "jitter_ms": 16.0,
            "packet_loss_pct": 1.5,
            "throughput_mbps": 14.0,
            "sinr_db": 2.5,
            "bler_proxy_pct": 9.0,
        },
        kpi_after=None,
        health_before=58.0,
        health_after=None,
        mlflow_run_id=None,
    )
    approval_id = ApprovalsRepo.insert(decision_id=decision_id, sla_deadline_iso="2026-04-25T00:00:00+00:00")

    r = client.post(
        "/api/review/preview",
        json={"approval_id": approval_id, "action_code": "ACT_PRIORITY_VOLTE_SCHEDULING"},
        headers=_headers("engineer"),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["root_cause"] == "RC_SINR_DEGRADED"
    assert body["proposed_action"] == "ACT_PRIORITY_VOLTE_SCHEDULING"
    assert body["cell_id"] == "CELL-PA1"
    assert body["forecast"]["changed_kpis"]["packet_loss_pct"]["before"] == 1.5

    bad = client.post(
        "/api/review/preview",
        json={"approval_id": approval_id, "action_code": "ACT_LOADBALANCE_FREQ_BAND"},
        headers=_headers("engineer"),
    )
    assert bad.status_code == 400
    assert "must match the pending approval action" in bad.json()["detail"]


def test_review_preview_rejects_unknown_action_code(client):
    r = client.post(
        "/api/review/preview",
        json={"action_code": "ACT_NOT_REAL"},
        headers=_headers("engineer"),
    )
    assert r.status_code == 400
    assert "unknown action_code" in r.json()["detail"]


def test_review_preview_rejects_non_pending_approval(client):
    decision_id = DecisionsRepo.insert(
        cell_id="CELL-RX1",
        root_cause="RC_TRANSPORT_DELAY",
        rc_confidence=0.9,
        selected_action="ACT_REDUCE_BUFFER_SIZE",
        selected_source="review.execute",
        hybrid_score=1.0,
        gate_decision="APPROVED",
        gate_reason="already resolved",
        risk_level="low",
        impact_radius="local",
        auto_executed=True,
        principal="lead-dev-token",
        evidence=["queue high"],
        candidates=[{"source": "review.execute", "action_code": "ACT_REDUCE_BUFFER_SIZE"}],
        validators=[{"name": "risk_threshold", "passed": True, "reason": "approved"}],
        kpi_before={"cell_id": "CELL-RX1", "latency_ms": 120.0},
        kpi_after={"cell_id": "CELL-RX1", "latency_ms": 90.0},
        health_before=60.0,
        health_after=75.0,
        mlflow_run_id=None,
    )
    approval_id = ApprovalsRepo.insert(decision_id=decision_id, sla_deadline_iso="2026-04-25T00:00:00+00:00")
    ApprovalsRepo.decide(approval_id, "APPROVED", "lead-dev-token", "resolved")

    r = client.post(
        "/api/review/preview",
        json={"approval_id": approval_id, "action_code": "ACT_REDUCE_BUFFER_SIZE"},
        headers=_headers("engineer"),
    )
    assert r.status_code == 409
    assert "must reference a pending approval" in r.json()["detail"]


def test_ops_health_exposes_mlops_status(client):
    r = client.get("/api/ops/health", headers=_headers("viewer"))
    assert r.status_code == 200
    body = r.json()
    assert "mlops" in body
    assert body["mlops"]["experiment_name"] == "qos_phase3_deployment"


def test_create_app_does_not_eagerly_initialize_mlflow(monkeypatch):
    from deployment import mlops as mlops_mod

    called = {"count": 0}

    def fake_configure_mlflow(*, raise_on_error: bool = False):
        del raise_on_error
        called["count"] += 1
        return {"available": False}

    monkeypatch.setattr(mlops_mod, "configure_mlflow", fake_configure_mlflow)

    app = create_app()

    assert app is not None
    assert called["count"] == 0


def test_ops_health_initializes_mlflow_lazily(client, monkeypatch):
    from deployment import mlops as mlops_mod
    from deployment.api.routes import ops as ops_mod

    called = {"count": 0}

    def fake_mlops_status():
        called["count"] += 1
        return {
            "available": True,
            "tracking_uri": "sqlite:///tmp/mlflow.db",
            "registry_uri": None,
            "experiment_name": "qos_phase3_deployment",
            "experiment_id": "1",
            "artifact_location": "file:///tmp/mlartifacts",
            "backend": "sqlite",
            "warning": None,
            "error": None,
            "tracing_ready": True,
            "traces_present": False,
        }

    monkeypatch.setattr(mlops_mod, "mlops_status", fake_mlops_status)
    monkeypatch.setattr(ops_mod, "mlops_status", fake_mlops_status)

    r = client.get("/api/ops/health", headers=_headers("viewer"))

    assert r.status_code == 200
    assert called["count"] == 1


def test_app_cors_defaults_to_local_frontend_origins():
    settings_mod.get_settings.cache_clear()
    app = create_app()
    cors = next((mw for mw in app.user_middleware if mw.cls.__name__ == "CORSMiddleware"), None)
    assert cors is not None
    assert cors.kwargs["allow_origins"] == ["http://localhost:5173", "http://127.0.0.1:5173"]


def test_app_cors_can_be_overridden(monkeypatch):
    monkeypatch.setenv("QOS_CORS_ALLOW_ORIGINS", "https://ops.example,https://noc.example")
    settings_mod.get_settings.cache_clear()
    app = create_app()
    cors = next((mw for mw in app.user_middleware if mw.cls.__name__ == "CORSMiddleware"), None)
    assert cors is not None
    assert cors.kwargs["allow_origins"] == ["https://ops.example", "https://noc.example"]


def test_ops_mlops_lists_recent_runs(client, monkeypatch):
    monkeypatch.setattr(
        "deployment.api.deps.get_reasoner",
        lambda: StubReasoner(),
    )
    monkeypatch.setattr(
        "deployment.api.routes.agent.get_reasoner",
        lambda: StubReasoner(),
    )
    decision = client.post("/api/agent/decide", json={}, headers=_headers("engineer"))
    assert decision.status_code == 200

    r = client.get("/api/ops/mlops", headers=_headers("viewer"))
    assert r.status_code == 200
    body = r.json()
    assert body["status"]["available"] is True
    assert len(body["recent_runs"]) >= 1


def test_ops_health_reports_mlflow_outage_without_500(client, monkeypatch):
    from deployment import mlops as mlops_mod

    class BrokenClient:
        def get_experiment_by_name(self, _name):
            raise RuntimeError("mlflow backend down")

    monkeypatch.setattr(mlops_mod, "MlflowClient", BrokenClient)

    r = client.get("/api/ops/health", headers=_headers("viewer"))
    assert r.status_code == 200
    body = r.json()
    assert body["mlops"]["available"] is False
    assert "mlflow backend down" in body["mlops"]["error"]


def test_configure_mlflow_omits_local_artifact_root_for_remote_tracking(monkeypatch):
    monkeypatch.setenv("QOS_MLFLOW_TRACKING_URI", "https://mlflow.example")
    settings_mod.get_settings.cache_clear()

    from deployment import mlops as mlops_mod

    captured: dict[str, object] = {}

    class RemoteClient:
        def get_experiment_by_name(self, _name):
            return None

        def create_experiment(self, name, **kwargs):
            captured["name"] = name
            captured["kwargs"] = kwargs
            return "17"

        def get_experiment(self, _experiment_id):
            return type("Experiment", (), {"experiment_id": "17", "artifact_location": "mlflow-artifacts:/17"})()

    monkeypatch.setattr(mlops_mod, "MlflowClient", RemoteClient)
    monkeypatch.setattr(mlops_mod.mlflow, "set_tracking_uri", lambda _uri: None)
    monkeypatch.setattr(mlops_mod.mlflow, "set_registry_uri", lambda _uri: None)
    monkeypatch.setattr(mlops_mod.mlflow, "set_experiment", lambda _name: None)

    config = mlops_mod.configure_mlflow()

    assert config["available"] is True
    assert captured["kwargs"] == {}


def test_configure_mlflow_reuses_cached_result(monkeypatch):
    from deployment import mlops as mlops_mod

    calls = {"client": 0, "set_experiment": 0}

    class CachedClient:
        def __init__(self):
            calls["client"] += 1

        def get_experiment_by_name(self, _name):
            return type("Experiment", (), {"experiment_id": "17", "artifact_location": "file:///tmp/mlartifacts"})()

    monkeypatch.setattr(mlops_mod, "MlflowClient", CachedClient)
    monkeypatch.setattr(mlops_mod.mlflow, "set_tracking_uri", lambda _uri: None)
    monkeypatch.setattr(mlops_mod.mlflow, "set_registry_uri", lambda _uri: None)
    monkeypatch.setattr(mlops_mod.mlflow, "set_experiment", lambda _name: calls.__setitem__("set_experiment", calls["set_experiment"] + 1))
    mlops_mod.reset_mlflow_cache()

    first = mlops_mod.configure_mlflow()
    second = mlops_mod.configure_mlflow()

    assert first["available"] is True
    assert second["available"] is True
    assert calls["client"] == 1
    assert calls["set_experiment"] == 1


def test_drift_report_marks_missing_reference_baseline(monkeypatch):
    frame = pd.DataFrame(
        [
            {
                "timestamp": pd.Timestamp("2026-04-25T00:00:00Z"),
                "latency_ms": 120.0,
                "jitter_ms": 40.0,
                "packet_loss_pct": 2.5,
                "throughput_mbps": 18.0,
                "sinr_db": 4.0,
                "rssi_dbm": -95.0,
                "bandwidth_util_pct": 88.0,
                "queue_length": 90.0,
            }
        ]
        * 80
    )
    monkeypatch.setattr(drift_mod, "load_qos", lambda: frame)
    monkeypatch.setattr("deployment.llmops.drift.load_notebook_bundle", lambda: {})
    drift_mod._training_stats.cache_clear()

    report = drift_mod.drift_report(window=60)

    assert report["baseline_missing"] is True
    assert report["scored_columns"] == 0
    assert all(column["baseline_missing"] is True for column in report["columns"])
    assert all(column["z_score"] is None for column in report["columns"])


def test_ops_drift_uses_exported_train_stats_when_bundle_is_incompatible(client, monkeypatch):
    from deployment.llmops import drift as drift_mod

    frame = pd.DataFrame(
        [
            {
                "timestamp": pd.Timestamp("2026-04-25T00:00:00Z"),
                "latency_ms": 120.0,
                "jitter_ms": 40.0,
                "packet_loss_pct": 2.5,
                "throughput_mbps": 18.0,
                "sinr_db": 4.0,
                "rssi_dbm": -95.0,
                "bandwidth_util_pct": 88.0,
                "queue_length": 90.0,
            }
        ]
        * 80
    )
    monkeypatch.setattr(drift_mod, "load_qos", lambda: frame)
    monkeypatch.setattr(
        "deployment.llmops.drift.load_notebook_bundle",
        lambda: (_ for _ in ()).throw(ValueError("PCG64 is not a known BitGenerator module")),
    )
    drift_mod._training_stats.cache_clear()

    r = client.get("/api/ops/drift?window=60", headers=_headers("viewer"))

    assert r.status_code == 200
    body = r.json()
    assert body["baseline_missing"] is False
    assert body["baseline_unavailable"] is False
    assert body["scored_columns"] == 8


def test_ops_drift_route_catches_unexpected_errors(client, monkeypatch):
    monkeypatch.setattr("deployment.api.routes.ops.drift_report", lambda window=300: (_ for _ in ()).throw(RuntimeError("boom")))

    r = client.get("/api/ops/drift?window=60", headers=_headers("viewer"))

    assert r.status_code == 200
    body = r.json()
    assert body["baseline_unavailable"] is True
    assert body["error"] == "boom"


def test_ops_prompts_registered(client):
    r = client.get("/api/ops/prompts", headers=_headers("viewer"))
    assert r.status_code == 200
    names = {p["prompt_name"] for p in r.json()["items"]}
    assert {"agent.decision", "review.assessment", "llm.healthcheck"}.issubset(names)


def test_ops_preflight_exposes_readiness_checks(client):
    r = client.get("/api/ops/preflight", headers=_headers("viewer"))
    assert r.status_code == 200
    body = r.json()
    names = {check["name"] for check in body["checks"]}
    assert {"frontend_build", "store_path", "mlflow_path", "access_bootstrap", "telemetry_source", "mlflow_backend"} <= names


def test_integrations_test_drive_ingests_monitoring_and_diagnostic(client):
    r = client.post(
        "/api/integrations/test-drive",
        json={
            "monitoring": {
                "source_system": "near-live-driver",
                "zone_id": "Z9",
                "node_id": "N9",
                "cell_id": "CELL-TD1",
                "latency_ms": 155,
                "jitter_ms": 44,
                "packet_loss_pct": 2.3,
                "throughput_mbps": 16,
            },
            "diagnostic": {
                "source_system": "near-live-driver",
                "cell_id": "CELL-TD1",
                "root_cause": "RC_TRANSPORT_DELAY",
                "confidence": 0.91,
                "recommended_action": "ACT_REDUCE_BUFFER_SIZE",
                "evidence": ["queue high"],
            },
        },
        headers=_headers("engineer"),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["monitoring"]["ok"] is True
    assert body["diagnostic"]["ok"] is True


def test_decision_detail_includes_reasonings(client):
    decision_id = DecisionsRepo.insert(
        cell_id="CELL-AUD1",
        root_cause="RC_TRANSPORT_DELAY",
        rc_confidence=0.8,
        selected_action="ACT_REDUCE_BUFFER_SIZE",
        selected_source="WeightedFusion",
        hybrid_score=0.75,
        gate_decision="REJECTED",
        gate_reason="repeat action limit triggered",
        risk_level="low",
        impact_radius="local",
        auto_executed=False,
        principal="engineer-dev-token",
        evidence=["queue high"],
        candidates=[{"action_code": "ACT_REDUCE_BUFFER_SIZE", "source": "RuleLookup", "score": 0.8}],
        validators=[{"name": "repeat_guard", "passed": False, "reason": "cooldown"}],
        kpi_before={"latency_ms": 140.0},
        kpi_after={"latency_ms": 110.0},
        health_before=60.0,
        health_after=71.0,
        mlflow_run_id=None,
    )
    from deployment.store.repos import ReasoningsRepo

    ReasoningsRepo.insert(
        decision_id=decision_id,
        kind="agent",
        prompt_hash="hash-1",
        prompt_version="v1",
        model="stub-qwen",
        available=True,
        chosen_action="ACT_REDUCE_BUFFER_SIZE",
        confidence=0.7,
        reasoning_text="Policy outcome · REJECTED. repeat action limit triggered",
        raw={"chosen": "ACT_REDUCE_BUFFER_SIZE"},
        latency_ms=12.0,
        error=None,
    )

    r = client.get(f"/api/decisions/{decision_id}", headers=_headers("viewer"))
    assert r.status_code == 200
    body = r.json()
    assert body["decision"]["candidates"][0]["action_code"] == "ACT_REDUCE_BUFFER_SIZE"
    assert body["reasonings"][0]["reasoning_text"].startswith("Policy outcome")


# --- Tickets / Jira integration ----------------------------------------------


def _seed_local_ticket(decision_id: str | None = None) -> str:
    from deployment.integrations import open_change_ticket

    res = open_change_ticket(
        decision_id=decision_id,
        cell_id="CELL-T1",
        action_code="ACT_REDUCE_BUFFER_SIZE",
        summary="cut queue depth on CELL-T1",
        reasoning="queue length elevated",
        evidence=["queue=92"],
        kpis={"latency_ms": 120.0, "throughput_mbps": 60.0},
        risk_level="low",
        opened_by="engineer-dev-token",
    )
    return res["local_id"]


def test_tickets_provider_health_local_by_default(client, monkeypatch):
    # Ensure we're testing the local fallback, even if the dev shell has JIRA_* set.
    for var in ("JIRA_URL", "JIRA_EMAIL", "JIRA_TOKEN", "JIRA_PROJECT_KEY"):
        monkeypatch.delenv(var, raising=False)
    with _write_temp_dotenv(""):
        r = client.get("/api/tickets/provider-health", headers=_headers("viewer"))
        assert r.status_code == 200
        body = r.json()
        assert body["provider"] == "local"
        assert body["configured"] is False
        assert body["jira"]["can_create"] is False


def test_tickets_provider_health_reloads_dotenv_backed_jira_config(client, monkeypatch):
    for var in ("JIRA_URL", "JIRA_EMAIL", "JIRA_TOKEN", "JIRA_PROJECT_KEY"):
        monkeypatch.delenv(var, raising=False)
    with _write_temp_dotenv(
            "\n".join(
                [
                    "JIRA_URL=https://example.atlassian.net",
                    "JIRA_EMAIL=ops@example.com",
                    "JIRA_TOKEN=token-xyz",
                    "JIRA_PROJECT_KEY=NOC",
                ]
            )
            + "\n",
    ):
        r = client.get("/api/tickets/provider-health", headers=_headers("viewer"))

    assert r.status_code == 200
    body = r.json()
    assert body["provider"] == "jira"
    assert body["configured"] is True
    assert body["jira"]["project_key"] == "NOC"


def test_tickets_list_and_close_local(client, monkeypatch):
    for var in ("JIRA_URL", "JIRA_EMAIL", "JIRA_TOKEN", "JIRA_PROJECT_KEY"):
        monkeypatch.delenv(var, raising=False)
    from deployment.core import settings as settings_mod
    settings_mod.get_settings.cache_clear()

    with _write_temp_dotenv(""):
        ticket_id = _seed_local_ticket()

        listing = client.get("/api/tickets?limit=10", headers=_headers("viewer"))
        assert listing.status_code == 200
        items = listing.json()["items"]
        assert any(t["id"] == ticket_id for t in items)
        target = next(t for t in items if t["id"] == ticket_id)
        assert target["status"] == "OPEN"
        assert target["evidence"]["provider"] == "local"

        closed = client.post(f"/api/tickets/{ticket_id}/close", headers=_headers("engineer"))
        assert closed.status_code == 200
        body = closed.json()
        assert body["ticket"]["status"] == "CLOSED"
        assert body["transitioned"] is False  # no Jira link
        # Closing again is a no-op.
        again = client.post(f"/api/tickets/{ticket_id}/close", headers=_headers("engineer"))
        assert again.status_code == 200
        assert again.json()["reason"] == "already_closed"


def test_tickets_refresh_skips_when_no_jira_link(client, monkeypatch):
    for var in ("JIRA_URL", "JIRA_EMAIL", "JIRA_TOKEN", "JIRA_PROJECT_KEY"):
        monkeypatch.delenv(var, raising=False)
    with _write_temp_dotenv(""):
        ticket_id = _seed_local_ticket()
        r = client.post(f"/api/tickets/{ticket_id}/refresh", headers=_headers("engineer"))
        assert r.status_code == 409
        assert r.json()["detail"] == "Jira provider is not configured"


def test_tickets_close_role_escalation(client, monkeypatch):
    for var in ("JIRA_URL", "JIRA_EMAIL", "JIRA_TOKEN", "JIRA_PROJECT_KEY"):
        monkeypatch.delenv(var, raising=False)
    from deployment.core import settings as settings_mod
    settings_mod.get_settings.cache_clear()

    ticket_id = _seed_local_ticket()
    # Viewer cannot close.
    r = client.post(f"/api/tickets/{ticket_id}/close", headers=_headers("viewer"))
    assert r.status_code == 403


def test_tickets_close_calls_jira_when_configured(client, monkeypatch):
    monkeypatch.setenv("JIRA_URL", "https://example.atlassian.net")
    monkeypatch.setenv("JIRA_EMAIL", "ops@example.com")
    monkeypatch.setenv("JIRA_TOKEN", "token-xyz")
    monkeypatch.setenv("JIRA_PROJECT_KEY", "NOC")
    from deployment.core import settings as settings_mod
    settings_mod.get_settings.cache_clear()

    # Stub the Jira POST so create_issue succeeds without a real network call.
    from deployment.integrations import jira as jira_mod

    captured: dict = {}

    class _Resp:
        def __init__(self, payload: dict, status: int = 200) -> None:
            self._payload = payload
            self.status_code = status
            self.content = b"x"

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                raise RuntimeError(f"http {self.status_code}")

        def json(self) -> dict:
            return self._payload

    def fake_post(url, json=None, auth=None, headers=None, timeout=None):  # noqa: ARG001
        captured["last_post"] = {"url": url, "json": json}
        if url.endswith("/rest/api/3/issue"):
            return _Resp({"id": "10001", "key": "NOC-42"})
        if "/transitions" in url:
            state["transitioned"] = True
            return _Resp({}, status=204)
        raise AssertionError(f"unexpected POST: {url}")

    state = {"transitioned": False}

    def fake_get(url, params=None, auth=None, headers=None, timeout=None):  # noqa: ARG001
        captured["last_get"] = {"url": url, "params": params}
        if url.endswith("/transitions"):
            return _Resp(
                {
                    "transitions": [
                        {
                            "id": "31",
                            "name": "Done",
                            "to": {"name": "Done", "statusCategory": {"key": "done"}},
                        }
                    ]
                }
            )
        if "/rest/api/3/issue/" in url:
            if state["transitioned"]:
                return _Resp(
                    {
                        "fields": {
                            "summary": "synthetic",
                            "status": {"name": "Done", "statusCategory": {"key": "done", "name": "Done"}},
                            "resolution": {"name": "Done"},
                            "updated": "2026-04-25T00:00:00.000+0000",
                        }
                    }
                )
            return _Resp(
                {
                    "fields": {
                        "summary": "synthetic",
                        "status": {"name": "Open", "statusCategory": {"key": "new", "name": "To Do"}},
                        "resolution": None,
                        "updated": "2026-04-25T00:00:00.000+0000",
                    }
                }
            )
        raise AssertionError(f"unexpected GET: {url}")

    monkeypatch.setattr(jira_mod.requests, "post", fake_post)
    monkeypatch.setattr(jira_mod.requests, "get", fake_get)

    # Open a ticket — should land in Jira.
    from deployment.integrations import open_change_ticket
    res = open_change_ticket(
        decision_id=None,
        cell_id="CELL-J1",
        action_code="ACT_NO_OP",
        summary="probe ticket",
        reasoning="auto-test",
        evidence=["x=1"],
        kpis={"latency_ms": 30.0},
        risk_level="low",
        opened_by="engineer-dev-token",
    )
    assert res["provider"] == "jira"
    assert res["ticket_key"] == "NOC-42"
    assert res["ticket_url"].endswith("/browse/NOC-42")

    # Close — should call transition then close locally.
    closed = client.post(f"/api/tickets/{res['local_id']}/close", headers=_headers("engineer"))
    assert closed.status_code == 200
    body = closed.json()
    assert body["ticket"]["status"] == "CLOSED"
    assert body["transitioned"] is True
    assert body["transition"]["transition_name"].lower() == "done"
    # Verify a transition POST happened.
    assert "transitions" in captured["last_post"]["url"]


def test_tickets_probe_endpoint(client, monkeypatch):
    monkeypatch.setenv("JIRA_URL", "https://example.atlassian.net")
    monkeypatch.setenv("JIRA_EMAIL", "ops@example.com")
    monkeypatch.setenv("JIRA_TOKEN", "token-xyz")
    monkeypatch.setenv("JIRA_PROJECT_KEY", "NOC")
    from deployment.core import settings as settings_mod
    settings_mod.get_settings.cache_clear()

    from deployment.integrations import jira as jira_mod

    class _Resp:
        def __init__(self, payload, status=200):
            self._payload = payload
            self.status_code = status
            self.content = b"x"

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError("http")

        def json(self):
            return self._payload

    def fake_get(url, **_):
        if url.endswith("/rest/api/3/myself"):
            return _Resp({"accountId": "abc", "displayName": "QoS Bot"})
        if "/rest/api/3/issue/createmeta" in url:
            return _Resp(
                {
                    "projects": [
                        {
                            "key": "NOC",
                            "name": "Ops",
                            "issuetypes": [{"name": "Task"}],
                        }
                    ]
                }
            )
        raise AssertionError(url)

    monkeypatch.setattr(jira_mod.requests, "get", fake_get)

    r = client.post("/api/tickets/probe", headers=_headers("engineer"))
    assert r.status_code == 200
    body = r.json()
    assert body["provider"] == "jira"
    assert body["ok"] is True
    assert body["display_name"] == "QoS Bot"
    assert body["project_access"]["ok"] is True

    # Viewer cannot probe.
    r = client.post("/api/tickets/probe", headers=_headers("viewer"))
    assert r.status_code == 403


def test_tickets_probe_rejects_non_creatable_project(client, monkeypatch):
    monkeypatch.setenv("JIRA_URL", "https://example.atlassian.net")
    monkeypatch.setenv("JIRA_EMAIL", "ops@example.com")
    monkeypatch.setenv("JIRA_TOKEN", "token-xyz")
    monkeypatch.setenv("JIRA_PROJECT_KEY", "QOS")
    from deployment.core import settings as settings_mod
    settings_mod.get_settings.cache_clear()

    from deployment.api.routes import tickets as tickets_mod

    class ProbeClient:
        def __init__(self, *_args, **_kwargs):
            pass

        def is_configured(self) -> bool:
            return True

        def probe(self) -> dict:
            return {
                "ok": True,
                "account_id": "abc",
                "display_name": "QoS Bot",
                "project_access": {
                    "ok": False,
                    "project_key": "QOS",
                    "issue_type": "Task",
                    "reason": "project_not_creatable",
                },
            }

    monkeypatch.setattr(tickets_mod, "JiraClient", ProbeClient)

    r = client.post("/api/tickets/probe", headers=_headers("engineer"))

    assert r.status_code == 409
    assert "project QOS is not creatable" in r.json()["detail"]


def test_tickets_probe_requires_configured_jira(client, monkeypatch):
    for var in ("JIRA_URL", "JIRA_EMAIL", "JIRA_TOKEN", "JIRA_PROJECT_KEY"):
        monkeypatch.delenv(var, raising=False)
    with _write_temp_dotenv(""):
        r = client.post("/api/tickets/probe", headers=_headers("engineer"))
        assert r.status_code == 409
        assert r.json()["detail"] == "Jira provider is not configured"


def test_open_change_ticket_surfaces_jira_validation_detail(monkeypatch):
    monkeypatch.setenv("JIRA_URL", "https://example.atlassian.net")
    monkeypatch.setenv("JIRA_EMAIL", "ops@example.com")
    monkeypatch.setenv("JIRA_TOKEN", "token-xyz")
    monkeypatch.setenv("JIRA_PROJECT_KEY", "NOC")
    from deployment.core import settings as settings_mod
    settings_mod.get_settings.cache_clear()

    from deployment.integrations import open_change_ticket
    from deployment.integrations import jira as jira_mod

    class _Resp:
        def __init__(self, payload: dict, status: int) -> None:
            self._payload = payload
            self.status_code = status
            self.content = b"x"
            self.reason = "Bad Request"
            self.text = str(payload)

        def raise_for_status(self) -> None:
            raise jira_mod.requests.HTTPError(response=self)

        def json(self) -> dict:
            return self._payload

    def fake_post(url, json=None, auth=None, headers=None, timeout=None):  # noqa: ARG001
        assert url.endswith("/rest/api/3/issue")
        return _Resp({"errors": {"issuetype": "Issue type is invalid"}}, 400)

    monkeypatch.setattr(jira_mod.requests, "post", fake_post)

    result = open_change_ticket(
        decision_id=None,
        cell_id="CELL-J3",
        action_code="ACT_NO_OP",
        summary="jira validation failure",
        reasoning="synthetic",
        evidence=["x=1"],
        kpis={"latency_ms": 30.0},
        risk_level="low",
        opened_by="engineer-dev-token",
    )

    assert result["provider"] == "local"
    assert "issuetype: Issue type is invalid" in (result["upstream_error"] or "")


def test_tickets_refresh_returns_502_for_jira_upstream_error(client, monkeypatch):
    monkeypatch.setenv("JIRA_URL", "https://example.atlassian.net")
    monkeypatch.setenv("JIRA_EMAIL", "ops@example.com")
    monkeypatch.setenv("JIRA_TOKEN", "token-xyz")
    monkeypatch.setenv("JIRA_PROJECT_KEY", "NOC")
    from deployment.core import settings as settings_mod
    settings_mod.get_settings.cache_clear()

    from deployment.api.routes import tickets as tickets_mod
    from deployment.store.repos import ChangeTicketsRepo

    ticket_id = ChangeTicketsRepo.insert(
        decision_id=None,
        cell_id="CELL-J2",
        action_code="ACT_NO_OP",
        summary="probe refresh failure",
        evidence={
            "provider": "jira",
            "ticket_key": "NOC-777",
            "ticket_url": "https://example.atlassian.net/browse/NOC-777",
        },
        opened_by="engineer-dev-token",
    )

    class BrokenJiraClient:
        def __init__(self, *_args, **_kwargs):
            pass

        def is_configured(self) -> bool:
            return True

        def get_issue_status(self, issue_key: str) -> dict:
            raise RuntimeError(f"jira unavailable for {issue_key}")

    monkeypatch.setattr(tickets_mod, "JiraClient", BrokenJiraClient)

    r = client.post(f"/api/tickets/{ticket_id}/refresh", headers=_headers("engineer"))

    assert r.status_code == 502
    assert "jira unavailable" in r.json()["detail"]
