"""
Scenario Lab — chaos injection endpoint for the demo.

Publishes synthetic MetricEvents into qos.metrics.raw for a short burst so
the rest of the pipeline (synthesis → alerts → diagnosis → actions) reacts
naturally end-to-end. No real network is touched. Each injection is audited.

Only SITE_ADMIN and AI_ENGINEER roles can inject — NOC roles are read-only.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from bus.redis_streams import RedisStreamsBus
from contracts.schemas import AuthLevel, MetricEvent, Role, StreamName

from .actions import _chain  # reuse the same hash chain
from .auth import Principal

log = logging.getLogger("qos.gateway.chaos")

CHAOS_ENABLED = os.getenv("QOS_CHAOS_ENABLED", "false").lower() == "true"
_INJECTOR_ROLES = (Role.SITE_ADMIN, Role.AI_ENGINEER)
_DEFAULT_CELL = "C1"
_TICK_HZ = 1.0  # 1 sample per second
_MAX_DURATION_S = 60
_MIN_DURATION_S = 5

ScenarioName = Literal[
    "latency_storm",
    "jitter_surge",
    "packet_loss",
    "cpu_saturation",
    "throughput_collapse",
    "bgp_flap",
]


# ─── scenarios ────────────────────────────────────────────────────────────


def _scenario_sample(name: ScenarioName, t_pct: float) -> dict[str, Any]:
    """Return one synthetic MetricEvent payload for the given scenario.

    `t_pct` is 0..1 progress through the burst — most scenarios ramp.
    """
    # baseline healthy values; scenario overrides specific fields
    base: dict[str, Any] = {
        "latency_ms": 28.0 + random.uniform(-2, 2),
        "jitter_ms": 4.0 + random.uniform(-1, 1),
        "packet_loss_pct": 0.05 + random.uniform(0, 0.05),
        "throughput_mbps": 320.0 + random.uniform(-10, 10),
        "mos_estimate": 4.3,
        "bler_proxy_pct": 0.5,
        "tcp_retransmit_rate": 0.2,
        "anomaly_score": 0.05,
        "anomaly_flag": False,
        "cpu_pct": 35.0 + random.uniform(-3, 3),
        "memory_pct": 52.0,
        "active_connections": 1450,
    }

    # ramp factor 0.3 → 1.0 across the burst so the alert ladder triggers
    ramp = 0.3 + 0.7 * t_pct

    if name == "latency_storm":
        base["latency_ms"] = 28.0 + 220.0 * ramp + random.uniform(-5, 5)
        base["mos_estimate"] = max(1.5, 4.3 - 2.5 * ramp)
        base["anomaly_score"] = min(1.0, 0.2 + 0.7 * ramp)
        base["anomaly_flag"] = ramp > 0.5
        base["anomaly_type"] = "latency_storm"
    elif name == "jitter_surge":
        base["jitter_ms"] = 4.0 + 60.0 * ramp + random.uniform(-2, 2)
        base["mos_estimate"] = max(1.8, 4.3 - 2.0 * ramp)
        base["anomaly_score"] = min(1.0, 0.2 + 0.6 * ramp)
        base["anomaly_flag"] = ramp > 0.5
        base["anomaly_type"] = "jitter_surge"
    elif name == "packet_loss":
        base["packet_loss_pct"] = 0.05 + 8.0 * ramp + random.uniform(0, 0.5)
        base["bler_proxy_pct"] = 0.5 + 9.0 * ramp
        base["tcp_retransmit_rate"] = 0.2 + 5.0 * ramp
        base["anomaly_score"] = min(1.0, 0.25 + 0.7 * ramp)
        base["anomaly_flag"] = ramp > 0.4
        base["anomaly_type"] = "packet_loss_spike"
    elif name == "cpu_saturation":
        base["cpu_pct"] = 35.0 + 60.0 * ramp + random.uniform(-2, 2)
        base["memory_pct"] = 52.0 + 35.0 * ramp
        base["anomaly_score"] = min(1.0, 0.15 + 0.7 * ramp)
        base["anomaly_flag"] = ramp > 0.6
        base["anomaly_type"] = "host_saturation"
    elif name == "throughput_collapse":
        base["throughput_mbps"] = max(5.0, 320.0 - 300.0 * ramp + random.uniform(-5, 5))
        base["anomaly_score"] = min(1.0, 0.2 + 0.7 * ramp)
        base["anomaly_flag"] = ramp > 0.5
        base["anomaly_type"] = "throughput_collapse"
    elif name == "bgp_flap":
        # simulates intermittent connectivity — alternating values
        flapping = (random.random() < 0.4)
        base["packet_loss_pct"] = 12.0 if flapping else 0.1
        base["latency_ms"] = 350.0 if flapping else 35.0
        base["throughput_mbps"] = 30.0 if flapping else 280.0
        base["anomaly_score"] = 0.85 if flapping else 0.25
        base["anomaly_flag"] = flapping
        base["anomaly_type"] = "bgp_flap"

    return base


# ─── request / response ──────────────────────────────────────────────────


class InjectBody(BaseModel):
    scenario: ScenarioName
    cell_id: str = _DEFAULT_CELL
    duration_seconds: int = Field(default=20, ge=_MIN_DURATION_S, le=_MAX_DURATION_S)


class InjectResult(BaseModel):
    scenario: ScenarioName
    cell_id: str
    duration_seconds: int
    samples_published: int
    started_at: str
    audit_hash: str


# ─── runtime ─────────────────────────────────────────────────────────────


class _ChaosRunner:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._active_until: float = 0.0

    async def is_busy(self) -> bool:
        return asyncio.get_event_loop().time() < self._active_until

    async def run(
        self,
        bus: RedisStreamsBus,
        scenario: ScenarioName,
        cell_id: str,
        duration_seconds: int,
    ) -> int:
        async with self._lock:
            self._active_until = (
                asyncio.get_event_loop().time() + duration_seconds + 2
            )
        ticks = int(duration_seconds * _TICK_HZ)
        published = 0
        for i in range(ticks):
            t_pct = i / max(1, ticks - 1)
            payload = _scenario_sample(scenario, t_pct)
            event = MetricEvent(
                producer="chaos-injector",
                producer_version="0.1",
                correlation_id=f"corr-chaos-{int(asyncio.get_event_loop().time())}",
                cell_id=cell_id,
                zone_id="Z1",
                node_id="N1",
                data_source="chaos",
                data_quality_rating="synthetic",
                device_type="simulated",
                extra={"scenario": scenario, "synthetic": True},
                **payload,
            )
            await bus.publish(StreamName.METRICS_RAW, event)
            published += 1
            await asyncio.sleep(1.0 / _TICK_HZ)
        return published


_runner = _ChaosRunner()


# ─── endpoint ────────────────────────────────────────────────────────────


def register(app, get_principal) -> None:  # type: ignore[no-untyped-def]
    """Mount /api/chaos/inject on the FastAPI app."""

    @app.post("/api/chaos/inject", response_model=InjectResult)
    async def inject(  # noqa: D401
        body: InjectBody,
        request: Request,
        principal: Principal = Depends(get_principal),
    ) -> InjectResult:
        if not CHAOS_ENABLED:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "scenario injection is disabled; set QOS_CHAOS_ENABLED=true to allow synthetic test traffic",
            )
        if principal.role not in _INJECTOR_ROLES:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "role cannot inject scenarios"
            )
        if await _runner.is_busy():
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "another scenario is already running",
            )

        bus: RedisStreamsBus = request.app.state.bus

        # audit BEFORE running so the operator's intent is captured even if
        # the injection itself errors mid-stream
        audit = await _chain.append(
            actor=principal.username,
            actor_role=principal.role,
            action=f"chaos.inject.{body.scenario}",
            target_id=body.cell_id,
            succeeded=True,
            auth_level=AuthLevel.WEBAUTHN,
            correlation_id=None,
            causation_id=None,
            cell_id=body.cell_id,
        )
        await bus.publish(StreamName.AUDIT, audit)

        started_at = datetime.now(timezone.utc).isoformat()
        # run inline so the response only returns when the burst is done;
        # client renders a progress bar against duration_seconds while it waits
        published = await _runner.run(
            bus, body.scenario, body.cell_id, body.duration_seconds
        )

        log.info(
            "chaos injection complete actor=%s scenario=%s cell=%s samples=%d",
            principal.username,
            body.scenario,
            body.cell_id,
            published,
        )

        return InjectResult(
            scenario=body.scenario,
            cell_id=body.cell_id,
            duration_seconds=body.duration_seconds,
            samples_published=published,
            started_at=started_at,
            audit_hash=audit.hash,
        )
