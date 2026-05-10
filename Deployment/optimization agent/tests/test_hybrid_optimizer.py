from __future__ import annotations

from deployment.data import latest_cell_row
from deployment.hybrid_optimizer import ACTION_TOOLS, get_optimizer
from deployment.simulation import simulate_action


def test_hybrid_optimizer_returns_candidates_and_tool():
    row = latest_cell_row("C1")
    decision = get_optimizer().decide(row)
    assert decision.selected_action in ACTION_TOOLS
    assert decision.selected_tool == ACTION_TOOLS[decision.selected_action]
    assert {c.source for c in decision.candidates} >= {"RuleLookup", "EpsilonGreedy", "M6 ContextualBandit"}
    assert decision.explanation


def test_simulation_returns_health_delta_for_selected_action():
    row = latest_cell_row("C1")
    decision = get_optimizer().decide(row)
    result = simulate_action(row, decision.selected_action)
    assert result["action_code"] == decision.selected_action
    assert 0 <= result["before_health_score"] <= 100
    assert 0 <= result["after_health_score"] <= 100
    assert "changed_kpis" in result

