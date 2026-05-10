"""Live KPI snapshot injection.

The dashboard reads from cached CSVs by default; this module lets operators
push synthetic snapshots through `POST /api/inject` so we can drive the agent
loop and live UI from a control surface.

Injected rows are:
- Held in a bounded ring buffer (newest wins, oldest dropped).
- Merged on top of CSV rows by `latest_cell_row`, `latest_cell_snapshot`,
  and `timeseries` so existing endpoints react without writing to disk.
- Published on the `telemetry` SSE channel so subscribed clients refresh.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Iterable

import pandas as pd

from .core.clock import utc_now


_BUFFER_SIZE = 1024


_NUMERIC_FIELDS: dict[str, float] = {
    "latency_ms": 35.0,
    "jitter_ms": 6.0,
    "packet_loss_pct": 0.4,
    "throughput_mbps": 60.0,
    "bandwidth_util_pct": 45.0,
    "queue_length": 18.0,
    "rssi_dbm": -78.0,
    "sinr_db": 12.0,
    "cqi": 11.0,
    "bler_proxy_pct": 1.5,
    "ho_success_rate_pct": 98.0,
    "active_connections": 60.0,
    "anomaly_score": 0.1,
    "signal_health_score": 80.0,
}


@dataclass
class InjectedSnapshot:
    timestamp: datetime
    cell_id: str
    zone_id: str | None = None
    node_id: str | None = None
    anomaly_type: str | None = None
    root_cause_override: str | None = None
    note: str | None = None
    fields: dict[str, float] = field(default_factory=dict)
    source: str = "inject"

    def to_row(self) -> dict[str, Any]:
        row = {**_NUMERIC_FIELDS}
        row.update({k: float(v) for k, v in self.fields.items() if v is not None})
        row["timestamp"] = self.timestamp
        row["cell_id"] = str(self.cell_id)
        if self.zone_id is not None:
            row["zone_id"] = str(self.zone_id)
        if self.node_id is not None:
            row["node_id"] = str(self.node_id)
        if self.anomaly_type is not None:
            row["anomaly_type"] = str(self.anomaly_type)
        row["source_file"] = "inject://" + (self.note or "live")
        row["__injected__"] = True
        row["__rc_override__"] = self.root_cause_override
        return row

    def to_payload(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "cell_id": self.cell_id,
            "zone_id": self.zone_id,
            "node_id": self.node_id,
            "anomaly_type": self.anomaly_type,
            "root_cause_override": self.root_cause_override,
            "note": self.note,
            "fields": {k: float(v) for k, v in self.fields.items()},
            "source": self.source,
        }


_buffer: deque[InjectedSnapshot] = deque(maxlen=_BUFFER_SIZE)
_lock = Lock()


def _coerce_timestamp(raw: Any) -> datetime:
    if raw is None:
        return utc_now()
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    try:
        ts = pd.to_datetime(raw, utc=True, errors="coerce")
        if pd.isna(ts):
            return utc_now()
        return ts.to_pydatetime()
    except Exception:
        return utc_now()


def inject(
    cell_id: str,
    *,
    zone_id: str | None = None,
    node_id: str | None = None,
    fields: dict[str, Any] | None = None,
    timestamp: Any = None,
    anomaly_type: str | None = None,
    root_cause_override: str | None = None,
    note: str | None = None,
) -> InjectedSnapshot:
    """Append a snapshot to the buffer and return it. Caller decides whether to publish."""
    safe_fields: dict[str, float] = {}
    for key, value in (fields or {}).items():
        if value is None:
            continue
        try:
            safe_fields[str(key)] = float(value)
        except (TypeError, ValueError):
            continue
    snapshot = InjectedSnapshot(
        timestamp=_coerce_timestamp(timestamp),
        cell_id=str(cell_id),
        zone_id=zone_id,
        node_id=node_id,
        anomaly_type=anomaly_type,
        root_cause_override=root_cause_override,
        note=note,
        fields=safe_fields,
    )
    with _lock:
        _buffer.append(snapshot)
    return snapshot


def get_buffer() -> list[InjectedSnapshot]:
    with _lock:
        return list(_buffer)


def get_buffer_payloads() -> list[dict[str, Any]]:
    return [s.to_payload() for s in get_buffer()]


def clear() -> None:
    with _lock:
        _buffer.clear()


def overlay_dataframe(base: pd.DataFrame, *, cell_id: str | None = None) -> pd.DataFrame:
    """Merge buffered snapshots onto a base DataFrame.

    Injected rows always win when timestamps collide, and they slot in by
    `timestamp`. We keep the original column ordering from `base` and add
    bookkeeping columns (`__injected__`, `__rc_override__`) only when needed
    so downstream code can pick up the override.
    """
    snapshots = get_buffer()
    if not snapshots:
        return base
    if cell_id is not None:
        snapshots = [s for s in snapshots if str(s.cell_id) == str(cell_id)]
        if not snapshots:
            return base
    rows = [s.to_row() for s in snapshots]
    overlay = pd.DataFrame(rows)
    overlay["timestamp"] = pd.to_datetime(overlay["timestamp"], utc=True, errors="coerce")
    base_cols = list(base.columns)
    extra_cols = [c for c in overlay.columns if c not in base_cols]
    full_cols = base_cols + extra_cols
    overlay_full = overlay.reindex(columns=full_cols)
    base_full = base.reindex(columns=full_cols)
    if not extra_cols and overlay_full.empty:
        return base_full
    combined = pd.concat([base_full, overlay_full], ignore_index=True, sort=False)
    if "timestamp" in combined.columns:
        combined = combined.sort_values("timestamp", kind="mergesort")
    return combined


def root_cause_override_for(row: pd.Series) -> str | None:
    """Return the RC override attached to an injected row, if any."""
    flag = row.get("__injected__") if isinstance(row, pd.Series) else None
    if not flag:
        return None
    override = row.get("__rc_override__")
    if isinstance(override, str) and override:
        return override
    return None


def latest_payloads(limit: int = 50) -> list[dict[str, Any]]:
    snapshots = get_buffer()
    return [s.to_payload() for s in snapshots[-limit:][::-1]]
