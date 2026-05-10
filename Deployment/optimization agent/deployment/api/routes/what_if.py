from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

import pandas as pd
import redis.asyncio as redis
from fastapi import APIRouter
from pydantic import BaseModel, Field

from ...contracts import ACTION_CONTRACTS, ACTION_COST, action_contract
from ...simulation import ACTION_EFFECTS, health_score, simulate_action


router = APIRouter(prefix="/api", tags=["what-if"])

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
METRIC_STREAM = os.getenv("QOS_METRIC_STREAM", "qos.metrics.raw")
ACTION_PROPOSED_STREAM = os.getenv("QOS_ACTION_PROPOSED_STREAM", "qos.action.proposed")
ACTION_EXECUTED_STREAM = os.getenv("QOS_ACTION_EXECUTED_STREAM", "qos.action.executed")
HORIZON_SECONDS = 300
STEP_SECONDS = 30

ACTION_LABELS = {
    "ACT_ALERT_COVERAGE_HOLE": "Create coverage investigation ticket",
    "ACT_LOADBALANCE_FREQ_BAND": "Rebalance traffic across frequency bands",
    "ACT_OPTIMIZE_HO_PARAMS": "Tune handover settings",
    "ACT_TRIGGER_CA": "Stage carrier aggregation change",
    "ACT_REDUCE_BUFFER_SIZE": "Reduce transport buffer size",
    "ACT_PRIORITY_VOLTE_SCHEDULING": "Prioritize voice scheduling",
    "ACT_RECOMMEND_SITE_ADDITION": "Recommend capacity planning case",
}

HIGHER_IS_BETTER = {
    "throughput_mbps",
    "mos_estimate",
    "sinr_db",
    "rssi_dbm",
    "ho_success_rate_pct",
    "cssr_proxy_pct",
}

BOUNDS = {
    "latency_ms": (0.0, 500.0),
    "jitter_ms": (0.0, 200.0),
    "packet_loss_pct": (0.0, 100.0),
    "throughput_mbps": (0.0, 1000.0),
    "cpu_pct": (0.0, 100.0),
    "memory_pct": (0.0, 100.0),
    "bandwidth_util_pct": (0.0, 100.0),
    "bler_proxy_pct": (0.0, 100.0),
    "queue_length": (0.0, 10000.0),
    "anomaly_score": (0.0, 1.0),
}


class WhatIfRequest(BaseModel):
    kpi_overrides: dict[str, float] = Field(default_factory=dict)
    cell_id: str | None = None


@dataclass(frozen=True)
class ArmScore:
    action_code: str
    display_label: str
    confidence: float
    projected_improvement: float
    breach_risk_after: float
    rollback_risk: float
    safety_pass: bool
    target_metric: str


@router.post("/what-if")
async def what_if(body: WhatIfRequest) -> dict[str, Any]:
    recent = await _read_recent_metrics(body.cell_id, limit=10)
    synthetic = _build_synthetic_metric(body.kpi_overrides, recent, body.cell_id)
    row = pd.Series(synthetic)
    target_metric = _select_projection_metric(body.kpi_overrides, synthetic)

    arm_scores = _score_all_arms(row, target_metric)
    results: list[dict[str, Any]] = []
    for arm in arm_scores[:3]:
        results.append(
            {
                "action_label": arm.display_label,
                "confidence": arm.confidence,
                "projected_improvement": arm.projected_improvement,
                "breach_risk_after": arm.breach_risk_after,
                "safety_pass": arm.safety_pass,
                "time_series_no_action": _generate_projection(
                    synthetic,
                    recent,
                    target_metric,
                    action_code=None,
                    horizon_seconds=HORIZON_SECONDS,
                ),
                "time_series_with_action": _generate_projection(
                    synthetic,
                    recent,
                    target_metric,
                    action_code=arm.action_code,
                    horizon_seconds=HORIZON_SECONDS,
                ),
            }
        )
    return {"arms": results, "baseline_kpis": body.kpi_overrides}


@router.get("/optimization/arm-stats")
async def arm_stats() -> dict[str, Any]:
    proposed = await _read_stream_json(ACTION_PROPOSED_STREAM, count=500)
    executed = await _read_stream_json(ACTION_EXECUTED_STREAM, count=500)
    rows: list[dict[str, Any]] = []
    for action_code in ACTION_EFFECTS:
        if action_code == "ACT_NO_OP":
            continue
        label = ACTION_LABELS.get(action_code, action_code.replace("ACT_", "").replace("_", " ").title())
        pulls = [event for event in proposed if _matches_action(event, action_code, label)]
        wins = [event for event in executed if _matches_action(event, action_code, label) and bool(event.get("success"))]
        executions = [event for event in executed if _matches_action(event, action_code, label)]
        last_execution_time = None
        if executions:
            last_execution_time = max(
                str(event.get("occurred_at") or event.get("published_at") or "")
                for event in executions
            )
        rows.append(
            {
                "action_code": action_code,
                "action_label": label,
                "pull_count": len(pulls),
                "win_rate": round(len(wins) / len(executions), 3) if executions else 0.0,
                "last_execution_time": last_execution_time,
            }
        )
    return {"arms": rows}


async def _read_recent_metrics(cell_id: str | None, limit: int) -> list[dict[str, Any]]:
    client = redis.from_url(REDIS_URL, decode_responses=True)
    try:
        rows = await client.xrevrange(METRIC_STREAM, count=max(limit * 4, limit))
    finally:
        await client.aclose()

    metrics: list[dict[str, Any]] = []
    for _message_id, fields in rows:
        raw = fields.get("json")
        if not raw:
            continue
        try:
            metric = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if cell_id and metric.get("cell_id") != cell_id:
            continue
        metrics.append(metric)
        if len(metrics) >= limit:
            break
    metrics.reverse()
    return metrics


async def _read_stream_json(stream_name: str, count: int) -> list[dict[str, Any]]:
    client = redis.from_url(REDIS_URL, decode_responses=True)
    try:
        rows = await client.xrevrange(stream_name, count=count)
    finally:
        await client.aclose()
    events: list[dict[str, Any]] = []
    for _message_id, fields in rows:
        raw = fields.get("json")
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            events.append(payload)
    return events


def _matches_action(event: dict[str, Any], action_code: str, label: str) -> bool:
    candidates = {
        str(event.get("action_code") or ""),
        str(event.get("action_id") or ""),
        str(event.get("title") or ""),
        str(event.get("display_label") or ""),
        str(event.get("action_label") or ""),
    }
    return action_code in candidates or label in candidates


def _build_synthetic_metric(
    overrides: dict[str, float],
    recent: list[dict[str, Any]],
    cell_id: str | None,
) -> dict[str, Any]:
    base = dict(recent[-1]) if recent else {}
    base.setdefault("cell_id", cell_id or "synthetic")
    defaults = {
        "latency_ms": 40.0,
        "jitter_ms": 5.0,
        "packet_loss_pct": 0.2,
        "throughput_mbps": 80.0,
        "cpu_pct": 35.0,
        "memory_pct": 45.0,
        "bandwidth_util_pct": 55.0,
        "queue_length": 40.0,
        "sinr_db": 10.0,
        "rssi_dbm": -85.0,
        "bler_proxy_pct": 5.0,
        "ho_success_rate_pct": 95.0,
        "anomaly_score": 0.1,
    }
    for key, value in defaults.items():
        base.setdefault(key, value)
    for key, value in overrides.items():
        base[key] = float(value)
    return base


def _score_all_arms(row: pd.Series, target_metric: str) -> list[ArmScore]:
    scored: list[ArmScore] = []
    for action_code in ACTION_EFFECTS:
        if action_code == "ACT_NO_OP":
            continue
        try:
            contract = action_contract(action_code)
        except KeyError:
            continue
        sim = simulate_action(row, action_code)
        delta = max(0.0, float(sim["delta_health_score"]))
        after_health = float(sim["after_health_score"])
        rollback_risk = _rollback_risk(action_code)
        safety_pass = bool(contract.is_reversible and rollback_risk <= 0.65)
        risk_after = round(max(0.0, min(1.0, 1.0 - after_health / 100.0)), 3)
        confidence = round(max(0.05, min(0.98, 0.45 + (delta / 35.0) - ACTION_COST.get(action_code, 0.0) * 0.2)), 3)
        scored.append(
            ArmScore(
                action_code=action_code,
                display_label=ACTION_LABELS.get(action_code, action_code.replace("ACT_", "").replace("_", " ").title()),
                confidence=confidence,
                projected_improvement=round(delta, 2),
                breach_risk_after=risk_after,
                rollback_risk=rollback_risk,
                safety_pass=safety_pass,
                target_metric=target_metric,
            )
        )
    return sorted(scored, key=lambda arm: (arm.safety_pass, arm.projected_improvement, arm.confidence), reverse=True)


def _rollback_risk(action_code: str) -> float:
    contract = ACTION_CONTRACTS[action_code]
    base = {
        "low": 0.15,
        "medium": 0.35,
        "high": 0.6,
        "critical": 0.9,
    }.get(contract.risk_level.value, 0.5)
    if not contract.is_reversible:
        base += 0.2
    if contract.requires_human:
        base += 0.1
    return round(min(1.0, base), 3)


def _select_projection_metric(overrides: dict[str, float], synthetic: dict[str, Any]) -> str:
    for preferred in ("packet_loss_pct", "latency_ms", "jitter_ms", "throughput_mbps"):
        if preferred in overrides:
            return preferred
    worst_key = "packet_loss_pct"
    worst_score = -1.0
    for key, value in synthetic.items():
        if not isinstance(value, (int, float)):
            continue
        score = _metric_stress(key, float(value))
        if score > worst_score:
            worst_score = score
            worst_key = key
    return worst_key


def _metric_stress(key: str, value: float) -> float:
    if key in HIGHER_IS_BETTER:
        target = 50.0 if key == "throughput_mbps" else 10.0
        return max(0.0, min(1.0, (target - value) / max(target, 1.0)))
    if key == "packet_loss_pct":
        return min(1.0, value / 3.0)
    if key == "latency_ms":
        return min(1.0, value / 150.0)
    if key == "jitter_ms":
        return min(1.0, value / 50.0)
    if key in {"cpu_pct", "memory_pct", "bandwidth_util_pct"}:
        return min(1.0, value / 90.0)
    if key == "queue_length":
        return min(1.0, value / 120.0)
    return 0.0


def _generate_projection(
    synthetic: dict[str, Any],
    recent: list[dict[str, Any]],
    metric: str,
    *,
    action_code: str | None,
    horizon_seconds: int,
) -> list[dict[str, float]]:
    current = _as_float(synthetic.get(metric), 0.0)
    slope = _metric_slope(recent, metric)
    action_delta = 0.0
    if action_code:
        sim = simulate_action(pd.Series(synthetic), action_code)
        changed = sim.get("changed_kpis", {})
        if metric in changed:
            action_delta = _as_float(changed[metric].get("after"), current) - current
        else:
            action_delta = _health_delta_to_metric_delta(metric, float(sim["delta_health_score"]), current)

    points: list[dict[str, float]] = []
    for t in range(0, horizon_seconds + STEP_SECONDS, STEP_SECONDS):
        trend_value = current + slope * (t / STEP_SECONDS)
        action_value = action_delta * (t / max(horizon_seconds, STEP_SECONDS))
        points.append({"t": t, "value": round(_clamp_metric(metric, trend_value + action_value), 3)})
    return points


def _metric_slope(recent: list[dict[str, Any]], metric: str) -> float:
    values = [_as_float(row.get(metric), None) for row in recent]
    series = [v for v in values if v is not None]
    if len(series) < 2:
        return 0.0
    n = len(series)
    sum_x = n * (n - 1) / 2
    sum_x2 = (n - 1) * n * (2 * n - 1) / 6
    sum_y = sum(series)
    sum_xy = sum(i * y for i, y in enumerate(series))
    denom = n * sum_x2 - sum_x * sum_x
    if denom == 0:
        return 0.0
    return (n * sum_xy - sum_x * sum_y) / denom


def _health_delta_to_metric_delta(metric: str, health_delta: float, current: float) -> float:
    magnitude = abs(current) * min(0.25, max(0.0, health_delta / 100.0))
    if metric in HIGHER_IS_BETTER:
        return magnitude
    return -magnitude


def _clamp_metric(metric: str, value: float) -> float:
    lo, hi = BOUNDS.get(metric, (0.0, None))
    value = max(lo, value)
    if hi is not None:
        value = min(hi, value)
    return value


def _as_float(value: Any, default: float | None) -> float | None:
    try:
        if value is None or pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default
