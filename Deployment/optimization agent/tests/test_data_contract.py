from __future__ import annotations

from deployment.contracts import ImpactRadius, PHASE3_ACTIONS, RiskLevel


def test_phase3_contract_contains_requested_gate_cases():
    assert PHASE3_ACTIONS["RC_TRANSPORT_DELAY"].action_code == "ACT_REDUCE_BUFFER_SIZE"
    assert PHASE3_ACTIONS["RC_TRANSPORT_DELAY"].risk_level == RiskLevel.LOW
    assert PHASE3_ACTIONS["RC_TRANSPORT_DELAY"].estimated_impact == ImpactRadius.LOCAL
    assert PHASE3_ACTIONS["RC_CQI_MISMATCH"].action_code == "ACT_PRIORITY_VOLTE_SCHEDULING"
    assert PHASE3_ACTIONS["RC_COVERAGE_HOLE"].action_code == "ACT_RECOMMEND_SITE_ADDITION"
    assert PHASE3_ACTIONS["RC_COVERAGE_HOLE"].is_reversible is False
    assert PHASE3_ACTIONS["RC_CAPACITY_OVERLOAD"].requires_human is True

