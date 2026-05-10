from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import numpy as np
import pandas as pd

from .contracts import ACTION_COST, ACTION_TOOLS, PHASE3_ACTIONS
from .data import infer_root_cause, load_qos

FEATURE_COLUMNS = [
    "latency_ms",
    "jitter_ms",
    "packet_loss_pct",
    "throughput_mbps",
    "bandwidth_util_pct",
    "queue_length",
    "rssi_dbm",
    "sinr_db",
    "cqi",
    "bler_proxy_pct",
    "ho_success_rate_pct",
    "active_connections",
]


@dataclass(frozen=True)
class Candidate:
    source: str
    action_code: str
    tool_name: str
    score: float
    rationale: str


def _num(row: pd.Series, col: str, default: float = 0.0) -> float:
    try:
        value = row.get(col, default)
        if pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default


def _features(row: pd.Series, means: pd.Series | None = None, stds: pd.Series | None = None) -> np.ndarray:
    raw = np.array([_num(row, col) for col in FEATURE_COLUMNS], dtype=float)
    if means is None or stds is None:
        return raw
    denom = stds.reindex(FEATURE_COLUMNS).replace(0, 1).fillna(1).to_numpy(dtype=float)
    center = means.reindex(FEATURE_COLUMNS).fillna(0).to_numpy(dtype=float)
    return (raw - center) / denom


def reward_proxy(root_cause: str, action_code: str, row: pd.Series | None = None) -> float:
    """Notebook-style intent reward proxy for deployment training and test simulation."""
    if root_cause == "RC_NONE":
        return 0.90 if action_code == "ACT_NO_OP" else 0.20
    target = PHASE3_ACTIONS[root_cause].action_code
    base = 0.78 if action_code == target else 0.30
    if action_code == "ACT_NO_OP":
        base = 0.15
    base -= ACTION_COST.get(action_code, 0.25) * 0.20
    if row is not None:
        confidence = infer_root_cause(row)[1]
        base += (confidence - 0.70) * 0.20
    return float(np.clip(base, 0.0, 1.0))


class EpsilonGreedyTable:
    def __init__(self, frame: pd.DataFrame):
        rows = []
        actions = sorted(ACTION_COST)
        for _, row in frame.iterrows():
            rc, _, _ = infer_root_cause(row)
            for action in actions:
                rows.append({"root_cause": rc, "action_code": action, "reward": reward_proxy(rc, action, row)})
        table = pd.DataFrame(rows)
        self.scores = (
            table.groupby(["root_cause", "action_code"], as_index=False)["reward"]
            .mean()
            .sort_values(["root_cause", "reward"], ascending=[True, False])
        )

    def select(self, root_cause: str) -> Candidate:
        subset = self.scores[self.scores["root_cause"] == root_cause]
        if subset.empty:
            action = PHASE3_ACTIONS.get(root_cause, PHASE3_ACTIONS["RC_NONE"]).action_code
            score = 0.0
        else:
            top = subset.iloc[0]
            action = str(top["action_code"])
            score = float(top["reward"])
        return Candidate("EpsilonGreedy", action, ACTION_TOOLS[action], score, "highest replay reward estimate for this root cause")


class ContextualLinearBandit:
    def __init__(self, frame: pd.DataFrame, lam: float = 1.0):
        numeric = frame[FEATURE_COLUMNS].apply(pd.to_numeric, errors="coerce")
        self.means = numeric.mean()
        self.stds = numeric.std().replace(0, 1).fillna(1)
        self.weights: dict[str, np.ndarray] = {}
        actions = sorted(ACTION_COST)
        x_rows = np.vstack([_features(row, self.means, self.stds) for _, row in frame.iterrows()])
        design = np.c_[x_rows, np.ones(len(x_rows))]
        reg = lam * np.eye(design.shape[1])
        for action in actions:
            y = []
            for _, row in frame.iterrows():
                rc, _, _ = infer_root_cause(row)
                y.append(reward_proxy(rc, action, row))
            target = np.asarray(y, dtype=float)
            self.weights[action] = np.linalg.solve(design.T @ design + reg, design.T @ target)

    def select(self, root_cause: str, row: pd.Series) -> Candidate:
        allowed = {PHASE3_ACTIONS[root_cause].action_code, "ACT_NO_OP"}
        if root_cause in {"RC_SINR_DEGRADED", "RC_CAPACITY_OVERLOAD"}:
            allowed.add("ACT_LOADBALANCE_FREQ_BAND")
        x = np.r_[_features(row, self.means, self.stds), 1.0]
        scored = [(action, float(self.weights[action] @ x)) for action in allowed]
        action, score = max(scored, key=lambda item: item[1])
        return Candidate("M6 ContextualBandit", action, ACTION_TOOLS[action], score, "linear contextual score over live KPI vector")


class RuleLookup:
    def select(self, root_cause: str) -> Candidate:
        spec = PHASE3_ACTIONS[root_cause]
        score = 0.90 if root_cause == "RC_NONE" else 0.75
        return Candidate("RuleLookup", spec.action_code, ACTION_TOOLS[spec.action_code], score, spec.reason)


@dataclass
class HybridDecision:
    root_cause: str
    confidence: float
    evidence: list[str]
    selected_action: str
    selected_tool: str
    selected_source: str
    hybrid_score: float
    candidates: list[Candidate]
    explanation: str


class HybridOptimizer:
    def __init__(self, frame: pd.DataFrame):
        self.rule = RuleLookup()
        self.eg = EpsilonGreedyTable(frame)
        self.linucb = ContextualLinearBandit(frame)

    def decide(self, row: pd.Series, llm_choice: str | None = None, llm_reasoning: str | None = None) -> HybridDecision:
        rc, confidence, evidence = infer_root_cause(row)
        candidates = [self.rule.select(rc), self.eg.select(rc), self.linucb.select(rc, row)]
        if llm_choice and llm_choice in {c.action_code for c in candidates}:
            candidates.append(
                Candidate("M7 LocalQwen", llm_choice, ACTION_TOOLS[llm_choice], 0.82, llm_reasoning or "local Qwen selected a valid candidate")
            )
        aggregate: dict[str, list[Candidate]] = {}
        for candidate in candidates:
            aggregate.setdefault(candidate.action_code, []).append(candidate)
        scored = []
        for action, group in aggregate.items():
            mean_score = float(np.mean([c.score for c in group]))
            agreement = len(group) / len(candidates)
            score = mean_score + 0.08 * agreement - ACTION_COST.get(action, 0.2) * 0.04
            scored.append((action, score, group))
        selected_action, hybrid_score, group = max(scored, key=lambda item: item[1])
        lead = max(group, key=lambda c: c.score)
        explanation = (
            f"Hybrid selected {selected_action} using {len(group)}/{len(candidates)} agreeing candidates. "
            f"Root cause {rc} confidence={confidence:.2f}. Evidence: {'; '.join(evidence)}."
        )
        return HybridDecision(
            root_cause=rc,
            confidence=confidence,
            evidence=evidence,
            selected_action=selected_action,
            selected_tool=ACTION_TOOLS[selected_action],
            selected_source=lead.source,
            hybrid_score=float(hybrid_score),
            candidates=candidates,
            explanation=explanation,
        )


@lru_cache(maxsize=1)
def get_optimizer() -> HybridOptimizer:
    return HybridOptimizer(load_qos())
