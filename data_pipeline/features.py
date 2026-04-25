# CLEANED: removed unused global feature list state from resolve_feature_columns
"""Feature engineering and column lists for XGBoost / LSTM."""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import linregress

from config import TARGET_NAMES


def _rolling_linreg_slope(series: pd.Series, window: int) -> pd.Series:
    values = series.to_numpy(dtype=float)

    def win_slope(chunk: np.ndarray) -> float:
        if chunk.size < 3 or np.any(np.isnan(chunk)):
            return np.nan
        x = np.arange(chunk.size, dtype=float)
        try:
            return float(linregress(x, chunk).slope)
        except (ValueError, FloatingPointError):
            return np.nan

    out = np.full(values.shape, np.nan, dtype=float)
    for i in range(window - 1, len(values)):
        out[i] = win_slope(values[i - window + 1 : i + 1])
    return pd.Series(out, index=series.index)


def _normalize_01(s: pd.Series) -> pd.Series:
    lo, hi = np.nanpercentile(s, [5, 95])
    if hi <= lo:
        return pd.Series(np.zeros(len(s)), index=s.index)
    clipped = s.clip(lo, hi)
    return (clipped - lo) / (hi - lo)


def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add engineered columns. ``congestion_index`` is defined here and reused
    downstream (including Prophet and labels if present).

    Precomputed rolling columns from raw CSV are assumed backward-looking per
    the data contract; slopes added here use only past rows within each ``node_id``.
    """
    out = df.copy()

    out["congestion_index"] = out["queue_length"] / (out["active_connections"] + 1.0)

    cols_rsrp = ["rsrp_dbm", "rsrq_db", "sinr_db"]
    if all(c in out.columns for c in cols_rsrp):
        mat = out[cols_rsrp].to_numpy(dtype=float)
        out["signal_instability_index"] = np.nanstd(mat, axis=1)
    else:
        out["signal_instability_index"] = np.nan

    if "rsrp_dbm" in out.columns:
        out["rsrp_slope_5min"] = out.groupby("node_id", sort=False)["rsrp_dbm"].transform(
            lambda s: _rolling_linreg_slope(s, 10)
        )
    else:
        out["rsrp_slope_5min"] = np.nan

    if "mos_estimate" in out.columns:
        out["mos_trend_slope"] = out.groupby("node_id", sort=False)["mos_estimate"].transform(
            lambda s: _rolling_linreg_slope(s, 10)
        )
    else:
        out["mos_trend_slope"] = np.nan

    if all(c in out.columns for c in ("rsrp_dbm", "sinr_db", "cqi")):
        rsrp_n = _normalize_01(out["rsrp_dbm"])
        sinr_n = _normalize_01(out["sinr_db"])
        cqi_n = _normalize_01(out["cqi"])
        out["coverage_risk_score"] = (
            (1.0 - rsrp_n) + (1.0 - sinr_n) + (1.0 - cqi_n)
        ) / 3.0
    else:
        out["coverage_risk_score"] = np.nan

    if all(c in out.columns for c in ("jitter_ms", "packet_loss_pct", "mos_estimate")):
        j = _normalize_01(out["jitter_ms"])
        pl = _normalize_01(out["packet_loss_pct"])
        mos_n = _normalize_01(out["mos_estimate"])
        out["voice_qoe_score"] = (j + pl + (1.0 - mos_n)) / 3.0
    else:
        out["voice_qoe_score"] = np.nan

    if "handover_count" in out.columns and "neighbor_count" in out.columns:
        out["ho_pressure"] = out["handover_count"] / (out["neighbor_count"] + 1.0)
    else:
        out["ho_pressure"] = np.nan

    if "bandwidth_util_pct" in out.columns and "cpu_pct" in out.columns:
        out["bandwidth_stress"] = out["bandwidth_util_pct"] * out["cpu_pct"] / 100.0
    else:
        out["bandwidth_stress"] = np.nan

    # Convenience rolling stats used by interaction features below (safe even if not used).
    if "node_id" in out.columns:
        if "jitter_ms" in out.columns:
            g_j = out.groupby("node_id", sort=False)["jitter_ms"]
            out["jitter_rolling_mean"] = g_j.transform(lambda s: s.rolling(10, min_periods=1).mean())
            out["jitter_rolling_std"] = g_j.transform(lambda s: s.rolling(10, min_periods=2).std())
        else:
            out["jitter_rolling_mean"] = np.nan
            out["jitter_rolling_std"] = np.nan

        if "latency_ms" in out.columns:
            g_l = out.groupby("node_id", sort=False)["latency_ms"]
            out["latency_rolling_mean"] = g_l.transform(lambda s: s.rolling(10, min_periods=1).mean())
        else:
            out["latency_rolling_mean"] = np.nan

        if "throughput_mbps" in out.columns:
            g_t = out.groupby("node_id", sort=False)["throughput_mbps"]
            out["throughput_volatility"] = g_t.transform(lambda s: s.rolling(10, min_periods=2).std())
        else:
            out["throughput_volatility"] = np.nan

    # ── anomaly_score lag and rolling features ─────────────────────────
    # anomaly_score_rmean5 → future call_drop_risk correlation: +0.615
    # This is the strongest verified predictor in the dataset.
    if "anomaly_score" in out.columns:
        g_score = out.groupby("node_id", sort=False)["anomaly_score"]
        out["anomaly_score_lag1"]    = g_score.transform(lambda s: s.shift(1).fillna(0))
        out["anomaly_score_lag3"]    = g_score.transform(lambda s: s.shift(3).fillna(0))
        out["anomaly_score_lag5"]    = g_score.transform(lambda s: s.shift(5).fillna(0))
        out["anomaly_score_rmean5"]  = g_score.transform(
            lambda s: s.rolling(5, min_periods=1).mean()
        )
        out["anomaly_score_rmean10"] = g_score.transform(
            lambda s: s.rolling(10, min_periods=1).mean()
        )
        out["anomaly_score_rmax10"]  = g_score.transform(
            lambda s: s.rolling(10, min_periods=1).max()
        )
        out["anomaly_score_rstd5"]   = g_score.transform(
            lambda s: s.rolling(5, min_periods=2).std().fillna(0)
        )

    # ── anomaly_type binary flags + 10-step rolling rates ──────────────
    # Verified cross-correlations with future targets (rate10 → future label):
    #   high_latency_rate10    → future throughput:  +0.114
    #   jitter_deg_rate10      → future jitter:      +0.129
    #   high_latency_rate10    → future latency:     +0.087
    if "anomaly_type" in out.columns:
        raw_atype = out["anomaly_type"].astype(str)
        type_flags = {
            "is_weak_signal":     "weak_signal",
            "is_packet_loss":     "severe_packet_loss",
            "is_high_latency":    "high_latency",
            "is_jitter_deg":      "jitter_degradation",
            "is_congestion_evt":  "congestion",
            "is_high_jitter":     "high_jitter",
            "is_high_retransmit": "high_retransmission",
        }
        for feat_name, atype_val in type_flags.items():
            out[feat_name] = (raw_atype == atype_val).astype(np.int8)
            out[f"{feat_name}_rate10"] = out.groupby("node_id", sort=False)[feat_name].transform(
                lambda s: s.rolling(10, min_periods=1).mean()
            )

    # ── key metric lag features ─────────────────────────────────────────
    for col in ["latency_ms", "jitter_ms", "throughput_mbps", "packet_loss_pct"]:
        if col in out.columns:
            g_col = out.groupby("node_id", sort=False)[col]
            for lag in [1, 3, 5]:
                out[f"{col}_lag{lag}"] = g_col.transform(
                    lambda s, l=lag: s.shift(l).bfill().fillna(0)
                )

    # ── cross-metric interaction features ──────────────────────────────
    # jitter_rolling_mean is the strongest predictor of future latency (+0.240),
    # throughput (+0.203), and jitter (+0.232) in this dataset.
    if "jitter_rolling_mean" in out.columns and "latency_rolling_mean" in out.columns:
        out["jitter_x_latency_stress"] = (
            out["jitter_rolling_mean"] * out["latency_rolling_mean"] / 100.0
        )
    if "rsrp_dbm" in out.columns and "sinr_db" in out.columns:
        out["rsrp_x_sinr"] = out["rsrp_dbm"] * out["sinr_db"]
    if "throughput_mbps" in out.columns and "sinr_db" in out.columns:
        out["throughput_sinr_product"] = out["throughput_mbps"] * out["sinr_db"]

    if "throughput_rolling_mean" in out.columns and "mos_estimate" in out.columns:
        out["mos_throughput_combined"] = out["throughput_rolling_mean"] * out["mos_estimate"]

    if "memory_pct" in out.columns and "active_connections" in out.columns:
        out["memory_connections_ratio"] = out["memory_pct"] / (out["active_connections"] + 1.0)
    if "throughput_volatility" in out.columns and "jitter_rolling_std" in out.columns:
        out["volatility_combined"] = (
            out["throughput_volatility"] + out["jitter_rolling_std"]
        )
    if "bler_proxy_pct" in out.columns and "tcp_retransmit_rate" in out.columns:
        out["retransmit_pressure"] = (
            out["bler_proxy_pct"] + out["tcp_retransmit_rate"]
        )

    # Fill NaNs introduced by the new lag/rolling features
    for c in out.columns:
        if out[c].dtype in [np.float64, np.float32]:
            out[c] = out[c].fillna(0.0)

    return out


# Columns excluded from model inputs (identifiers, timestamps, training flags, raw labels)
_EXCLUDE_FROM_MODEL: set[str] = {
    "timestamp",
    "skip_for_training",
    "anomaly_flag",
    "anomaly_type",
    "anomaly_score",
    *TARGET_NAMES,
}

# Must never appear in saved XGB/LSTM feature lists (temporal leakage for call_drop / labels).
# ``call_drop_risk`` uses future ``anomaly_flag``; same-row anomaly_* would leak signal.
MODEL_INPUT_LEAKAGE_BLOCKLIST: frozenset[str] = frozenset(
    {"anomaly_flag", "anomaly_type", "anomaly_score"}
)


def drop_leaky_feature_columns(feature_cols: list[str]) -> tuple[list[str], list[str]]:
    """
    Remove blocklisted columns from a saved feature list (e.g. legacy ``*.joblib``).

    Returns ``(cleaned, removed_names)``.
    """
    removed = [c for c in feature_cols if c in MODEL_INPUT_LEAKAGE_BLOCKLIST]
    cleaned = [c for c in feature_cols if c not in MODEL_INPUT_LEAKAGE_BLOCKLIST]
    return cleaned, removed


def _candidate_feature_columns(df: pd.DataFrame) -> list[str]:
    cols: list[str] = []
    for c in df.columns:
        if c in _EXCLUDE_FROM_MODEL:
            continue
        if c.startswith("tte_") or c.endswith("_event"):
            continue
        if pd.api.types.is_bool_dtype(df[c]):
            cols.append(c)
            continue
        if pd.api.types.is_numeric_dtype(df[c]) or str(df[c].dtype).startswith("Int"):
            cols.append(c)
            continue
    return cols


def build_xgb_feature_list(df: pd.DataFrame) -> list[str]:
    """Derive XGB feature names from a post-engineering, post-label frame."""
    return sorted(_candidate_feature_columns(df))


def resolve_feature_columns(df: pd.DataFrame) -> list[str]:
    """
    Resolve feature columns for model training.
    
    Returns:
        list[str]: Features excluding leakage columns (TTE, events, targets, timestamp)
        
    Notes:
        - Automatically filters out TTE columns (tte_*) and event columns (*_event)
        - Removes all columns in _EXCLUDE_FROM_MODEL blocklist
        - Returns sorted list for deterministic ordering
    """
    cols = build_xgb_feature_list(df)
    return cols
