"""
Detection bridge.

Subscribes to `qos.metrics.raw`, calls the *real* detection agent's
`/api/v1/detect/single` endpoint (Keras autoencoder + MAE-vs-threshold), and
publishes anomalies as `AlertEvent` on `qos.alerts`.

This is a thin adapter — all model logic lives in the upstream
`detection agent/backend/app/services/inference_service.py`. We do not
re-implement scoring here.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

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

log = logging.getLogger("qos.bridge.detection")

DETECTION_URL = os.getenv("DETECTION_URL", "http://detection:8000")
GROUP = os.getenv("DETECTION_GROUP", "detection")
CONSUMER = os.getenv("DETECTION_CONSUMER", "detection-1")
ALERT_COOLDOWN_SECONDS = float(os.getenv("DETECTION_ALERT_COOLDOWN_SECONDS", "45"))

# 30 features the upstream model expects, in the order the scaler was fit on.
FEATURES: tuple[str, ...] = (
    "latency_ms", "jitter_ms", "packet_loss_pct", "throughput_mbps",
    "bandwidth_util_pct", "cpu_pct", "memory_pct", "active_connections",
    "queue_length", "traffic_confidence", "hour_of_day", "rssi_dbm",
    "signal_quality_pct", "channel", "channel_util_pct", "connected_stations",
    "tcp_retransmit_rate", "mos_estimate", "wifi_signal_score",
    "cellular_signal_score", "signal_health_score", "rsrp_dbm",
    "rsrq_db", "sinr_db", "cqi", "mcs", "bler_proxy_pct",
    "ho_success_rate_pct", "cssr_proxy_pct", "anomaly_rate_recent",
)

_SEVERITY_MAP = {
    "CRITICAL": Severity.CRITICAL,
    "MODERATE": Severity.HIGH,
    "LIGHT": Severity.MEDIUM,
    "N/A": Severity.LOW,
}

_recent_alerts: dict[tuple[str, str, str, str], float] = {}


def _severity_value(severity: Severity | str) -> str:
    return severity.value if isinstance(severity, Severity) else str(severity)


def _row_from_metric(metric: dict[str, Any]) -> dict[str, float]:
    extra = metric.get("extra") or {}
    row: dict[str, float] = {}
    for f in FEATURES:
        v = metric.get(f)
        if v is None:
            v = extra.get(f)
        try:
            row[f] = float(v) if v is not None else 0.0
        except (TypeError, ValueError):
            row[f] = 0.0
    return row


def _top_factors(metric: dict[str, Any]) -> list[TopFactor]:
    """Pick the most-degraded KPIs to surface as NOC-language drivers."""
    candidates: list[tuple[str, str, float, str]] = []  # (display, tech, impact, dir)

    def push(display: str, tech: str, value: float | None, ideal: float, scale: float, up: bool):
        if value is None:
            return
        delta = (value - ideal) if up else (ideal - value)
        impact = max(0.0, min(100.0, delta / scale * 100.0))
        if impact >= 5.0:
            candidates.append((display, tech, impact, "up" if up else "down"))

    push("Round-trip delay", "latency_ms", metric.get("latency_ms"), 30.0, 200.0, True)
    push("Jitter", "jitter_ms", metric.get("jitter_ms"), 5.0, 60.0, True)
    push("Packet loss", "packet_loss_pct", metric.get("packet_loss_pct"), 0.5, 8.0, True)
    push("Voice quality (MOS)", "mos_estimate", metric.get("mos_estimate"), 4.0, 2.0, False)
    push("Throughput", "throughput_mbps", metric.get("throughput_mbps"), 200.0, 200.0, False)
    push("Host CPU", "cpu_pct", metric.get("cpu_pct"), 60.0, 40.0, True)

    candidates.sort(key=lambda c: c[2], reverse=True)
    return [
        TopFactor(display_label=d, technical_name=t, impact_pct=round(i, 1), direction=dr)
        for d, t, i, dr in candidates[:3]
    ]


def _display_label(metric: dict[str, Any], severity: Severity) -> str:
    lat = metric.get("latency_ms")
    loss = metric.get("packet_loss_pct")
    mos = metric.get("mos_estimate")
    cpu = metric.get("cpu_pct")
    if loss is not None and loss >= 5.0:
        return "Packet loss spike"
    if lat is not None and lat >= 150.0:
        return "Latency surge"
    if mos is not None and mos < 3.0:
        return "Voice quality degraded"
    if cpu is not None and cpu >= 90.0:
        return "Host saturation"
    return f"Behavioural anomaly ({severity.value})"


def _dedupe_key(payload: dict[str, Any], alert: AlertEvent) -> tuple[str, str, str, str]:
    top = ",".join(
        f.technical_name or f.display_label
        for f in (alert.top_factors or [])[:2]
    )
    return (
        str(alert.cell_id or payload.get("node_id") or "default"),
        str(alert.detector),
        _severity_value(alert.severity),
        f"{alert.display_label}:{top}",
    )


def _should_publish(payload: dict[str, Any], alert: AlertEvent) -> bool:
    if ALERT_COOLDOWN_SECONDS <= 0:
        return True
    key = _dedupe_key(payload, alert)
    now = asyncio.get_event_loop().time()
    last = _recent_alerts.get(key, 0.0)
    if now - last < ALERT_COOLDOWN_SECONDS:
        return False
    _recent_alerts[key] = now
    return True


async def _handle(
    client: httpx.AsyncClient, bus: RedisStreamsBus, _msg_id: str, payload: dict[str, Any]
) -> None:
    body = _row_from_metric(payload)
    try:
        resp = await client.post(
            f"{DETECTION_URL}/api/v1/detect/single",
            json=body,
            timeout=5.0,
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        log.warning("detection call failed: %s", exc)
        return

    out = resp.json()
    if not out.get("is_anomaly"):
        return

    sev = _SEVERITY_MAP.get(out.get("severity"), Severity.MEDIUM)
    confidence = max(0.0, min(1.0, float(out.get("confidence", 50)) / 100.0))

    alert = AlertEvent(
        correlation_id=payload.get("correlation_id") or f"corr-{payload.get('event_id','')}",
        causation_id=payload.get("event_id"),
        tenant_id=payload.get("tenant_id", "default"),
        zone_id=payload.get("zone_id"),
        cell_id=payload.get("cell_id"),
        node_id=payload.get("node_id"),
        producer="detection",
        producer_version="1.0",
        severity=sev,
        display_label=_display_label(payload, sev),
        technical_label=f"autoencoder-mae={out.get('score'):.4f}",
        detector="behavioral",
        confidence=confidence,
        top_factors=_top_factors(payload),
        metric_correlation_id=payload.get("correlation_id"),
        monitoring_features=body,
    )
    if not _should_publish(payload, alert):
        return
    await bus.publish(StreamName.ALERTS, alert)


async def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    install_sigterm_handler(log)
    init_tracer(os.getenv("OTEL_SERVICE_NAME", "detection-bridge"))
    bus = RedisStreamsBus()
    await bus.connect()
    client = httpx.AsyncClient()

    # Wait for the detection agent to be ready before draining metrics.
    for _ in range(60):
        try:
            r = await client.get(f"{DETECTION_URL}/api/v1/health", timeout=2.0)
            if r.status_code == 200:
                log.info("detection agent ready: %s", r.json())
                break
        except httpx.HTTPError:
            pass
        await asyncio.sleep(2.0)
    else:
        log.warning("detection health never returned 200 — proceeding anyway")

    async def handler(msg_id: str, payload: dict[str, Any]) -> None:
        await _handle(client, bus, msg_id, payload)

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
