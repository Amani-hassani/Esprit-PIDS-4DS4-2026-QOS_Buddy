from __future__ import annotations

from datetime import datetime, timezone

from deployment.contracts import ActionHistoryEntry, Decision, ImpactRadius, PolicyRequest, RiskLevel
from deployment.policy_gate import evaluate_policy


def _request(**overrides) -> PolicyRequest:
    base = dict(
        root_cause="RC_TRANSPORT_DELAY",
        action_code="ACT_REDUCE_BUFFER_SIZE",
        risk_level=RiskLevel.LOW,
        is_reversible=True,
        estimated_impact=ImpactRadius.LOCAL,
        current_time=datetime(2026, 4, 22, 12, 0, tzinfo=timezone.utc),
        cell_id="C1",
    )
    base.update(overrides)
    return PolicyRequest(**base)


def test_low_reversible_local_action_is_approved():
    decision = evaluate_policy(_request())
    assert decision.decision == Decision.APPROVED
    assert all(v.passed for v in decision.validators)


def test_medium_risk_goes_pending_approval():
    decision = evaluate_policy(_request(risk_level=RiskLevel.MEDIUM))
    assert decision.decision == Decision.PENDING_APPROVAL
    assert "NOC approval" in decision.reason


def test_site_impact_is_rejected():
    decision = evaluate_policy(_request(estimated_impact=ImpactRadius.SITE))
    assert decision.decision == Decision.REJECTED
    assert "exceeds" in decision.reason


def test_irreversible_action_is_rejected():
    decision = evaluate_policy(_request(is_reversible=False, rollback_available=False))
    assert decision.decision == Decision.REJECTED
    assert "irreversible" in decision.reason


def test_maintenance_window_is_deferred():
    decision = evaluate_policy(_request(current_time=datetime(2026, 4, 25, 3, 0, tzinfo=timezone.utc)))
    assert decision.decision == Decision.DEFERRED
    assert "maintenance window" in decision.reason


def test_repeat_action_is_rejected():
    history = [
        ActionHistoryEntry(
            cell_id="C1",
            action_code="ACT_REDUCE_BUFFER_SIZE",
            timestamp=datetime(2026, 4, 22, 11, 45, tzinfo=timezone.utc),
            decision=Decision.APPROVED,
        )
    ]
    decision = evaluate_policy(_request(action_history=history))
    assert decision.decision == Decision.REJECTED
    assert "already applied" in decision.reason


def test_requires_human_queues_without_approval():
    decision = evaluate_policy(_request(requires_human=True))
    assert decision.decision == Decision.PENDING_APPROVAL
    assert "requires NOC approval" in decision.reason


def test_human_approval_can_clear_human_and_risk_pending_check():
    decision = evaluate_policy(_request(requires_human=True, risk_level=RiskLevel.MEDIUM, human_approved=True))
    assert decision.decision == Decision.APPROVED

