"""
Prediction bridge.

Buffers metrics from `qos.metrics.raw` into per-node windows and periodically
calls the *real* prediction agent's `/api/predict` endpoint. When the agent
returns a `predicted_breach` projection, we publish a forecast `AlertEvent`
on `qos.alerts` so the dashboard's forecast tab lights up end-to-end.

The agent itself maintains MLflow runs, RAG memory and explainability â€”
this bridge intentionally stays narrow so future tweaks land upstream.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections import deque
from datetime import datetime, timezone
from typing import Any, Deque

import httpx

from contracts.schemas import (
    AlertEvent,
    Severity,
    StreamName,
    TopFactor,
)

from .graceful import install_sigterm_handler
from .otel import flush_tracer, init_tracer
from .redis_streams import RedisStreamsBus, run_consumer

log = logging.getLogger("qos.bridge.prediction")

PREDICTION_URL = os.getenv("PREDICTION_URL", "http://prediction:8000")
GROUP = os.getenv("PREDICTION_GROUP", "prediction")
CONSUMER = os.getenv("PREDICTION_CONSUMER", "prediction-1")
WINDOW_ROWS = int(os.getenv("PREDICTION_WINDOW_ROWS", "60"))
WINDOW_FLUSH_SECS = float(os.getenv("PREDICTION_FLUSH_SECS", "30"))
MIN_ROWS = int(os.getenv("PREDICTION_MIN_ROWS", "20"))
PREDICTION_TIMEOUT_SECONDS = float(os.getenv("PREDICTION_TIMEOUT_SECONDS", "45"))
PREDICTION_RETRY_BACKOFF_SECS = float(os.getenv("PREDICTION_RETRY_BACKOFF_SECS", "15"))

# Numeric columns the agent's preprocessor.joblib was fitted on. The
# SimpleImputer rejects frames that don't have all 53 â€” supply NaN for
# anything missing on a given metric so it can fall back to the training
# median.
# Categorical / boolean columns the LSTM and engineer_features expect.
# Pass-through verbatim from the metric event so engineered features such as
# `is_peak_hour`, `baseline_phase`, traffic-type embeddings can be derived.
PREPROCESSOR_CATEGORICAL_COLS: tuple[str, ...] = (
    "zone_id", "cell_id", "device_type", "traffic_type", "detection_method",
    "ho_status", "anomaly_type", "cell_id_router", "network_type_router",
    "wifi_signal_category", "cellular_signal_category", "signal_health_overall",
    "signal_dominant_link", "data_quality_issues", "data_quality_rating",
    "baseline_phase", "data_source", "is_peak_hour", "teams_in_meeting",
)

PREPROCESSOR_NUMERIC_COLS: tuple[str, ...] = (
    "latency_ms", "jitter_ms", "packet_loss_pct", "throughput_mbps",
    "bandwidth_util_pct", "cpu_pct", "memory_pct", "active_connections",
    "queue_length", "traffic_confidence", "hour_of_day", "rssi_dbm",
    "signal_quality_pct", "channel", "handover_count", "neighbor_count",
    "channel_util_pct", "connected_stations", "tcp_retransmit_rate",
    "mos_estimate", "wifi_signal_score", "cellular_signal_score",
    "signal_health_score", "rsrp_dbm", "rsrq_db", "sinr_db", "cqi", "pci",
    "earfcn", "mcs", "bler_proxy_pct", "bler_delta", "ho_success_rate_pct",
    "cssr_proxy_pct", "latency_rolling_mean", "latency_rolling_std",
    "latency_trend", "latency_volatility", "jitter_rolling_mean",
    "jitter_rolling_std", "jitter_increasing", "throughput_rolling_mean",
    "throughput_rolling_std", "throughput_volatility", "anomaly_rate_recent",
    "signal_degradation_rate", "data_completeness_pct", "required_metrics_pct",
    "router_metrics_pct", "hour_anomaly_rate", "incident_recovery_time",
    "collection_completion_pct", "anomaly_score",
)


class _Buffer:
    """Per-node ring buffer of recent samples ready for batch inference."""

    def __init__(self, capacity: int = WINDOW_ROWS):
        self._buf: dict[str, Deque[dict[str, Any]]] = {}
        self.capacity = capacity

    def add(self, sample: dict[str, Any]) -> None:
        node = str(sample.get("node_id") or sample.get("cell_id") or "default")
        q = self._buf.setdefault(node, deque(maxlen=self.capacity))
        q.append(sample)

    def drain(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for q in self._buf.values():
            records.extend(q)
        return records

    def ready(self, min_rows: int = 20) -> bool:
        return any(len(q) >= min_rows for q in self._buf.values())


def _record_for_predict(metric: dict[str, Any]) -> dict[str, Any]:
    extra = metric.get("extra") or {}
    out: dict[str, Any] = {
        "timestamp": metric.get("occurred_at") or metric.get("timestamp"),
        "node_id": metric.get("node_id") or metric.get("cell_id") or "default",
    }
    for col in PREPROCESSOR_NUMERIC_COLS:
        v = metric.get(col)
        if v is None:
            v = extra.get(col)
        try:
            out[col] = float(v) if v is not None else None
        except (TypeError, ValueError):
            out[col] = None
    for col in PREPROCESSOR_CATEGORICAL_COLS:
        v = metric.get(col)
        if v is None:
            v = extra.get(col)
        out[col] = v
    return out


def _severity_from_risk(risk: float) -> Severity:
    if risk >= 0.85:
        return Severity.CRITICAL
    if risk >= 0.7:
        return Severity.HIGH
    if risk >= 0.5:
        return Severity.MEDIUM
    return Severity.LOW


# Maps the agent's `primary_metric_name` (one of six risk heads) to the KPI
# the dashboard reasons about, so a forecast says "throughput will breach"
# rather than "throughput_risk will breach".
_RISK_HEAD_TO_KPI: dict[str, tuple[str, str]] = {
    "congestion_risk": ("throughput_mbps", "Throughput"),
    "throughput_risk": ("throughput_mbps", "Throughput"),
    "latency_breach_risk": ("latency_ms", "Latency"),
    "jitter_risk": ("jitter_ms", "Jitter"),
    "call_drop_risk": ("ho_success_rate_pct", "Handover success"),
    "mos_risk": ("mos_estimate", "Voice quality (MOS)"),
}


def _forecast_alert(prediction: dict[str, Any], cell_id: str | None) -> AlertEvent | None:
    # Real shape from prediction_agent: {risk_probs, primary_metric_name,
    # primary_metric_probability, primary_metric_eta_min, top_3_drivers, ...}.
    # Fall back to the legacy risk_score/predicted_breach contract for safety.
    primary_prob = prediction.get("primary_metric_probability")
    primary_name = prediction.get("primary_metric_name")
    eta_min = prediction.get("primary_metric_eta_min")

    if primary_prob is None:
        risk_probs = prediction.get("risk_probs") or {}
        if risk_probs:
            primary_name, primary_prob = max(risk_probs.items(), key=lambda kv: kv[1])
        else:
            primary_prob = prediction.get("risk_score") or prediction.get("risk")

    if primary_prob is None:
        return None
    try:
        risk_f = float(primary_prob)
    except (TypeError, ValueError):
        return None
    if risk_f < 0.5:
        return None

    kpi, kpi_label = _RISK_HEAD_TO_KPI.get(str(primary_name or ""), ("latency_ms", "Latency"))
    seconds: int | None = None
    if eta_min is not None:
        try:
            seconds = max(1, int(float(eta_min) * 60.0))
        except (TypeError, ValueError):
            seconds = None

    drivers_raw = prediction.get("top_3_drivers") or {}
    if isinstance(drivers_raw, dict):
        drivers = drivers_raw.get(str(primary_name)) or next(iter(drivers_raw.values()), [])
    else:
        drivers = drivers_raw or prediction.get("drivers") or prediction.get("top_factors") or []
    top: list[TopFactor] = []
    for d in (drivers or [])[:3]:
        try:
            feat = str(d.get("feature") or d.get("name") or "")
            val = float(d.get("value") or d.get("impact") or 0.0)
            direction_raw = str(d.get("direction") or "increases_risk")
            top.append(
                TopFactor(
                    display_label=str(d.get("display_label") or feat.replace("_", " ").title()),
                    technical_name=feat,
                    impact_pct=max(0.0, min(100.0, abs(val) * 100.0)),
                    direction=("up" if "increase" in direction_raw or val > 0 else "down"),
                )
            )
        except Exception:  # noqa: BLE001
            continue

    sev = _severity_from_risk(risk_f)
    if seconds:
        if seconds < 90:
            display = f"Forecast: {kpi_label} breach in ~{seconds}s"
        else:
            display = f"Forecast: {kpi_label} breach in ~{seconds // 60}m"
    else:
        display = f"Forecast: {kpi_label} degradation likely"

    return AlertEvent(
        tenant_id="default",
        cell_id=cell_id,
        node_id=str(prediction.get("node_id") or "default"),
        producer="prediction",
        producer_version="4.1",
        severity=sev,
        display_label=display,
        technical_label=f"{primary_name}={risk_f:.2f}",
        detector="forecast",
        confidence=risk_f,
        time_to_breach_seconds=seconds,
        breach_threshold=None,
        breach_metric=kpi,
        top_factors=top,
    )


async def _flush(client: httpx.AsyncClient, bus: RedisStreamsBus, buffer: _Buffer) -> bool:
    if not buffer.ready(MIN_ROWS):
        return True
    records = buffer.drain()
    if not records:
        return True
    try:
        resp = await client.post(
            f"{PREDICTION_URL}/api/predict",
            json={"records": [_record_for_predict(r) for r in records],
                  "generate_llm": False, "persist": True},
            timeout=PREDICTION_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        log.warning("prediction call failed: %s", exc)
        await asyncio.sleep(PREDICTION_RETRY_BACKOFF_SECS)
        return False

    body = resp.json()
    cell_id = (records[-1].get("cell_id") if records else None)
    for pred in body.get("predictions", []):
        alert = _forecast_alert(pred, cell_id)
        if alert is not None:
            await bus.publish(StreamName.ALERTS, alert)
    return True


async def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    install_sigterm_handler(log)
    init_tracer(os.getenv("OTEL_SERVICE_NAME", "prediction-bridge"))
    bus = RedisStreamsBus()
    await bus.connect()
    client = httpx.AsyncClient()
    buffer = _Buffer()

    for _ in range(60):
        try:
            r = await client.get(f"{PREDICTION_URL}/api/health", timeout=2.0)
            if r.status_code == 200:
                log.info("prediction agent ready")
                break
        except httpx.HTTPError:
            pass
        await asyncio.sleep(2.0)

    last_flush = asyncio.get_event_loop().time()

    async def handler(_msg_id: str, payload: dict[str, Any]) -> None:
        nonlocal last_flush
        buffer.add(payload)
        now = asyncio.get_event_loop().time()
        if now - last_flush >= WINDOW_FLUSH_SECS:
            last_flush = now
            await _flush(client, bus, buffer)

    try:
        await run_consumer(
            bus,
            StreamName.METRICS_RAW,
            group=GROUP,
            consumer=CONSUMER,
            handler=handler,
        )
    finally:
        await client.aclose()
        await bus.close()
        flush_tracer()
        log.info("Shutdown complete")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
