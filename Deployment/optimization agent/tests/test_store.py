from __future__ import annotations

import pytest

from deployment.core.clock import utc_now_iso
from deployment.store import repos
from deployment.store.db import reset_for_tests


@pytest.fixture(autouse=True)
def clean_store():
    reset_for_tests()
    yield
    reset_for_tests()


def _insert_decision(**overrides):
    base = dict(
        cell_id="C1",
        root_cause="RC_TRANSPORT_DELAY",
        rc_confidence=0.88,
        selected_action="ACT_REDUCE_BUFFER_SIZE",
        selected_source="RuleLookup",
        hybrid_score=0.82,
        gate_decision="APPROVED",
        gate_reason="auto-approved",
        risk_level="low",
        impact_radius="local",
        auto_executed=True,
        principal="engineer-dev-token",
        evidence=["queue=90"],
        candidates=[{"source": "RuleLookup", "action_code": "ACT_REDUCE_BUFFER_SIZE"}],
        validators=[{"name": "risk_threshold", "passed": True, "reason": "low"}],
        kpi_before={"latency_ms": 120.0},
        kpi_after={"latency_ms": 98.0},
        health_before=72.0,
        health_after=81.4,
        mlflow_run_id="run-xyz",
    )
    base.update(overrides)
    return repos.DecisionsRepo.insert(**base)


def test_decisions_roundtrip():
    decision_id = _insert_decision()
    stored = repos.DecisionsRepo.get(decision_id)
    assert stored is not None
    assert stored.cell_id == "C1"
    assert stored.gate_decision == "APPROVED"
    assert stored.kpi_before == {"latency_ms": 120.0}


def test_decisions_filter_by_gate():
    _insert_decision(gate_decision="APPROVED")
    _insert_decision(gate_decision="PENDING_APPROVAL")
    pending = repos.DecisionsRepo.list_recent(gate="PENDING_APPROVAL")
    assert len(pending) == 1
    assert pending[0].gate_decision == "PENDING_APPROVAL"


def test_approvals_lifecycle():
    decision_id = _insert_decision(gate_decision="PENDING_APPROVAL", auto_executed=False)
    approval_id = repos.ApprovalsRepo.insert(decision_id=decision_id, sla_deadline_iso=utc_now_iso())
    assert len(repos.ApprovalsRepo.pending()) == 1
    decided = repos.ApprovalsRepo.decide(approval_id, "APPROVED", actor="lead-dev-token", reason="ok")
    assert decided is not None and decided["status"] == "APPROVED"
    # second decision is a no-op
    again = repos.ApprovalsRepo.decide(approval_id, "REJECTED", actor="lead-dev-token")
    assert again["status"] == "APPROVED"


def test_alerts_not_duplicated_per_approval():
    decision_id = _insert_decision()
    approval_id = repos.ApprovalsRepo.insert(decision_id=decision_id, sla_deadline_iso=utc_now_iso())
    repos.AlertsRepo.insert(severity="warning", kind="sla_breach", subject="late", body="overdue", approval_id=approval_id)
    assert repos.AlertsRepo.exists_for_approval(approval_id, "sla_breach")
    assert not repos.AlertsRepo.exists_for_approval(approval_id, "drift")


def test_reasonings_are_queryable():
    decision_id = _insert_decision()
    rsn_id = repos.ReasoningsRepo.insert(
        decision_id=decision_id,
        kind="agent",
        prompt_hash="abc",
        prompt_version="v1",
        model="qwen2.5:3b",
        available=True,
        chosen_action="ACT_REDUCE_BUFFER_SIZE",
        confidence=0.91,
        reasoning_text="queue high, cut buffer",
        raw={"chosen": "ACT_REDUCE_BUFFER_SIZE"},
        latency_ms=140.0,
        error=None,
    )
    hit = repos.ReasoningsRepo.get(rsn_id)
    assert hit is not None and hit["chosen_action"] == "ACT_REDUCE_BUFFER_SIZE"
    assert hit["available"] is True


def test_reasonings_after_id_paginates_without_repeating_rows():
    decision_id = _insert_decision()
    for idx in range(3):
        repos.ReasoningsRepo.insert(
            decision_id=decision_id,
            kind="agent",
            prompt_hash=f"p{idx}",
            prompt_version="v1",
            model="qwen2.5:3b",
            available=True,
            chosen_action="ACT_REDUCE_BUFFER_SIZE",
            confidence=0.9,
            reasoning_text=f"reasoning-{idx}",
            raw={"idx": idx},
            latency_ms=100.0 + idx,
            error=None,
        )

    first_page = repos.ReasoningsRepo.list_recent(limit=2)
    assert len(first_page) == 2

    seen = {row["id"] for row in first_page}
    second_page = repos.ReasoningsRepo.list_recent(limit=2, after_id=first_page[-1]["id"])
    assert all(row["id"] not in seen for row in second_page)


def test_llm_cache_stats_roundtrip():
    repos.LLMCacheRepo.put(key="k1", prompt_hash="p1", model="qwen2.5:3b", response={"chosen": "ACT_NO_OP"})
    hit = repos.LLMCacheRepo.get("k1")
    assert hit is not None and hit["response"] == {"chosen": "ACT_NO_OP"}
    stats = repos.LLMCacheRepo.stats()
    assert stats["entries"] == 1
    assert stats["total_hits"] >= 1
