"""
Diagnoser — pattern label + nearest-neighbour similar-incident lookup
on a rolling history of resolved alerts. Cosine-distance over a small
fixed feature vector — pure stdlib.

The "lessons library" is a built-in seed set so the demo always has
plausible historical matches even on the very first alert. As the agent
runs, freshly resolved alerts get appended to the live history and
become candidates for future matches.
"""

from __future__ import annotations

import math
from collections import deque
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from contracts.schemas import (
    AlertEvent,
    DiagnosisEvent,
    MetricEvent,
    SimilarIncident,
)

# ── feature vector layout (fixed order) ───────────────────────────────────

_FEATURES: tuple[str, ...] = (
    "latency_ms",
    "jitter_ms",
    "packet_loss_pct",
    "throughput_mbps",
    "anomaly_score",
)

# Used to scale features so cosine distance treats them comparably.
_SCALE: dict[str, float] = {
    "latency_ms": 250.0,
    "jitter_ms": 150.0,
    "packet_loss_pct": 10.0,
    "throughput_mbps": 15.0,
    "anomaly_score": 1.0,
}


# ── seed lesson library (NOC-language only) ───────────────────────────────

_SEED_LESSONS: list[tuple[list[float], dict[str, Any]]] = [
    # vector,                                 lesson
    (
        [220.0, 30.0, 1.5, 4.5, 0.6],
        {
            "summary": "Round-trip delay spiked on the upstream path during peak hours.",
            "resolution": "Re-prioritised voice traffic; backbone congestion cleared in 4 minutes.",
            "pattern_label": "Backbone congestion pattern",
        },
    ),
    (
        [80.0, 100.0, 8.0, 2.0, 0.7],
        {
            "summary": "Severe delay variation with packet loss — buffer pressure on the cell.",
            "resolution": "Scaled queue depth; throughput recovered within 6 minutes.",
            "pattern_label": "Buffer pressure cluster",
        },
    ),
    (
        [60.0, 20.0, 0.5, 0.3, 0.9],
        {
            "summary": "Throughput collapsed despite normal delay — backhaul link degradation.",
            "resolution": "Failed over to secondary backhaul; full throughput restored.",
            "pattern_label": "Backhaul degradation",
        },
    ),
    (
        [180.0, 60.0, 12.0, 1.2, 0.85],
        {
            "summary": "Multi-KPI degradation matching a radio-side issue.",
            "resolution": "Adjusted neighbour list and RACH parameters; service stabilised.",
            "pattern_label": "Radio-side degradation",
        },
    ),
    (
        [40.0, 8.0, 0.0, 6.0, 0.5],
        {
            "summary": "Rising signal-quality dispersion ahead of evening peak.",
            "resolution": "Pre-emptively shifted traffic to neighbouring cell.",
            "pattern_label": "Pre-peak warning",
        },
    ),
]


class Diagnoser:
    def __init__(self) -> None:
        # rolling live memory of (vector, lesson)
        self._history: deque[tuple[list[float], dict[str, Any]]] = deque(maxlen=200)
        for v, lesson in _SEED_LESSONS:
            self._history.append((v, lesson))

    def diagnose(self, alert: AlertEvent, metric: MetricEvent) -> DiagnosisEvent:
        vector = _vectorize(metric)
        scored = [
            (_cosine_similarity(vector, past_vec), lesson)
            for past_vec, lesson in self._history
        ]
        scored.sort(key=lambda x: x[0], reverse=True)

        top = scored[:3]
        similar = [
            SimilarIncident(
                incident_id=f"inc-{uuid4().hex[:8]}",
                similarity_pct=round(max(0.0, score) * 100.0, 1),
                summary=lesson["summary"],
                resolution=lesson["resolution"],
                occurred_at=None,
            )
            for score, lesson in top
        ]
        pattern = top[0][1] if top else {"pattern_label": "Unmatched pattern"}

        # Append this fresh case so future incidents can learn from it.
        # We don't yet know the resolution; placeholder updated when an action executes.
        self._history.append(
            (
                vector,
                {
                    "summary": alert.display_label,
                    "resolution": "Pending",
                    "pattern_label": pattern["pattern_label"],
                },
            )
        )

        return DiagnosisEvent(
            producer="synthesis",
            producer_version="0.1",
            correlation_id=alert.correlation_id,
            causation_id=alert.event_id,
            tenant_id=alert.tenant_id,
            zone_id=alert.zone_id,
            cell_id=alert.cell_id,
            node_id=alert.node_id,
            alert_id=alert.event_id,
            pattern_id=pattern.get("pattern_label", "unknown").lower().replace(" ", "_"),
            pattern_label=pattern.get("pattern_label", "Unmatched pattern"),
            similar_incidents=similar,
            log_window_seconds=60,
        )


def _vectorize(m: MetricEvent) -> list[float]:
    out: list[float] = []
    for f in _FEATURES:
        v = getattr(m, f, None)
        if v is None:
            out.append(0.0)
            continue
        out.append(float(v) / _SCALE[f])
    return out


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)
