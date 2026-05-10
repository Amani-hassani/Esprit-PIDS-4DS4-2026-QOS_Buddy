from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any

from .core.settings import get_settings


class Decision(str, Enum):
    APPROVED = "APPROVED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    REJECTED = "REJECTED"
    DEFERRED = "DEFERRED"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ImpactRadius(str, Enum):
    LOCAL = "local"
    SECTOR = "sector"
    SITE = "site"
    REGIONAL = "regional"


@dataclass(frozen=True)
class ActionSpec:
    root_cause: str
    action_code: str
    risk_level: RiskLevel
    autonomy: str
    reason: str
    is_reversible: bool
    estimated_impact: ImpactRadius
    requires_human: bool = False


@dataclass(frozen=True)
class ActionContract:
    action_code: str
    risk_level: RiskLevel
    autonomy: str
    reason: str
    is_reversible: bool
    estimated_impact: ImpactRadius
    requires_human: bool = False


def _contracts_path() -> Path:
    return get_settings().paths.action_contracts


@lru_cache(maxsize=1)
def _load_contract_payload() -> dict[str, Any]:
    with _contracts_path().open("r", encoding="utf-8") as fh:
        payload = json.load(fh)
    if not isinstance(payload, dict):
        raise ValueError("action contracts payload must be an object")
    return payload


@lru_cache(maxsize=1)
def _load_action_specs() -> dict[str, ActionSpec]:
    payload = _load_contract_payload()
    root_causes = payload.get("root_causes") or {}
    specs: dict[str, ActionSpec] = {}
    for root_cause, raw in root_causes.items():
        specs[str(root_cause)] = ActionSpec(
            root_cause=str(root_cause),
            action_code=str(raw["action_code"]),
            risk_level=RiskLevel(str(raw["risk_level"])),
            autonomy=str(raw["autonomy"]),
            reason=str(raw["reason"]),
            is_reversible=bool(raw["is_reversible"]),
            estimated_impact=ImpactRadius(str(raw["estimated_impact"])),
            requires_human=bool(raw.get("requires_human", False)),
        )
    if "RC_NONE" not in specs:
        raise ValueError("action contracts must define RC_NONE")
    return specs


@lru_cache(maxsize=1)
def _load_action_metadata() -> dict[str, dict[str, Any]]:
    payload = _load_contract_payload()
    metadata = payload.get("actions") or {}
    if not isinstance(metadata, dict):
        raise ValueError("actions metadata must be an object")
    return {str(action): dict(values or {}) for action, values in metadata.items()}


def _max_risk(levels: list[RiskLevel]) -> RiskLevel:
    order = {
        RiskLevel.LOW: 0,
        RiskLevel.MEDIUM: 1,
        RiskLevel.HIGH: 2,
        RiskLevel.CRITICAL: 3,
    }
    return max(levels, key=lambda level: order[level])


def _max_impact(levels: list[ImpactRadius]) -> ImpactRadius:
    order = {
        ImpactRadius.LOCAL: 0,
        ImpactRadius.SECTOR: 1,
        ImpactRadius.SITE: 2,
        ImpactRadius.REGIONAL: 3,
    }
    return max(levels, key=lambda level: order[level])


@lru_cache(maxsize=1)
def _load_action_contracts() -> dict[str, ActionContract]:
    metadata = _load_action_metadata()
    root_specs = _load_action_specs()
    by_action: dict[str, list[ActionSpec]] = {}
    for spec in root_specs.values():
        by_action.setdefault(spec.action_code, []).append(spec)

    contracts: dict[str, ActionContract] = {}
    for action_code, values in metadata.items():
        explicit_fields = (
            "risk_level",
            "autonomy",
            "reason",
            "is_reversible",
            "estimated_impact",
            "requires_human",
        )
        if all(field in values for field in explicit_fields):
            contracts[action_code] = ActionContract(
                action_code=action_code,
                risk_level=RiskLevel(str(values["risk_level"])),
                autonomy=str(values["autonomy"]),
                reason=str(values["reason"]),
                is_reversible=bool(values["is_reversible"]),
                estimated_impact=ImpactRadius(str(values["estimated_impact"])),
                requires_human=bool(values.get("requires_human", False)),
            )
            continue

        related = by_action.get(action_code, [])
        if not related:
            raise ValueError(f"action {action_code} has metadata but no root-cause mapping")
        contracts[action_code] = ActionContract(
            action_code=action_code,
            risk_level=_max_risk([spec.risk_level for spec in related]),
            autonomy=sorted(str(spec.autonomy) for spec in related)[0],
            reason=str(related[0].reason),
            is_reversible=all(spec.is_reversible for spec in related),
            estimated_impact=_max_impact([spec.estimated_impact for spec in related]),
            requires_human=any(spec.requires_human for spec in related),
        )
    return contracts


PHASE3_ACTIONS: dict[str, ActionSpec] = _load_action_specs()
ACTION_TOOLS: dict[str, str] = {
    action: str(values.get("tool_name") or "observe_kpi_stream")
    for action, values in _load_action_metadata().items()
}
ACTION_COST: dict[str, float] = {
    action: float(values.get("action_cost", 0.25))
    for action, values in _load_action_metadata().items()
}
ACTION_CONTRACTS: dict[str, ActionContract] = _load_action_contracts()


def action_contract(action_code: str) -> ActionContract:
    try:
        return ACTION_CONTRACTS[action_code]
    except KeyError as exc:
        raise KeyError(f"unknown action contract for {action_code}") from exc


def action_catalog() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for root_cause, spec in PHASE3_ACTIONS.items():
        contract = action_contract(spec.action_code)
        out.append(
            {
                "root_cause": root_cause,
                "action_code": spec.action_code,
                "tool_name": ACTION_TOOLS.get(spec.action_code),
                "risk_level": contract.risk_level.value,
                "autonomy": contract.autonomy,
                "reason": contract.reason,
                "is_reversible": contract.is_reversible,
                "estimated_impact": contract.estimated_impact.value,
                "requires_human": contract.requires_human,
                "action_cost": ACTION_COST.get(spec.action_code),
            }
        )
    return out

@dataclass
class ActionHistoryEntry:
    cell_id: str
    action_code: str
    timestamp: datetime
    decision: Decision


@dataclass
class PolicyRequest:
    root_cause: str
    action_code: str
    risk_level: RiskLevel
    is_reversible: bool
    estimated_impact: ImpactRadius
    current_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    action_history: list[ActionHistoryEntry] = field(default_factory=list)
    human_approved: bool = False
    cell_id: str = "unknown"
    requires_human: bool = False
    rollback_available: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ValidatorResult:
    name: str
    passed: bool
    reason: str
    failure_decision: Decision


@dataclass
class PolicyDecision:
    decision: Decision
    reason: str
    validators: list[ValidatorResult]
    request: PolicyRequest
    logged_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
