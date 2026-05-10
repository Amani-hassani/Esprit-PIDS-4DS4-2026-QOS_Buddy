from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from deployment.api.events import EventBus
from deployment.api.watchers import sla_watcher_loop
from deployment.core.clock import utc_now
from deployment.store.db import cursor, reset_for_tests
from deployment.store.repos import AlertsRepo, ApprovalsRepo, DecisionsRepo


@pytest.fixture(autouse=True)
def clean_store():
    reset_for_tests()
    yield
    reset_for_tests()


def _seed_overdue_approval() -> tuple[str, str]:
    decision_id = DecisionsRepo.insert(
        cell_id="C1",
        root_cause="RC_TRANSPORT_DELAY",
        rc_confidence=0.8,
        selected_action="ACT_REDUCE_BUFFER_SIZE",
        selected_source="test",
        hybrid_score=0.9,
        gate_decision="PENDING_APPROVAL",
        gate_reason="requires review",
        risk_level="high",
        impact_radius="cell",
        auto_executed=False,
        principal="engineer-dev-token",
        evidence=[],
        candidates=[],
        validators=[],
        kpi_before={"latency_ms": 140},
        kpi_after=None,
        health_before=60.0,
        health_after=None,
        mlflow_run_id=None,
    )
    past = (utc_now() - timedelta(minutes=10)).isoformat()
    approval_id = ApprovalsRepo.insert(decision_id=decision_id, sla_deadline_iso=past)
    # The watcher selects approvals whose `created_at` is older than the
    # `pending_alert_s` threshold (default 5 min). Backdate so the freshly
    # inserted row qualifies.
    with cursor() as cur:
        cur.execute(
            "UPDATE approvals SET created_at = ? WHERE id = ?",
            (past, approval_id),
        )
    return decision_id, approval_id


@pytest.mark.asyncio
async def test_sla_watcher_inserts_alert_once_per_approval():
    _, approval_id = _seed_overdue_approval()
    bus = EventBus()

    task = asyncio.create_task(sla_watcher_loop(bus, interval_s=0.05))
    try:
        await asyncio.sleep(0.3)  # allow a few ticks
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    alerts = AlertsRepo.list_recent(limit=5)
    assert len(alerts) == 1, "watcher should insert exactly one alert per overdue approval"
    alert = alerts[0]
    assert alert["approval_id"] == approval_id
    assert alert["kind"] == "pending_untouched"
    assert alert["severity"] in {"warning", "critical"}


@pytest.mark.asyncio
async def test_sla_watcher_publishes_to_bus():
    _seed_overdue_approval()
    bus = EventBus()

    queue = await bus.subscribe("alerts")
    task = asyncio.create_task(sla_watcher_loop(bus, interval_s=0.05))
    try:
        event = await asyncio.wait_for(queue.get(), timeout=1.0)
        assert event.channel == "alerts"
        assert event.payload["kind"] == "pending_untouched"
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        await bus.unsubscribe("alerts", queue)
