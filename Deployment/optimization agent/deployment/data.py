from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .contracts import ACTION_TOOLS, PHASE3_ACTIONS
from .core.settings import get_settings
from .inject import overlay_dataframe, root_cause_override_for
from .store.repos import DiagnosticContractsRepo, MonitoringSnapshotsRepo


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = get_settings().paths.samples_dir
INTERIM_DIR = get_settings().paths.interim_dir
REPORT_FIGURES_DIR = get_settings().paths.figures_dir


class DataUnavailableError(RuntimeError):
    """Raised when no live telemetry is available and sample fallback is disabled."""


def _read_csv_bundle(pattern: str) -> pd.DataFrame:
    files = sorted(DATA_DIR.glob(pattern))
    if not files:
        return pd.DataFrame()

    frames: list[pd.DataFrame] = []
    for file in files:
        frame = pd.read_csv(file)
        if frame.empty:
            continue
        frame = frame.dropna(axis=1, how="all").copy()
        if frame.empty:
            continue
        frame["source_file"] = file.name
        frames.append(frame)

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def _sample_fallback_enabled() -> bool:
    return get_settings().app_mode in {"demo", "dev"}


def _require_sample_fallback(feature: str) -> None:
    if _sample_fallback_enabled():
        return
    raise DataUnavailableError(
        f"{feature} unavailable: live telemetry is required in {get_settings().app_mode} mode "
        "and bundled sample-data fallback is disabled"
    )


def _sample_qos_frame(cell_id: str | None = None) -> pd.DataFrame:
    _require_sample_fallback("telemetry")
    df = overlay_dataframe(load_qos(), cell_id=cell_id)
    if cell_id:
        filtered = df[df["cell_id"].astype(str) == str(cell_id)]
        if not filtered.empty:
            df = filtered
    return df


def _sample_latest_row(cell_id: str | None = None) -> pd.Series:
    df = _sample_qos_frame(cell_id)
    return df.dropna(subset=["timestamp"]).iloc[-1]


def latest_rows_frame() -> pd.DataFrame:
    snapshots = MonitoringSnapshotsRepo.latest_per_cell(limit=500)
    if snapshots:
        diagnostics = {row["cell_id"]: row for row in DiagnosticContractsRepo.list_recent(limit=500)}
        rows = [_row_from_monitoring_snapshot(snapshot, diagnostics.get(snapshot.get("cell_id"))).to_dict() for snapshot in snapshots]
        return pd.DataFrame(rows)

    _require_sample_fallback("fleet view")
    raw = load_qos().copy()
    if raw.empty:
        return raw
    return raw.sort_values("timestamp").groupby("cell_id", as_index=False).tail(1)


@lru_cache(maxsize=1)
def load_qos() -> pd.DataFrame:
    df = _read_csv_bundle("qos_timeseries_*.csv")
    if df.empty:
        raise FileNotFoundError(f"No qos_timeseries_*.csv files found in {DATA_DIR}.")
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
    return df.sort_values("timestamp")


@lru_cache(maxsize=1)
def load_incidents() -> pd.DataFrame:
    df = _read_csv_bundle("incidents_*.csv")
    if df.empty:
        return pd.DataFrame()
    for col in ("start_timestamp", "end_timestamp"):
        if col in df:
            df[col] = pd.to_datetime(df[col], errors="coerce", utc=True)
    return df


def _num(row: pd.Series, col: str, default: float = 0.0) -> float:
    value = row.get(col, default)
    try:
        if pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default


def infer_root_cause(row: pd.Series) -> tuple[str, float, list[str]]:
    """Use the latest diagnostic contract when present; otherwise fall back to KPI heuristics."""
    diagnostic_rc = row.get("__diagnostic_root_cause__")
    if isinstance(diagnostic_rc, str) and diagnostic_rc:
        evidence = row.get("__diagnostic_evidence__", [])
        safe_evidence = [str(item) for item in evidence] if isinstance(evidence, list) else []
        summary = row.get("__diagnostic_summary__")
        if summary:
            safe_evidence = [str(summary), *safe_evidence]
        try:
            confidence = float(row.get("__diagnostic_confidence__", 0.0))
        except Exception:
            confidence = 0.0
        return diagnostic_rc, confidence, safe_evidence

    evidence: list[str] = []
    latency = _num(row, "latency_ms")
    jitter = _num(row, "jitter_ms")
    queue = _num(row, "queue_length")
    throughput = _num(row, "throughput_mbps")
    sinr = _num(row, "sinr_db", 99.0)
    cqi = _num(row, "cqi", 15.0)
    rssi = _num(row, "rssi_dbm", -40.0)
    prb = _num(row, "bandwidth_util_pct")
    ho_success = _num(row, "ho_success_rate_pct", 100.0)
    bler = _num(row, "bler_proxy_pct")
    active = _num(row, "active_connections")

    if rssi <= -85 or _num(row, "signal_health_score", 100.0) < 45:
        evidence.append(f"weak signal rssi={rssi:.1f}, signal_health={_num(row, 'signal_health_score', 0):.1f}")
        return "RC_WEAK_SIGNAL", 0.86, evidence
    if sinr <= 5:
        evidence.append(f"degraded SINR={sinr:.1f} dB")
        return "RC_SINR_DEGRADED", 0.84, evidence
    if ho_success and ho_success < 92:
        evidence.append(f"handover success={ho_success:.1f}%")
        return "RC_HO_FAILURE", 0.80, evidence
    if prb >= 85 and throughput < 5:
        evidence.append(f"high utilization={prb:.1f}% with throughput={throughput:.2f} Mbps")
        return "RC_PRB_CONGESTION", 0.82, evidence
    if latency >= 120 or jitter >= 40 or queue >= 80:
        evidence.append(f"transport pressure latency={latency:.1f} ms jitter={jitter:.1f} ms queue={queue:.1f}")
        return "RC_TRANSPORT_DELAY", 0.88, evidence
    if cqi <= 7 and bler >= 8:
        evidence.append(f"CQI/BLER mismatch cqi={cqi:.1f}, bler={bler:.1f}%")
        return "RC_CQI_MISMATCH", 0.78, evidence
    if throughput < 1 and rssi < -78 and sinr < 9:
        evidence.append(f"coverage pattern throughput={throughput:.2f}, rssi={rssi:.1f}, sinr={sinr:.1f}")
        return "RC_COVERAGE_HOLE", 0.76, evidence
    if active >= 120 or prb >= 90:
        evidence.append(f"capacity pressure active={active:.0f}, utilization={prb:.1f}%")
        return "RC_CAPACITY_OVERLOAD", 0.77, evidence
    evidence.append("no actionable impairment above deployment thresholds")
    return "RC_NONE", 0.70, evidence


def _diagnostic_for(cell_id: str | None) -> dict[str, Any] | None:
    return DiagnosticContractsRepo.latest(cell_id=cell_id) if cell_id else DiagnosticContractsRepo.latest()


def _row_from_monitoring_snapshot(snapshot: dict[str, Any], diagnostic: dict[str, Any] | None = None) -> pd.Series:
    payload = dict(snapshot.get("payload") or {})
    payload["timestamp"] = pd.to_datetime(snapshot.get("observed_at"), errors="coerce", utc=True)
    payload["zone_id"] = snapshot.get("zone_id")
    payload["node_id"] = snapshot.get("node_id")
    payload["cell_id"] = snapshot.get("cell_id")
    payload["source_file"] = snapshot.get("source_system") or "monitoring-agent"
    if diagnostic and str(diagnostic.get("cell_id")) == str(snapshot.get("cell_id")):
        payload["__diagnostic_root_cause__"] = diagnostic.get("root_cause")
        payload["__diagnostic_confidence__"] = diagnostic.get("confidence")
        payload["__diagnostic_summary__"] = diagnostic.get("summary")
        payload["__diagnostic_evidence__"] = diagnostic.get("evidence") or []
        payload["__diagnostic_recommended_action__"] = diagnostic.get("recommended_action")
    return pd.Series(payload)


def _latest_monitoring_row(cell_id: str | None = None) -> pd.Series | None:
    snapshot = MonitoringSnapshotsRepo.latest(cell_id=cell_id)
    if snapshot is None:
        return None
    return _row_from_monitoring_snapshot(snapshot, _diagnostic_for(str(snapshot.get("cell_id"))))


def latest_cell_snapshot(cell_id: str | None = None) -> dict[str, Any]:
    row = _latest_monitoring_row(cell_id)
    if row is None:
        row = _sample_latest_row(cell_id)
    rc, confidence, evidence = infer_root_cause(row)
    override = root_cause_override_for(row)
    if override and override in PHASE3_ACTIONS:
        rc = override
        confidence = max(confidence, 0.92)
        evidence = list(evidence) + [f"operator override -> {override}"]
    spec = PHASE3_ACTIONS[rc]
    recommended_action = row.get("__diagnostic_recommended_action__")
    if not isinstance(recommended_action, str) or recommended_action not in ACTION_TOOLS:
        recommended_action = spec.action_code
    fields = [
        "timestamp",
        "zone_id",
        "cell_id",
        "node_id",
        "latency_ms",
        "jitter_ms",
        "packet_loss_pct",
        "throughput_mbps",
        "bandwidth_util_pct",
        "queue_length",
        "rssi_dbm",
        "sinr_db",
        "cqi",
        "bler_proxy_pct",
        "ho_success_rate_pct",
        "active_connections",
        "anomaly_type",
        "anomaly_score",
    ]
    state = {field: row.get(field) for field in fields if field in row.index}
    state = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in state.items()}
    return {
        "root_cause": rc,
        "confidence": confidence,
        "evidence": evidence,
        "recommended_action": recommended_action,
        "action_spec": spec,
        "state": state,
    }


def latest_cell_row(cell_id: str | None = None) -> pd.Series:
    row = _latest_monitoring_row(cell_id)
    if row is not None:
        return row
    return _sample_latest_row(cell_id)


def timeseries(cell_id: str | None = None, limit: int = 160) -> list[dict[str, Any]]:
    monitoring_rows = MonitoringSnapshotsRepo.list_recent(limit=limit, cell_id=cell_id)
    if monitoring_rows:
        points: list[dict[str, Any]] = []
        for snapshot in reversed(monitoring_rows):
            payload = dict(snapshot.get("payload") or {})
            payload["timestamp"] = snapshot.get("observed_at")
            payload["cell_id"] = snapshot.get("cell_id")
            payload["zone_id"] = snapshot.get("zone_id")
            payload["node_id"] = snapshot.get("node_id")
            points.append(payload)
        return points

    df = _sample_qos_frame(cell_id)
    cols = [
        "timestamp",
        "cell_id",
        "latency_ms",
        "jitter_ms",
        "packet_loss_pct",
        "throughput_mbps",
        "bandwidth_util_pct",
        "queue_length",
        "sinr_db",
        "rssi_dbm",
        "anomaly_score",
    ]
    out = df[cols].tail(limit).copy()
    out["timestamp"] = out["timestamp"].astype(str)
    return out.replace({np.nan: None}).to_dict(orient="records")


def root_cause_feed(limit: int = 80) -> list[dict[str, Any]]:
    diagnostics = DiagnosticContractsRepo.list_recent(limit=limit)
    if diagnostics:
        items = []
        for row in diagnostics:
            rc = str(row.get("root_cause") or "RC_NONE")
            spec = PHASE3_ACTIONS.get(rc, PHASE3_ACTIONS["RC_NONE"])
            items.append(
                {
                    "timestamp": str(row.get("observed_at")),
                    "cell_id": row.get("cell_id"),
                    "root_cause": rc,
                    "confidence": float(row.get("confidence") or 0.0),
                    "action_code": row.get("recommended_action") or spec.action_code,
                    "risk_level": spec.risk_level.value,
                    "evidence": row.get("evidence") or [],
                }
            )
        return items

    if _sample_fallback_enabled():
        df = load_qos().tail(max(limit * 4, limit))
    else:
        df = latest_rows_frame().tail(limit)
    rows = []
    for _, row in df.iterrows():
        rc, confidence, evidence = infer_root_cause(row)
        if rc == "RC_NONE" and len(rows) >= limit // 3:
            continue
        spec = PHASE3_ACTIONS[rc]
        rows.append(
            {
                "timestamp": str(row.get("timestamp")),
                "cell_id": row.get("cell_id"),
                "root_cause": rc,
                "confidence": confidence,
                "action_code": spec.action_code,
                "risk_level": spec.risk_level.value,
                "evidence": evidence,
            }
        )
    return rows[-limit:][::-1]


def fleet_health() -> dict[str, Any]:
    latest = latest_rows_frame()
    rc_rows = []
    for _, row in latest.iterrows():
        rc, confidence, evidence = infer_root_cause(row)
        rc_rows.append(
            {
                "cell_id": row.get("cell_id"),
                "root_cause": rc,
                "confidence": confidence,
                "latency_ms": _num(row, "latency_ms"),
                "throughput_mbps": _num(row, "throughput_mbps"),
                "sinr_db": _num(row, "sinr_db"),
                "evidence": evidence,
            }
        )
    feed = root_cause_feed(200)
    actionable = sum(1 for item in rc_rows if item["root_cause"] != "RC_NONE")
    critical = sum(1 for item in feed if item["risk_level"] in {"high", "critical"})
    cells_total = int(latest["cell_id"].nunique()) if "cell_id" in latest else 0
    return {
        "cells_total": cells_total,
        "cells_actionable": actionable,
        "high_risk_events": critical,
        "latest": rc_rows,
        "root_cause_counts": pd.Series([x["root_cause"] for x in feed]).value_counts().to_dict(),
    }


def dataset_summary() -> dict[str, Any]:
    live = latest_rows_frame()
    if _sample_fallback_enabled():
        qos = load_qos()
        incidents = load_incidents()
    else:
        qos = live.copy()
        incidents = pd.DataFrame()
    cells = sorted(map(str, live["cell_id"].dropna().unique())) if not live.empty and "cell_id" in live else []
    if not cells and "cell_id" in qos:
        cells = sorted(map(str, qos["cell_id"].dropna().unique()))
    return {
        "qos_rows": int(len(qos)),
        "incident_rows": int(len(incidents)),
        "cells": cells,
        "date_min": str(qos["timestamp"].min()),
        "date_max": str(qos["timestamp"].max()),
        "figures": sorted(p.name for p in REPORT_FIGURES_DIR.glob("*.html"))[:80],
    }
