from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


ACTION_EFFECTS = {
    "ACT_NO_OP": {},
    "ACT_ALERT_COVERAGE_HOLE": {"anomaly_score": ("mul", 0.98, 0, 1)},
    "ACT_LOADBALANCE_FREQ_BAND": {
        "bandwidth_util_pct": ("mul", 0.82, 0, 100),
        "throughput_mbps": ("mul", 1.08, 0, None),
        "sinr_db": ("add", 1.5, -30, 40),
    },
    "ACT_OPTIMIZE_HO_PARAMS": {
        "ho_success_rate_pct": ("add", 7, 0, 100),
        "jitter_ms": ("mul", 0.92, 0, None),
    },
    "ACT_TRIGGER_CA": {
        "throughput_mbps": ("mul", 1.18, 0, None),
        "bandwidth_util_pct": ("mul", 0.88, 0, 100),
    },
    "ACT_REDUCE_BUFFER_SIZE": {
        "latency_ms": ("mul", 0.80, 0, None),
        "jitter_ms": ("mul", 0.82, 0, None),
        "queue_length": ("mul", 0.62, 0, None),
        "packet_loss_pct": ("mul", 0.90, 0, 100),
    },
    "ACT_PRIORITY_VOLTE_SCHEDULING": {
        "packet_loss_pct": ("mul", 0.86, 0, 100),
        "jitter_ms": ("mul", 0.88, 0, None),
        "bler_proxy_pct": ("mul", 0.90, 0, 100),
    },
    "ACT_RECOMMEND_SITE_ADDITION": {
        "rssi_dbm": ("add", 8, -140, -30),
        "sinr_db": ("add", 4, -30, 40),
        "throughput_mbps": ("mul", 1.20, 0, None),
    },
}


def _bounded(value: Any, op: str, amount: float, lo: float | None, hi: float | None) -> float:
    try:
        out = float(value)
    except Exception:
        out = 0.0
    if op == "mul":
        out *= amount
    elif op == "add":
        out += amount
    if lo is not None or hi is not None:
        out = float(np.clip(out, -np.inf if lo is None else lo, np.inf if hi is None else hi))
    return out


def health_score(row: pd.Series | dict[str, Any]) -> float:
    def n(key: str, default: float = 0.0) -> float:
        try:
            value = row.get(key, default)
            if pd.isna(value):
                return default
            return float(value)
        except Exception:
            return default

    latency_penalty = min(n("latency_ms") / 250.0, 1.0) * 25
    jitter_penalty = min(n("jitter_ms") / 80.0, 1.0) * 15
    loss_penalty = min(n("packet_loss_pct") / 5.0, 1.0) * 20
    queue_penalty = min(n("queue_length") / 120.0, 1.0) * 15
    sinr_bonus = np.clip((n("sinr_db", 10) + 5) / 25.0, 0, 1) * 15
    throughput_bonus = min(n("throughput_mbps") / 50.0, 1.0) * 10
    score = 100 - latency_penalty - jitter_penalty - loss_penalty - queue_penalty + sinr_bonus + throughput_bonus
    return float(np.clip(score, 0, 100))


def simulate_action(row: pd.Series, action_code: str) -> dict[str, Any]:
    before = row.to_dict()
    after = dict(before)
    changed = {}
    for key, (op, amount, lo, hi) in ACTION_EFFECTS.get(action_code, {}).items():
        after[key] = _bounded(before.get(key), op, amount, lo, hi)
        changed[key] = {"before": before.get(key), "after": after[key]}
    before_score = health_score(before)
    after_score = health_score(after)
    return {
        "action_code": action_code,
        "before_health_score": before_score,
        "after_health_score": after_score,
        "delta_health_score": after_score - before_score,
        "changed_kpis": changed,
        "simulator": "deterministic action forecast",
    }
