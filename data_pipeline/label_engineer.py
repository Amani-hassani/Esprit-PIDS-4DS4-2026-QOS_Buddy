"""Future-window label engineering (per ``node_id``, no shuffle)."""

from __future__ import annotations

import logging
import numpy as np
import pandas as pd

from config import (
    ANOMALY_SCORE_THRESHOLD,
    CONGESTION_INDEX_THRESHOLD,
    FUTURE_WINDOW_STEPS,
    LABEL_HORIZON_STEPS,
    LABEL_AGGREGATION_STRATEGY,
    SECONDS_PER_STEP,
    JITTER_THRESHOLD_MS,
    LATENCY_THRESHOLD_MS,
    MOS_THRESHOLD,
    TARGET_NAMES,
    THROUGHPUT_THRESHOLD_MBPS,
)

logger = logging.getLogger(__name__)


ETA_TARGETS = (
    "call_drop_risk",
    "latency_breach_risk",
    "throughput_risk",
    "jitter_risk",
    "mos_risk",
)


TTE_COLUMN_MAP = {
    "call_drop_risk": "tte_call_drop_min",
    "latency_breach_risk": "tte_latency_breach_min",
    "throughput_risk": "tte_throughput_min",
    "jitter_risk": "tte_jitter_min",
    "mos_risk": "tte_mos_min",
}

EVENT_COLUMN_MAP = {
    "call_drop_risk": "call_drop_event",
    "latency_breach_risk": "latency_breach_event",
    "throughput_risk": "throughput_event",
    "jitter_risk": "jitter_event",
    "mos_risk": "mos_event",
}


def _ensure_congestion_index(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "congestion_index" not in out.columns:
        out["congestion_index"] = out["queue_length"] / (out["active_connections"] + 1.0)
    return out


def _future_window_slice(values: pd.Series, start_idx: int, horizon: int) -> pd.Series:
    return values.iloc[start_idx + 1 : start_idx + horizon + 1]


def _build_future_time_to_event(
    values: pd.Series,
    start_idx: int,
    horizon: int,
    predicate,
) -> tuple[float, int]:
    window = _future_window_slice(values, start_idx, horizon)
    if window.empty:
        return float("nan"), 0
    for step, value in enumerate(window.to_numpy(), start=1):
        try:
            if predicate(value):
                return float(step * SECONDS_PER_STEP / 60.0), 1
        except Exception:
            continue
    return float("nan"), 0


def build_labels(df: pd.DataFrame) -> pd.DataFrame:
    """Build labels using LABEL_AGGREGATION_STRATEGY from config.
    
    All label definitions now use documented, consistent aggregation rationale.
    """
    if df.empty:
        return df

    required = (
        "node_id", "timestamp", "anomaly_score",
        "latency_ms", "throughput_mbps", "jitter_ms",
        "mos_estimate", "queue_length", "active_connections",
    )
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"build_labels missing required columns: {missing}")

    work = _ensure_congestion_index(df)
    work = work.sort_values(["node_id", "timestamp"]).reset_index(drop=True)
    k = LABEL_HORIZON_STEPS
    parts: list[pd.DataFrame] = []

    for _, g in work.groupby("node_id", sort=False):
        gg = g.copy().reset_index(drop=True)

        # Initialize TTE columns ONCE per node_id
        tte_columns: dict[str, list[float]] = {name: [] for name in ETA_TARGETS}
        event_columns: dict[str, list[int]] = {name: [] for name in ETA_TARGETS}
        tte_horizon = LABEL_HORIZON_STEPS

        # ════════════════════════════════════════════════════════════════
        # CRITICAL: ALL LABELS NOW USE STRATEGY FROM config.py
        # ════════════════════════════════════════════════════════════════

        # call_drop_risk: rolling MAX
        strategy = LABEL_AGGREGATION_STRATEGY["call_drop_risk"]
        score = gg["anomaly_score"].fillna(0.0)
        future_score_max = score.shift(-k).rolling(
            k, min_periods=strategy["min_periods"]
        ).max().fillna(0)
        gg["call_drop_risk"] = (
            future_score_max > strategy["threshold"]
        ).astype(np.int8)

        # latency_breach_risk: rolling MEAN
        strategy = LABEL_AGGREGATION_STRATEGY["latency_breach_risk"]
        lat_future_mean = (
            gg["latency_ms"]
            .shift(-k)
            .rolling(k, min_periods=strategy["min_periods"])
            .mean()
        )
        gg["latency_breach_risk"] = (
            lat_future_mean > strategy["threshold"]
        ).astype("Int64")

        # throughput_risk: rolling MIN
        strategy = LABEL_AGGREGATION_STRATEGY["throughput_risk"]
        tp_future_min = (
            gg["throughput_mbps"]
            .shift(-k)
            .rolling(k, min_periods=strategy["min_periods"])
            .min()
        )
        gg["throughput_risk"] = (
            tp_future_min < strategy["threshold"]
        ).astype("Int64")

        # jitter_risk: rolling MEAN
        strategy = LABEL_AGGREGATION_STRATEGY["jitter_risk"]
        jitter_future_mean = (
            gg["jitter_ms"]
            .shift(-k)
            .rolling(k, min_periods=strategy["min_periods"])
            .mean()
        )
        gg["jitter_risk"] = (
            jitter_future_mean > strategy["threshold"]
        ).astype("Int64")

        # congestion_risk: FIXED - NOW USES rolling_max (was point_shift)
        strategy = LABEL_AGGREGATION_STRATEGY["congestion_risk"]
        cong_future_max = (
            gg["congestion_index"]
            .shift(-k)
            .rolling(k, min_periods=strategy["min_periods"])
            .max()
            .fillna(0)
        )
        gg["congestion_risk"] = (
            cong_future_max > strategy["threshold"]
        ).astype("Int64")

        # mos_risk: rolling MIN
        strategy = LABEL_AGGREGATION_STRATEGY["mos_risk"]
        mos_future_min = (
            gg["mos_estimate"]
            .shift(-k)
            .rolling(k, min_periods=strategy["min_periods"])
            .min()
        )
        gg["mos_risk"] = (
            mos_future_min < strategy["threshold"]
        ).astype("Int64")

        # ──── TIME-TO-EVENT LABELS (unchanged) ──────
        for idx in range(len(gg)):
            tte, evt = _build_future_time_to_event(
                gg["anomaly_score"],
                idx,
                tte_horizon,
                lambda x: float(x) > ANOMALY_SCORE_THRESHOLD,
            )
            tte_columns["call_drop_risk"].append(tte)
            event_columns["call_drop_risk"].append(evt)

            tte, evt = _build_future_time_to_event(
                gg["latency_ms"],
                idx,
                tte_horizon,
                lambda x: float(x) > LATENCY_THRESHOLD_MS,
            )
            tte_columns["latency_breach_risk"].append(tte)
            event_columns["latency_breach_risk"].append(evt)

            tte, evt = _build_future_time_to_event(
                gg["throughput_mbps"],
                idx,
                tte_horizon,
                lambda x: float(x) < THROUGHPUT_THRESHOLD_MBPS,
            )
            tte_columns["throughput_risk"].append(tte)
            event_columns["throughput_risk"].append(evt)

            tte, evt = _build_future_time_to_event(
                gg["jitter_ms"],
                idx,
                tte_horizon,
                lambda x: float(x) > JITTER_THRESHOLD_MS,
            )
            tte_columns["jitter_risk"].append(tte)
            event_columns["jitter_risk"].append(evt)

            tte, evt = _build_future_time_to_event(
                gg["mos_estimate"],
                idx,
                tte_horizon,
                lambda x: float(x) < MOS_THRESHOLD,
            )
            tte_columns["mos_risk"].append(tte)
            event_columns["mos_risk"].append(evt)

        for target in ETA_TARGETS:
            gg[TTE_COLUMN_MAP[target]] = tte_columns[target]
            gg[EVENT_COLUMN_MAP[target]] = event_columns[target]

        label_cols = list(TARGET_NAMES)
        gg = gg.dropna(subset=label_cols)
        for c in label_cols:
            gg[c] = gg[c].astype(np.int8)
        parts.append(gg)

    if not parts:
        logger.warning("build_labels: No groups produced. Returning empty dataframe.")
        return pd.DataFrame(columns=work.columns)
    
    result = pd.concat(parts, ignore_index=True)
    
    # ════════════════════════════════════════════════════════════════
    # LOG LABEL DISTRIBUTIONS (Issue #2 fix: explicit diagnostics)
    # ════════════════════════════════════════════════════════════════
    logger.info("═" * 70)
    logger.info(f"build_labels SUMMARY: {len(result)} rows total")
    logger.info("─" * 70)
    for target in TARGET_NAMES:
        if target in result.columns:
            n_pos = int((result[target] == 1).sum())
            n_neg = int((result[target] == 0).sum())
            n_total = len(result)
            pos_rate = 100.0 * n_pos / n_total if n_total else 0.0
            strategy = LABEL_AGGREGATION_STRATEGY.get(target, {})
            agg_method = strategy.get("aggregation", "UNKNOWN")
            logger.info(
                f"  {target:25s}: {n_pos:6d} pos, {n_neg:6d} neg "
                f"({pos_rate:5.1f}%) [{agg_method}]"
            )
    logger.info("═" * 70)
    
    return result
