import pandas as pd


def prepare_numeric(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    result = df.copy()
    for col in columns:
        if col in result.columns:
            result[col] = pd.to_numeric(result[col], errors="coerce")
    return result


def build_overview_metrics(df: pd.DataFrame, incidents_df: pd.DataFrame) -> dict:
    metrics = {
        "samples": len(df),
        "incidents": len(incidents_df),
        "anomalies": 0,
        "avg_latency": None,
        "avg_jitter": None,
        "avg_throughput": None,
        "max_latency": None,
        "max_jitter": None,
    }

    if "anomaly_flag" in df.columns:
        metrics["anomalies"] = int((df["anomaly_flag"].astype(str).str.lower() == "true").sum())

    if "latency_ms" in df.columns:
        s = pd.to_numeric(df["latency_ms"], errors="coerce").dropna()
        if not s.empty:
            metrics["avg_latency"] = round(s.mean(), 2)
            metrics["max_latency"] = round(s.max(), 2)

    if "jitter_ms" in df.columns:
        s = pd.to_numeric(df["jitter_ms"], errors="coerce").dropna()
        if not s.empty:
            metrics["avg_jitter"] = round(s.mean(), 2)
            metrics["max_jitter"] = round(s.max(), 2)

    if "throughput_mbps" in df.columns:
        s = pd.to_numeric(df["throughput_mbps"], errors="coerce").dropna()
        if not s.empty:
            metrics["avg_throughput"] = round(s.mean(), 2)

    return metrics


def build_time_series(df: pd.DataFrame) -> pd.DataFrame:
    needed = ["timestamp", "latency_ms", "jitter_ms", "throughput_mbps", "anomaly_type"]
    cols = [c for c in needed if c in df.columns]
    if not cols:
        return pd.DataFrame()

    ts = df[cols].copy()
    if "timestamp" in ts.columns:
        ts["timestamp"] = pd.to_datetime(ts["timestamp"], errors="coerce")
        ts = ts.dropna(subset=["timestamp"]).sort_values("timestamp")

    for col in ["latency_ms", "jitter_ms", "throughput_mbps"]:
        if col in ts.columns:
            ts[col] = pd.to_numeric(ts[col], errors="coerce")

    return ts


def build_anomaly_distribution(df: pd.DataFrame) -> pd.DataFrame:
    if "anomaly_type" not in df.columns:
        return pd.DataFrame(columns=["anomaly_type", "count"])

    dist = (
        df["anomaly_type"]
        .astype(str)
        .fillna("unknown")
        .value_counts()
        .reset_index()
    )
    dist.columns = ["anomaly_type", "count"]
    return dist


def build_daily_comparison(df: pd.DataFrame) -> pd.DataFrame:
    if "timestamp" not in df.columns:
        return pd.DataFrame()

    work = df.copy()
    work["timestamp"] = pd.to_datetime(work["timestamp"], errors="coerce")
    work = work.dropna(subset=["timestamp"])
    if work.empty:
        return pd.DataFrame()

    work["date"] = work["timestamp"].dt.date

    for col in ["latency_ms", "jitter_ms", "throughput_mbps"]:
        if col in work.columns:
            work[col] = pd.to_numeric(work[col], errors="coerce")

    group_cols = {}
    if "latency_ms" in work.columns:
        group_cols["latency_ms"] = "mean"
    if "jitter_ms" in work.columns:
        group_cols["jitter_ms"] = "mean"
    if "throughput_mbps" in work.columns:
        group_cols["throughput_mbps"] = "mean"

    daily = work.groupby("date", as_index=False).agg(group_cols)
    daily = daily.sort_values("date")
    return daily


def build_trend_summary(df: pd.DataFrame) -> dict:
    result = {
        "latency_trend": "N/A",
        "jitter_trend": "N/A",
        "throughput_trend": "N/A",
    }

    daily = build_daily_comparison(df)
    if len(daily) < 2:
        return result

    def compute_trend(series: pd.Series, higher_is_worse: bool) -> str:
        first = pd.to_numeric(series.iloc[0], errors="coerce")
        last = pd.to_numeric(series.iloc[-1], errors="coerce")
        if pd.isna(first) or pd.isna(last):
            return "N/A"

        delta = last - first
        if abs(delta) < 1e-6:
            return "stable"

        if higher_is_worse:
            return "en hausse (dégradation)" if delta > 0 else "en baisse (amélioration)"
        return "en hausse (amélioration)" if delta > 0 else "en baisse (dégradation)"

    if "latency_ms" in daily.columns:
        result["latency_trend"] = compute_trend(daily["latency_ms"], higher_is_worse=True)
    if "jitter_ms" in daily.columns:
        result["jitter_trend"] = compute_trend(daily["jitter_ms"], higher_is_worse=True)
    if "throughput_mbps" in daily.columns:
        result["throughput_trend"] = compute_trend(daily["throughput_mbps"], higher_is_worse=False)

    return result


def build_incident_summary(incidents_df: pd.DataFrame, limit: int = 10) -> pd.DataFrame:
    if incidents_df.empty:
        return pd.DataFrame()

    work = incidents_df.copy()
    if "max_score" in work.columns:
        work["max_score"] = pd.to_numeric(work["max_score"], errors="coerce")

    cols = [c for c in [
        "start_timestamp", "end_timestamp", "incident_type", "severity",
        "duration_sec", "samples", "max_score", "source_file"
    ] if c in work.columns]

    if "max_score" in work.columns:
        work = work.sort_values("max_score", ascending=False, na_position="last")

    return work[cols].head(limit).reset_index(drop=True)