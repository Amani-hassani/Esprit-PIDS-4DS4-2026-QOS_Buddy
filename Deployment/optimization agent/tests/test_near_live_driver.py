from __future__ import annotations

from scripts.near_live_driver import SCENARIO_ORDER, SCENARIOS, _build_payload, _decision_summary, _scenario_sequence


def test_near_live_driver_scenarios_cover_healthy_and_failure_modes():
    expected = {
        "healthy_baseline",
        "transport_delay",
        "sinr_degraded",
        "handover_failure",
        "congestion_burst",
        "capacity_overload",
        "cqi_mismatch",
        "weak_signal",
        "coverage_hole",
    }
    assert expected.issubset(SCENARIOS.keys())


def test_near_live_driver_build_payload_stamps_source_and_cell():
    payload = _build_payload(
        scenario_name="congestion_burst",
        zone_id="ZONE-7",
        node_id="NODE-7",
        cell_id="CELL-77",
        request_index=3,
    )
    assert payload["monitoring"]["source_system"] == "near-live-driver"
    assert payload["diagnostic"]["source_system"] == "near-live-driver"
    assert payload["monitoring"]["cell_id"] == "CELL-77"
    assert payload["diagnostic"]["cell_id"] == "CELL-77"
    assert payload["diagnostic"]["root_cause"] == "RC_PRB_CONGESTION"
    assert payload["diagnostic"]["recommended_action"] == "ACT_TRIGGER_CA"


def test_near_live_driver_all_sequence_expands_every_scenario():
    all_names = _scenario_sequence("all", len(SCENARIOS) + 2)
    assert all_names[: len(SCENARIOS)] == list(SCENARIOS.keys())
    assert all_names[-2:] == list(SCENARIOS.keys())[:2]
    assert _scenario_sequence("transport_delay", 3) == ["transport_delay", "transport_delay", "transport_delay"]


def test_near_live_driver_mixed_sequence_rotates_policy_gate_scenarios():
    mixed = _scenario_sequence("mixed", len(SCENARIO_ORDER) + 2)
    assert mixed[: len(SCENARIO_ORDER)] == SCENARIO_ORDER
    assert mixed[-2:] == SCENARIO_ORDER[:2]


def test_near_live_driver_decision_summary_reports_policy_output():
    summary = _decision_summary(
        {
            "decision": {
                "selected_action": "ACT_REDUCE_BUFFER_SIZE",
                "gate_decision": "APPROVED",
                "risk_level": "low",
                "auto_executed": True,
                "approval_id": None,
            }
        }
    )
    assert "decision=ACT_REDUCE_BUFFER_SIZE" in summary
    assert "gate=APPROVED" in summary
    assert "risk=low" in summary
    assert "mode=auto" in summary
