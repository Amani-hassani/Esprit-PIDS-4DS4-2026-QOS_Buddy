import plotly.express as px
import pandas as pd


def line_chart_latency(ts_df: pd.DataFrame):
    if ts_df.empty or "timestamp" not in ts_df.columns or "latency_ms" not in ts_df.columns:
        return None
    fig = px.line(
        ts_df,
        x="timestamp",
        y="latency_ms",
        title="Latence dans le temps",
        markers=False
    )
    fig.update_layout(template="plotly_dark", height=350)
    return fig


def line_chart_jitter(ts_df: pd.DataFrame):
    if ts_df.empty or "timestamp" not in ts_df.columns or "jitter_ms" not in ts_df.columns:
        return None
    fig = px.line(
        ts_df,
        x="timestamp",
        y="jitter_ms",
        title="Jitter dans le temps",
        markers=False
    )
    fig.update_layout(template="plotly_dark", height=350)
    return fig


def line_chart_throughput(ts_df: pd.DataFrame):
    if ts_df.empty or "timestamp" not in ts_df.columns or "throughput_mbps" not in ts_df.columns:
        return None
    fig = px.line(
        ts_df,
        x="timestamp",
        y="throughput_mbps",
        title="Throughput dans le temps",
        markers=False
    )
    fig.update_layout(template="plotly_dark", height=350)
    return fig


def bar_anomaly_distribution(dist_df: pd.DataFrame):
    if dist_df.empty:
        return None
    fig = px.bar(
        dist_df,
        x="anomaly_type",
        y="count",
        title="Distribution des anomalies"
    )
    fig.update_layout(template="plotly_dark", height=350, xaxis_title="Type d'anomalie", yaxis_title="Nombre")
    return fig


def line_daily_comparison(daily_df: pd.DataFrame):
    if daily_df.empty or "date" not in daily_df.columns:
        return None

    melted = daily_df.melt(id_vars="date", var_name="metric", value_name="value")
    fig = px.line(
        melted,
        x="date",
        y="value",
        color="metric",
        title="Comparaison journalière des métriques"
    )
    fig.update_layout(template="plotly_dark", height=380)
    return fig