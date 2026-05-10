from __future__ import annotations

from copy import deepcopy
from typing import Any

from .data import latest_cell_row, latest_cell_snapshot
from .simulation import health_score
from .store.repos import DiagnosticContractsRepo, MonitoringSnapshotsRepo


_CACHE: dict[str, tuple[tuple[Any, ...], dict[str, Any]]] = {}


def _cache_key(cell_id: str | None) -> str:
    return cell_id or "__latest__"


def _signature(cell_id: str | None) -> tuple[Any, ...]:
    live = MonitoringSnapshotsRepo.latest(cell_id=cell_id)
    diagnostic = DiagnosticContractsRepo.latest(cell_id=cell_id) if cell_id else DiagnosticContractsRepo.latest()
    if live is not None:
        return ("live", live.get("id"), diagnostic.get("id") if diagnostic else None)
    row = latest_cell_row(cell_id)
    return ("sample", row.get("cell_id"), str(row.get("timestamp")), diagnostic.get("id") if diagnostic else None)


def _normalize_snapshot(cell_id: str | None) -> dict[str, Any]:
    snap = latest_cell_snapshot(cell_id)
    spec = snap.pop("action_spec")
    snap["action_spec"] = {
        "action_code": spec.action_code,
        "risk_level": spec.risk_level.value,
        "estimated_impact": spec.estimated_impact.value,
        "requires_human": spec.requires_human,
        "is_reversible": spec.is_reversible,
        "autonomy": spec.autonomy,
        "reason": spec.reason,
    }
    state = snap.get("state", {})
    snap["health_score"] = health_score(state)
    return snap


def telemetry_snapshot_payload(cell_id: str | None = None) -> dict[str, Any]:
    key = _cache_key(cell_id)
    signature = _signature(cell_id)
    cached = _CACHE.get(key)
    if cached is not None and cached[0] == signature:
        return deepcopy(cached[1])
    payload = _normalize_snapshot(cell_id)
    _CACHE[key] = (signature, payload)
    return deepcopy(payload)


def reset_telemetry_cache() -> None:
    _CACHE.clear()
