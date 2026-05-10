from __future__ import annotations

import pytest

from deployment.agent import decide
from deployment.contracts import Decision
from deployment.llmops.client import LLMCall, LLMResponse
from deployment.store.db import reset_for_tests
from deployment.store.repos import (
    ApprovalsRepo,
    ChangeTicketsRepo,
    DecisionsRepo,
    ToolCallsRepo,
)


@pytest.fixture(autouse=True)
def clean_store():
    reset_for_tests()
    yield
    reset_for_tests()


class OfflineReasoner:
    """Stub that always reports the LLM as unavailable — exercises the fallback path."""

    def __init__(self) -> None:
        self.calls: list[LLMCall] = []

    def call(self, call: LLMCall) -> LLMResponse:
        self.calls.append(call)
        return LLMResponse(
            available=False,
            model="stub-qwen",
            content={},
            prompt_hash="x" * 16,
            prompt_version="0",
            cached=False,
            latency_ms=0.1,
            error="stub: ollama unavailable",
            reasoning_id=None,
        )


class ForcedChoiceReasoner:
    """Stub that returns a specific action from the shortlist, as if the local LLM ran."""

    def __init__(self, chosen: str, reasoning: str = "stub-selected") -> None:
        self.chosen = chosen
        self.reasoning = reasoning

    def call(self, call: LLMCall) -> LLMResponse:
        return LLMResponse(
            available=True,
            model="stub-qwen",
            content={"chosen": self.chosen, "reasoning": self.reasoning, "confidence": 0.77},
            prompt_hash="y" * 16,
            prompt_version="0",
            cached=False,
            latency_ms=1.23,
            reasoning_id="rsn_stub",
        )


def test_agent_loop_runs_without_llm_and_persists_decision():
    reasoner = OfflineReasoner()
    result = decide(cell_id=None, principal_role="engineer", reasoner=reasoner)

    # Fallback source must be the hybrid ensemble, not the LLM.
    assert result.llm_available is False
    assert result.selected_source != "M7 LocalQwen"
    assert result.selected_action.startswith("ACT_")
    assert result.decision_id.startswith("dec_") or len(result.decision_id) > 0

    # Decision row was persisted.
    row = DecisionsRepo.get(result.decision_id)
    assert row is not None
    assert row.selected_action == result.selected_action
    assert row.gate_decision in {d.value for d in Decision}
    assert row.mlflow_run_id

    # Tool calls were backfilled with the decision_id.
    tool_calls = ToolCallsRepo.for_decision(result.decision_id)
    names = {tc["tool_name"] for tc in tool_calls}
    assert {"read_kpis", "query_topology", "fetch_history", "fetch_incidents"}.issubset(names)


def test_agent_loop_respects_llm_choice_when_in_shortlist():
    # Run once with the offline reasoner to discover the shortlist for the current row.
    probe = decide(principal_role="engineer", reasoner=OfflineReasoner())
    shortlist = sorted({c["action_code"] for c in probe.candidates})
    assert shortlist, "hybrid optimizer produced no candidates"

    reset_for_tests()

    # Pick a shortlist action that differs from the hybrid's pick when possible.
    alt_action = next((a for a in shortlist if a != probe.selected_action), shortlist[0])

    result = decide(principal_role="engineer", reasoner=ForcedChoiceReasoner(alt_action))

    assert result.llm_available is True
    assert result.selected_action == alt_action
    assert result.selected_source == "WeightedFusion"
    assert "stub-selected" in result.llm_reasoning


def test_agent_loop_creates_approval_when_gate_pending():
    # Run the loop enough times to find a case where the gate returns PENDING_APPROVAL.
    found_pending = False
    for _ in range(5):
        result = decide(principal_role="engineer", reasoner=OfflineReasoner())
        if result.gate_decision == Decision.PENDING_APPROVAL.value:
            assert result.approval_id is not None
            approval = ApprovalsRepo.get(result.approval_id)
            assert approval is not None
            assert approval["decision_id"] == result.decision_id
            assert approval["status"] == "PENDING_APPROVAL"
            found_pending = True
            break
        reset_for_tests()
    # The dataset may deterministically approve or reject; skip rather than fail if so.
    if not found_pending:
        pytest.skip("no PENDING_APPROVAL path exercised under this fixture state")


def test_agent_loop_always_persists_tool_trace():
    result = decide(principal_role="engineer", reasoner=OfflineReasoner())
    tool_calls = ToolCallsRepo.for_decision(result.decision_id)
    # Each call should carry a duration and a sequence number.
    assert all("duration_ms" in tc for tc in tool_calls)
    seqs = [tc["seq"] for tc in tool_calls]
    assert seqs == sorted(seqs), "tool_calls.seq must be monotonically increasing"


def test_agent_loop_opens_ticket_for_rejected_decision():
    result = None
    for _ in range(8):
        probe = decide(principal_role="engineer", reasoner=OfflineReasoner())
        if probe.gate_decision == Decision.REJECTED.value:
            result = probe
            break
        reset_for_tests()
    if result is None:
        pytest.skip("no REJECTED path exercised under this fixture state")

    tickets = ChangeTicketsRepo.for_decision(result.decision_id)
    assert tickets
    evidence = tickets[0]["evidence"]
    assert evidence["provider"] in {"local", "jira"}
    assert "policy-rejected" in evidence["labels"]
