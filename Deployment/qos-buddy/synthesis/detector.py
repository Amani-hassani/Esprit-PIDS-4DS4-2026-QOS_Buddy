"""
Detector — turns a single MetricEvent into zero or one AlertEvent.

Three stacked strategies, all driven by REAL values on the live sample:
  1. Threshold breach   — compare against THRESHOLDS (NOC-tuned)
  2. Behavioral anomaly — `anomaly_score` from the collector itself
  3. Composite          — both threshold AND behavioral firing → escalate

Top contributing factors are computed from the live KPIs vs baseline so
the NOC sees the *why* without ever seeing model jargon.
"""

from __future__ import annotations

from typing import Any

from contracts.noc_vocab import NOC_FACTOR_LABELS, factor_label
from contracts.schemas import AlertEvent, MetricEvent, Severity, TopFactor

from .thresholds import THRESHOLDS

# Field set we surface as candidate factors. Order matters for tie-breaks.
_FACTOR_FIELDS: tuple[str, ...] = (
    "latency_ms",
    "jitter_ms",
    "packet_loss_pct",
    "throughput_mbps",
    "bler_proxy_pct",
    "tcp_retransmit_rate",
    "rsrp_dbm",
    "sinr_db",
    "rssi_dbm",
    "cpu_pct",
    "memory_pct",
)


def detect(metric: MetricEvent) -> AlertEvent | None:
    """Return an AlertEvent if the sample warrants one, else None."""
    threshold_hit, threshold_severity, threshold_label = _threshold_alert(metric)
    behavioral_hit, behavioral_severity = _behavioral_alert(metric)

    if not threshold_hit and not behavioral_hit:
        return None

    # Compose detector + severity (worst of the two).
    if threshold_hit and behavioral_hit:
        detector = "composite"
        severity = _max_severity(threshold_severity, behavioral_severity)
        display_label = threshold_label or "Network behaviour shift"
    elif threshold_hit:
        detector = "threshold"
        severity = threshold_severity
        display_label = threshold_label or "KPI threshold crossed"
    else:
        detector = "behavioral"
        severity = behavioral_severity
        display_label = "Network behaviour shift"

    factors = rank_top_factors(metric)
    confidence = _confidence(metric, detector)

    return AlertEvent(
        producer="synthesis",
        producer_version="0.1",
        correlation_id=metric.correlation_id,
        causation_id=metric.event_id,
        tenant_id=metric.tenant_id,
        zone_id=metric.zone_id,
        cell_id=metric.cell_id,
        node_id=metric.node_id,
        severity=severity,
        display_label=display_label,
        technical_label=metric.anomaly_type or detector,
        detector=detector,  # type: ignore[arg-type]
        confidence=confidence,
        top_factors=factors,
        metric_correlation_id=metric.correlation_id,
    )


# ── strategies ────────────────────────────────────────────────────────────


def _threshold_alert(m: MetricEvent) -> tuple[bool, Severity, str | None]:
    if m.latency_ms is not None and m.latency_ms >= THRESHOLDS.latency_critical_ms:
        return True, Severity.CRITICAL, "Severe round-trip delay"
    if m.packet_loss_pct is not None and m.packet_loss_pct >= THRESHOLDS.loss_critical_pct:
        return True, Severity.CRITICAL, "Severe packet loss"
    if m.throughput_mbps is not None and m.throughput_mbps < THRESHOLDS.throughput_min_mbps:
        return True, Severity.HIGH, "Throughput collapse"
    if m.jitter_ms is not None and m.jitter_ms >= THRESHOLDS.jitter_critical_ms:
        return True, Severity.HIGH, "Severe delay variation"
    if m.latency_ms is not None and m.latency_ms >= THRESHOLDS.latency_warning_ms:
        return True, Severity.MEDIUM, "Elevated round-trip delay"
    if m.packet_loss_pct is not None and m.packet_loss_pct >= THRESHOLDS.loss_warning_pct:
        return True, Severity.MEDIUM, "Elevated packet loss"
    if m.jitter_ms is not None and m.jitter_ms >= THRESHOLDS.jitter_warning_ms:
        return True, Severity.LOW, "Elevated delay variation"
    return False, Severity.INFO, None


def _behavioral_alert(m: MetricEvent) -> tuple[bool, Severity]:
    score = m.anomaly_score
    if score is None:
        return False, Severity.INFO
    if score >= THRESHOLDS.anomaly_score_critical:
        return True, Severity.HIGH
    if score >= THRESHOLDS.anomaly_score_warning:
        return True, Severity.LOW
    return False, Severity.INFO


# ── helpers ───────────────────────────────────────────────────────────────


_SEVERITY_ORDER = {
    Severity.INFO: 0,
    Severity.LOW: 1,
    Severity.MEDIUM: 2,
    Severity.HIGH: 3,
    Severity.CRITICAL: 4,
}


def _max_severity(a: Severity, b: Severity) -> Severity:
    return a if _SEVERITY_ORDER[a] >= _SEVERITY_ORDER[b] else b


def _confidence(m: MetricEvent, detector: str) -> float:
    score = m.anomaly_score or 0.0
    if detector == "composite":
        return min(0.96, max(0.90, 0.60 + 0.38 * score))
    if detector == "behavioral":
        return min(0.95, max(0.70, score))
    return 0.90  # threshold-only: KPI clearly out of band


def rank_top_factors(m: MetricEvent) -> list[TopFactor]:
    """Build NOC-language ranked factors from the live sample."""
    contributions: list[tuple[float, str, str]] = []
    for field in _FACTOR_FIELDS:
        value = getattr(m, field, None)
        if value is None:
            continue
        impact = _impact_pct(field, float(value))
        if impact <= 0.0:
            continue
        direction = _direction(field, float(value))
        contributions.append((impact, field, direction))

    contributions.sort(reverse=True)
    factors: list[TopFactor] = []
    for impact, field, direction in contributions[:4]:
        factors.append(
            TopFactor(
                display_label=NOC_FACTOR_LABELS.get(field, factor_label(field)),
                impact_pct=round(min(impact, 100.0), 1),
                direction=direction,  # type: ignore[arg-type]
                technical_name=field,
            )
        )
    return factors


def _impact_pct(field: str, value: float) -> float:
    """Real impact score: how far the KPI sits past its warning band."""
    t = THRESHOLDS
    if field == "latency_ms":
        if value <= t.latency_baseline_ms:
            return 0.0
        return min(100.0, (value - t.latency_baseline_ms) / t.latency_baseline_ms * 100.0)
    if field == "jitter_ms":
        if value <= t.jitter_acceptable_ms:
            return 0.0
        return min(100.0, (value - t.jitter_acceptable_ms) / t.jitter_acceptable_ms * 100.0)
    if field == "packet_loss_pct":
        if value <= 0.5:
            return 0.0
        return min(100.0, value / t.loss_critical_pct * 100.0)
    if field == "throughput_mbps":
        if value >= t.throughput_baseline_mbps:
            return 0.0
        return min(100.0, (t.throughput_baseline_mbps - value) / t.throughput_baseline_mbps * 100.0)
    if field == "bler_proxy_pct":
        return min(100.0, value)
    if field == "tcp_retransmit_rate":
        return min(100.0, value * 5.0)
    if field == "cpu_pct":
        return max(0.0, value - 60.0)
    if field == "memory_pct":
        return max(0.0, value - 70.0)
    if field == "rsrp_dbm":
        # weaker signal → higher impact (RSRP is negative)
        if value >= -90:
            return 0.0
        return min(100.0, abs(value + 90) * 5.0)
    if field == "sinr_db":
        if value >= 13:
            return 0.0
        return min(100.0, (13 - value) * 8.0)
    if field == "rssi_dbm":
        if value >= -65:
            return 0.0
        return min(100.0, abs(value + 65) * 4.0)
    return 0.0


def _direction(field: str, value: float) -> str:
    # KPIs where "higher = worse" point up; throughput / signal strength point down.
    if field in ("throughput_mbps", "rsrp_dbm", "rssi_dbm", "sinr_db"):
        return "down"
    return "up"
