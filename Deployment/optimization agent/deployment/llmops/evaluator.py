from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from ..model_loader import load_notebook_bundle


@dataclass
class EvalMetric:
    policy: str
    episodes: int
    oracle_hits: int
    mean_reward: float
    mean_regret: float
    oracle_hit_rate: float


@lru_cache(maxsize=1)
def _scorecard() -> list[dict[str, Any]]:
    bundle = load_notebook_bundle()
    table = bundle.get("final_score_table")
    if table is None:
        return []
    try:
        return table.to_dict(orient="records")
    except Exception:
        return []


@lru_cache(maxsize=1)
def _hybrid_decisions() -> list[dict[str, Any]]:
    bundle = load_notebook_bundle()
    df = bundle.get("hybrid_decisions")
    if df is None:
        return []
    try:
        return df.to_dict(orient="records")
    except Exception:
        return []


def evaluate_against_oracle() -> dict[str, Any]:
    rows = _scorecard()
    hybrid_rows = _hybrid_decisions()
    metrics = []
    for row in rows:
        episodes = int(row.get("episodes", 0) or 0)
        hits = int(row.get("oracle_hits", 0) or 0)
        metrics.append(
            EvalMetric(
                policy=str(row.get("policy", "unknown")),
                episodes=episodes,
                oracle_hits=hits,
                mean_reward=float(row.get("mean_intent_reward", 0.0) or 0.0),
                mean_regret=float(row.get("mean_regret", 0.0) or 0.0),
                oracle_hit_rate=float(hits) / float(episodes) if episodes else 0.0,
            )
        )
    hybrid_rewards = [float(r.get("reward", 0.0) or 0.0) for r in hybrid_rows]
    hybrid_regrets = [float(r.get("regret", 0.0) or 0.0) for r in hybrid_rows]
    summary = {
        "policy_count": len(metrics),
        "episodes": max((m.episodes for m in metrics), default=0),
        "best_mean_reward": max((m.mean_reward for m in metrics), default=0.0),
        "best_mean_regret": min((m.mean_regret for m in metrics), default=0.0),
        "hybrid_steps_exported": len(hybrid_rewards),
        "hybrid_mean_reward": (sum(hybrid_rewards) / len(hybrid_rewards)) if hybrid_rewards else 0.0,
        "hybrid_mean_regret": (sum(hybrid_regrets) / len(hybrid_regrets)) if hybrid_regrets else 0.0,
    }
    return {
        "metrics": [
            {
                "policy": m.policy,
                "episodes": m.episodes,
                "oracle_hits": m.oracle_hits,
                "mean_reward": m.mean_reward,
                "mean_regret": m.mean_regret,
                "oracle_hit_rate": m.oracle_hit_rate,
            }
            for m in metrics
        ],
        "summary": summary,
    }
