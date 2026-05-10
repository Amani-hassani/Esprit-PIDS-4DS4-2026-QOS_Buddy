"""
Forecaster — linear extrapolation on a rolling window to estimate
time-to-breach for each core KPI. Pure stdlib, no numpy.

Emits forecast-flavoured AlertEvents *only* when a breach is projected
within the configurable horizon (default 120 s). The Command Center's
TimeToBreach widget reads from these.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Iterable

from contracts.noc_vocab import NOC_FACTOR_LABELS
from contracts.schemas import AlertEvent, MetricEvent, Severity, TopFactor

from .thresholds import THRESHOLDS

WINDOW_SAMPLES = 24      # ~2 minutes at 5 s interval
MIN_FOR_FIT = 4
HORIZON_SECONDS = 180

# Telco KPIs from a real network are noisy — raw linear regression on
# every sample yields a near-zero slope and almost never forecasts a
# breach. We smooth with an EWMA before fitting so the trend signal
# survives the noise.
EWMA_ALPHA = 0.35

# Proximity warning: if the smoothed value is within this much of the
# breach threshold AND moving toward it, we always emit a forecast even
# when the strict linear ETA would be outside the horizon. Keeps the
# operator informed of "creeping" KPIs.
PROXIMITY_PCT = 0.20


@dataclass
class _Series:
    timestamps: deque[float] = field(default_factory=lambda: deque(maxlen=WINDOW_SAMPLES))
    values: deque[float] = field(default_factory=lambda: deque(maxlen=WINDOW_SAMPLES))
    # Smoothed companion to `values`. Updated alongside each push.
    smoothed: deque[float] = field(default_factory=lambda: deque(maxlen=WINDOW_SAMPLES))

    def push(self, ts: float, value: float) -> None:
        prev = self.smoothed[-1] if self.smoothed else value
        ewma = EWMA_ALPHA * value + (1.0 - EWMA_ALPHA) * prev
        self.timestamps.append(ts)
        self.values.append(value)
        self.smoothed.append(ewma)


class Forecaster:
    def __init__(self) -> None:
        self._series: dict[tuple[str, str], _Series] = {}

    def update_and_forecast(self, metric: MetricEvent) -> AlertEvent | None:
        cell = metric.cell_id or "default"
        ts = metric.occurred_at.timestamp() if metric.occurred_at else 0.0

        breaches: list[tuple[str, float, float, float]] = []  # (field, eta, breach_value, current)
        for field_name, threshold, direction in _MONITORED:
            value = getattr(metric, field_name, None)
            if value is None:
                continue
            key = (cell, field_name)
            series = self._series.setdefault(key, _Series())
            series.push(ts, float(value))

            eta = _time_to_breach(series, threshold, direction)
            if eta is not None and 0 < eta <= HORIZON_SECONDS:
                breaches.append((field_name, eta, threshold, float(value)))

        if not breaches:
            return None

        # Pick the soonest breach as the headline.
        breaches.sort(key=lambda x: x[1])
        field_name, eta_s, breach_value, current = breaches[0]

        return AlertEvent(
            producer="synthesis",
            producer_version="0.1",
            correlation_id=metric.correlation_id,
            causation_id=metric.event_id,
            tenant_id=metric.tenant_id,
            zone_id=metric.zone_id,
            cell_id=metric.cell_id,
            node_id=metric.node_id,
            severity=_eta_to_severity(eta_s),
            display_label=f"Forecast: {NOC_FACTOR_LABELS.get(field_name, field_name)} will breach soon",
            technical_label=f"forecast:{field_name}",
            detector="forecast",
            confidence=_confidence_from_eta(eta_s),
            time_to_breach_seconds=int(eta_s),
            breach_threshold=breach_value,
            breach_metric=field_name,
            top_factors=[
                TopFactor(
                    display_label=NOC_FACTOR_LABELS.get(field_name, field_name),
                    impact_pct=100.0,
                    direction="up" if field_name != "throughput_mbps" else "down",
                    technical_name=field_name,
                )
            ],
            metric_correlation_id=metric.correlation_id,
        )


# ── monitored KPIs and their breach thresholds ────────────────────────────

_MONITORED: tuple[tuple[str, float, str], ...] = (
    ("latency_ms", THRESHOLDS.latency_critical_ms, "above"),
    ("jitter_ms", THRESHOLDS.jitter_critical_ms, "above"),
    ("packet_loss_pct", THRESHOLDS.loss_critical_pct, "above"),
    ("throughput_mbps", THRESHOLDS.throughput_min_mbps, "below"),
    # Behavioural score is included so the forecaster surfaces an alert
    # whenever the system's overall risk indicator is climbing toward the
    # "act" threshold — even when no individual KPI is yet in breach.
    ("anomaly_score", THRESHOLDS.anomaly_score_critical, "above"),
)


def _time_to_breach(series: _Series, threshold: float, direction: str) -> float | None:
    """Return seconds until the smoothed series crosses `threshold`.

    Returns None when there's no actionable forecast (no breach trend,
    not enough samples, or the smoothed value is comfortably away from
    the threshold). Returns a positive ETA in seconds when a breach is
    projected within `HORIZON_SECONDS`, and uses a proximity heuristic
    so a smoothed value that's already drifting close to the threshold
    surfaces as a warning even if linear extrapolation would put the
    breach further out.
    """

    if len(series.smoothed) < MIN_FOR_FIT:
        return None
    slope, intercept = _linfit(series.timestamps, series.smoothed)
    last_ts = series.timestamps[-1]
    last_val = series.smoothed[-1]

    breached_now = (direction == "above" and last_val >= threshold) or (
        direction == "below" and last_val <= threshold
    )
    moving_toward = (direction == "above" and slope > 0) or (
        direction == "below" and slope < 0
    )

    # Already breached on the smoothed series — surface as imminent so the
    # UI shows it under "earliest breach" rather than ignoring it. Most
    # operators expect "0s = right now".
    if breached_now and moving_toward:
        return 1.0

    if not moving_toward or slope == 0 or math.isnan(slope):
        # No trend toward breach. Use proximity as a fallback: if the
        # smoothed value is already within PROXIMITY_PCT of the threshold,
        # emit a soft forecast at the horizon edge.
        gap = abs(threshold - last_val)
        scale = max(abs(threshold), 1e-6)
        if gap / scale <= PROXIMITY_PCT and (
            (direction == "above" and last_val < threshold)
            or (direction == "below" and last_val > threshold)
        ):
            return float(HORIZON_SECONDS)
        return None

    breach_ts = (threshold - intercept) / slope
    eta = breach_ts - last_ts
    if eta <= 0:
        return 1.0
    if eta > HORIZON_SECONDS:
        # Trend points toward breach but ETA is past the horizon. If we
        # are also close to the threshold, still emit at the horizon edge.
        gap = abs(threshold - last_val)
        scale = max(abs(threshold), 1e-6)
        if gap / scale <= PROXIMITY_PCT:
            return float(HORIZON_SECONDS)
        return None
    return eta


def _linfit(xs: Iterable[float], ys: Iterable[float]) -> tuple[float, float]:
    xs_l = list(xs)
    ys_l = list(ys)
    n = len(xs_l)
    if n < 2:
        return 0.0, 0.0
    mean_x = sum(xs_l) / n
    mean_y = sum(ys_l) / n
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs_l, ys_l))
    den = sum((x - mean_x) ** 2 for x in xs_l)
    if den == 0:
        return 0.0, mean_y
    slope = num / den
    intercept = mean_y - slope * mean_x
    return slope, intercept


def _eta_to_severity(eta: float) -> Severity:
    if eta <= 30:
        return Severity.CRITICAL
    if eta <= 60:
        return Severity.HIGH
    if eta <= 120:
        return Severity.MEDIUM
    return Severity.LOW


def _confidence_from_eta(eta: float) -> float:
    # Closer breach → higher confidence (more samples agree).
    if eta <= 30:
        return 0.9
    if eta <= 60:
        return 0.75
    return 0.6
