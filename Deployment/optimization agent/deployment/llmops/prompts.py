from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from ..store.repos import PromptRegistryRepo


@dataclass(frozen=True)
class PromptTemplate:
    name: str
    version: str
    template: str

    @property
    def hash(self) -> str:
        payload = f"{self.name}|{self.version}|{self.template}".encode("utf-8")
        return hashlib.sha256(payload).hexdigest()[:16]

    def render(self, **variables: Any) -> str:
        return self.template.format(**variables)


AGENT_DECISION = PromptTemplate(
    name="agent.decision",
    version="2026-04-24.v1",
    template=(
        "You are the QoS Buddy NOC reasoner for a cellular/Wi-Fi network.\n"
        "Return STRICT JSON with keys: chosen, confidence, reasoning, tool_plan.\n"
        "- chosen MUST be one of the shortlist action codes.\n"
        "- confidence is a float in [0, 1].\n"
        "- reasoning is <= 4 sentences, grounded in the evidence.\n"
        "- tool_plan is a list of tool calls you WOULD make next (may be empty).\n\n"
        "ROOT CAUSE: {root_cause} (confidence {rc_confidence:.2f})\n"
        "CAUSAL CHAIN: {causal_chain}\n"
        "KPIS: {kpis}\n"
        "EVIDENCE: {evidence}\n"
        "HYBRID CANDIDATES: {candidates}\n"
        "TRAINED HYBRID ACTION: {hybrid_action}\n"
        "SHORTLIST: {shortlist}\n"
        "RECENT DECISIONS FOR THIS CELL: {history}\n"
        "TOPOLOGY NEIGHBORS (health %): {neighbors}\n"
    ),
)


HEALTHCHECK = PromptTemplate(
    name="llm.healthcheck",
    version="2026-04-24.v1",
    template=(
        "Return STRICT JSON: status must be 'ok'. This is a QoS Buddy local Qwen health check.\n"
    ),
)


REVIEW_ASSESSMENT = PromptTemplate(
    name="review.assessment",
    version="2026-04-25.v1",
    template=(
        "You are the QoS Buddy change review assistant.\n"
        "Return STRICT JSON with keys: recommendation, confidence, reasoning, risks.\n"
        "- recommendation must be one of approve, reject, defer, test.\n"
        "- confidence is a float in [0,1].\n"
        "- reasoning is <= 5 sentences and must reference KPIs or policy.\n"
        "- risks is a short list of strings.\n\n"
        "CELL: {cell_id}\n"
        "ROOT CAUSE: {root_cause}\n"
        "PROPOSED ACTION: {action_code}\n"
        "POLICY DECISION: {policy_decision}\n"
        "POLICY REASON: {policy_reason}\n"
        "KPI SNAPSHOT: {kpis}\n"
        "EVIDENCE: {evidence}\n"
        "FORECAST BEFORE HEALTH: {before_health:.2f}\n"
        "FORECAST AFTER HEALTH: {after_health:.2f}\n"
        "CHANGED KPIS: {changed_kpis}\n"
    ),
)

REJECTION_MOTIVE = PromptTemplate(
    name="agent.rejection_motive",
    version="2026-04-27.v1",
    template=(
        "You are the QoS Buddy NOC rejection analyst.\n"
        "Return STRICT JSON with keys: motive, human_request, urgency, evidence_summary.\n"
        "- motive is one clear sentence explaining why policy rejected automatic execution.\n"
        "- human_request is one clear sentence asking Jira/NOC reviewers what to decide next.\n"
        "- urgency must be low, medium, high, or critical.\n"
        "- evidence_summary is <= 3 bullet-like strings.\n\n"
        "CELL: {cell_id}\n"
        "ROOT CAUSE: {root_cause}\n"
        "ACTION: {action_code}\n"
        "RISK: {risk_level}\n"
        "IMPACT: {impact_radius}\n"
        "POLICY REASON: {policy_reason}\n"
        "VALIDATORS: {validators}\n"
        "KPI SNAPSHOT: {kpis}\n"
        "EVIDENCE: {evidence}\n"
        "AGENT REASONING: {agent_reasoning}\n"
    ),
)


PROMPTS: dict[str, PromptTemplate] = {
    p.name: p for p in (AGENT_DECISION, REVIEW_ASSESSMENT, HEALTHCHECK, REJECTION_MOTIVE)
}


def register_all() -> None:
    for prompt in PROMPTS.values():
        PromptRegistryRepo.upsert(
            prompt_hash=prompt.hash,
            prompt_name=prompt.name,
            prompt_version=prompt.version,
            template=prompt.template,
        )
