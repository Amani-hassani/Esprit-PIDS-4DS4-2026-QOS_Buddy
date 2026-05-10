from __future__ import annotations

from functools import lru_cache
from typing import Any

import numpy as np
import pandas as pd

from ..data import load_qos
from ..model_loader import load_notebook_bundle, load_table_or_contract


DRIFT_COLUMNS = (
    "latency_ms",
    "jitter_ms",
    "packet_loss_pct",
    "throughput_mbps",
    "sinr_db",
    "rssi_dbm",
    "bandwidth_util_pct",
    "queue_length",
)
ELEVATED_Z_THRESHOLD = 3.5
DRIFTED_Z_THRESHOLD = 5.0


@lru_cache(maxsize=1)
def _training_stats() -> dict[str, Any]:
    try:
        bundle = load_notebook_bundle()
        stats = bundle.get("train_stats")
    except Exception:
        try:
            stats = load_table_or_contract("train_stats")
        except Exception:
            return {}
    if stats is None:
        return {}
    if hasattr(stats, "to_dict"):
        return stats.to_dict()
    if isinstance(stats, dict):
        return stats
    return {}


def _mean_and_std(column: str, stats: dict[str, Any]) -> tuple[float, float] | None:
    # Training stats may be shaped as {'col': {'mean': ..., 'std': ...}} or columnwise.
    if isinstance(stats, dict) and column in stats and isinstance(stats[column], dict):
        return float(stats[column].get("mean", 0.0)), float(stats[column].get("std", 1.0) or 1.0)
    if isinstance(stats, dict) and column in stats and isinstance(stats[column], (tuple, list)) and len(stats[column]) >= 2:
        return float(stats[column][0]), float(stats[column][1] or 1.0)
    return None


def drift_report(window: int = 300) -> dict[str, Any]:
    df = load_qos().dropna(subset=["timestamp"]).tail(max(50, window)).copy()
    if df.empty:
        return {"columns": [], "overall_drift": 0.0}
    stats = _training_stats()
    baseline_error = bool(not stats)
    rows = []
    z_scores = []
    baseline_missing = False
    for column in DRIFT_COLUMNS:
        if column not in df.columns:
            continue
        live = pd.to_numeric(df[column], errors="coerce").dropna()
        if live.empty:
            continue
        live_mean = float(live.mean())
        live_std = float(live.std() or 1.0)
        reference = _mean_and_std(column, stats)
        if reference is None:
            baseline_missing = True
            rows.append(
                {
                    "column": column,
                    "live_mean": round(live_mean, 3),
                    "live_std": round(live_std, 3),
                    "reference_mean": None,
                    "reference_std": None,
                    "z_score": None,
                "drifted": False,
                "elevated": False,
                "baseline_missing": True,
                }
            )
            continue
        ref_mean, ref_std = reference
        denom = max(ref_std, 1e-6)
        z = abs(live_mean - ref_mean) / denom
        z_scores.append(z)
        rows.append(
            {
                "column": column,
                "live_mean": round(live_mean, 3),
                "live_std": round(live_std, 3),
                "reference_mean": round(ref_mean, 3),
                "reference_std": round(ref_std, 3),
                "z_score": round(z, 3),
                "drifted": z >= DRIFTED_Z_THRESHOLD,
                "elevated": ELEVATED_Z_THRESHOLD <= z < DRIFTED_Z_THRESHOLD,
                "baseline_missing": False,
            }
        )
    return {
        "columns": rows,
        "overall_drift": round(float(np.mean(z_scores)) if z_scores else 0.0, 3),
        "window_rows": int(len(df)),
        "baseline_missing": baseline_missing,
        "baseline_unavailable": baseline_error,
        "scored_columns": len(z_scores),
    }
