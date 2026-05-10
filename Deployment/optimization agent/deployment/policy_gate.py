from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone

from .contracts import (
    Decision,
    ImpactRadius,
    PolicyDecision,
    PolicyRequest,
    RiskLevel,
    ValidatorResult,
)


@dataclass(frozen=True)
class GateConfig:
    auto_risk_levels: tuple[RiskLevel, ...] = (RiskLevel.LOW,)
    auto_impacts: tuple[ImpactRadius, ...] = (ImpactRadius.LOCAL, ImpactRadius.SECTOR)
    repeat_guard_minutes: int = 30
    maintenance_days_utc: tuple[int, ...] = (5, 6)
    maintenance_start_utc: time = time(2, 0)
    maintenance_end_utc: time = time(6, 0)
    resource_limits_enabled: bool = False


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def risk_threshold(req: PolicyRequest, cfg: GateConfig) -> ValidatorResult:
    passed = req.risk_level in cfg.auto_risk_levels or req.human_approved
    reason = (
        f"{req.risk_level.value} risk is auto-eligible"
        if passed
        else f"{req.risk_level.value} risk needs NOC approval"
    )
    return ValidatorResult("risk_threshold", passed, reason, Decision.PENDING_APPROVAL)


def impact_radius(req: PolicyRequest, cfg: GateConfig) -> ValidatorResult:
    passed = req.estimated_impact in cfg.auto_impacts
    reason = (
        f"{req.estimated_impact.value} impact is inside auto radius"
        if passed
        else f"{req.estimated_impact.value} impact exceeds local/sector radius"
    )
    return ValidatorResult("impact_radius", passed, reason, Decision.REJECTED)


def rollback_available(req: PolicyRequest, cfg: GateConfig) -> ValidatorResult:
    passed = bool(req.is_reversible and req.rollback_available)
    reason = "rollback path is available" if passed else "irreversible or rollback unavailable"
    return ValidatorResult("rollback_available", passed, reason, Decision.REJECTED)


def change_window(req: PolicyRequest, cfg: GateConfig) -> ValidatorResult:
    now = _as_utc(req.current_time)
    in_window = (
        now.weekday() in cfg.maintenance_days_utc
        and cfg.maintenance_start_utc <= now.time() < cfg.maintenance_end_utc
    )
    reason = (
        "inside maintenance window; defer for automatic retry"
        if in_window
        else "outside maintenance window"
    )
    return ValidatorResult("change_window", not in_window, reason, Decision.DEFERRED)


def not_repeat_action(req: PolicyRequest, cfg: GateConfig) -> ValidatorResult:
    now = _as_utc(req.current_time)
    horizon = now - timedelta(minutes=cfg.repeat_guard_minutes)
    for item in req.action_history:
        ts = _as_utc(item.timestamp)
        if item.cell_id == req.cell_id and item.action_code == req.action_code and ts >= horizon:
            return ValidatorResult(
                "not_repeat_action",
                False,
                f"{req.action_code} already applied to {req.cell_id} within {cfg.repeat_guard_minutes} min",
                Decision.REJECTED,
            )
    return ValidatorResult("not_repeat_action", True, "no recent duplicate action for this cell", Decision.REJECTED)


def resource_limits(req: PolicyRequest, cfg: GateConfig) -> ValidatorResult:
    if not cfg.resource_limits_enabled:
        return ValidatorResult(
            "resource_limits",
            True,
            "Phase 3 stub: live network resource limits not enabled",
            Decision.REJECTED,
        )
    return ValidatorResult("resource_limits", True, "resource capacity accepted", Decision.REJECTED)


VALIDATORS = (
    risk_threshold,
    impact_radius,
    rollback_available,
    change_window,
    not_repeat_action,
    resource_limits,
)


def evaluate_policy(req: PolicyRequest, cfg: GateConfig | None = None) -> PolicyDecision:
    cfg = cfg or GateConfig()
    results = [validator(req, cfg) for validator in VALIDATORS]
    failures = [result for result in results if not result.passed]
    if req.requires_human and not req.human_approved:
        failures.insert(
            0,
            ValidatorResult(
                "requires_human",
                False,
                "action contract requires NOC approval",
                Decision.PENDING_APPROVAL,
            ),
        )
    if not failures:
        decision = Decision.APPROVED
        reason = "Auto-execute approved: low risk, reversible, bounded impact, no duplicate, no maintenance conflict."
    elif any(f.failure_decision == Decision.REJECTED for f in failures):
        first = next(f for f in failures if f.failure_decision == Decision.REJECTED)
        decision = Decision.REJECTED
        reason = first.reason
    elif any(f.failure_decision == Decision.DEFERRED for f in failures):
        first = next(f for f in failures if f.failure_decision == Decision.DEFERRED)
        decision = Decision.DEFERRED
        reason = first.reason
    else:
        first = failures[0]
        decision = Decision.PENDING_APPROVAL
        reason = first.reason
    return PolicyDecision(decision=decision, reason=reason, validators=results, request=req)

