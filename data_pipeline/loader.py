"""Load QoS time-series and incident CSVs."""

from __future__ import annotations

import glob
from pathlib import Path
from typing import List

import pandas as pd

from config import DATA_INCIDENTS_DIR, DATA_RAW_DIR, INCIDENT_GLOB, QOS_GLOB


def apply_qos_schema_cleaning(df: pd.DataFrame) -> pd.DataFrame:
    """
    Parse timestamps, fill ``teams_in_meeting``, drop ``skip_for_training`` rows.
    Use after concatenating one or more raw QoS frames (disk or upload).
    """
    if df.empty:
        return df
    out = df.copy()
    if "timestamp" in out.columns:
        out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True, errors="coerce")

    if "teams_in_meeting" not in out.columns:
        out["teams_in_meeting"] = False
    else:
        out["teams_in_meeting"] = out["teams_in_meeting"].fillna(False).astype(bool)

    if "skip_for_training" in out.columns:
        s = out["skip_for_training"]
        if s.dtype == bool:
            mask = s.fillna(False)
        else:
            mask = s.astype(str).str.lower().isin(("true", "1", "yes", "t"))
        out = out.loc[~mask].copy()

    return out.reset_index(drop=True)


def apply_incidents_schema_cleaning(df: pd.DataFrame) -> pd.DataFrame:
    """Parse incident timestamp columns after load."""
    if df.empty:
        return df
    out = df.copy()
    for col in ("start_timestamp", "end_timestamp"):
        if col in out.columns:
            out[col] = pd.to_datetime(out[col], utc=True, errors="coerce")
    return out


def _read_csv_safe(path: Path) -> pd.DataFrame:
    try:
        return pd.read_csv(path)
    except (pd.errors.EmptyDataError, FileNotFoundError):
        return pd.DataFrame()


def load_qos(raw_dir: Path | None = None, pattern: str = QOS_GLOB) -> pd.DataFrame:
    """
    Load and concatenate all QoS CSVs under ``data/raw/``.

    - Parses ``timestamp`` with ``pd.to_datetime(..., utc=True)``.
    - Drops rows where ``skip_for_training`` is True.
    - Fills missing ``teams_in_meeting`` with False.
    """
    base = Path(raw_dir) if raw_dir is not None else DATA_RAW_DIR
    paths: List[str] = sorted(glob.glob(str(base / pattern)))
    if not paths:
        return pd.DataFrame()

    frames: List[pd.DataFrame] = []
    for p in paths:
        df = _read_csv_safe(Path(p))
        if df.empty:
            continue
        frames.append(df)

    if not frames:
        return pd.DataFrame()

    out = pd.concat(frames, ignore_index=True)
    return apply_qos_schema_cleaning(out)


def load_incidents(incidents_dir: Path | None = None, pattern: str = INCIDENT_GLOB) -> pd.DataFrame:
    """
    Load and concatenate incident CSVs. Empty files are skipped without error.
    """
    base = Path(incidents_dir) if incidents_dir is not None else DATA_INCIDENTS_DIR
    paths: List[str] = sorted(glob.glob(str(base / pattern)))
    if not paths:
        return pd.DataFrame()

    frames: List[pd.DataFrame] = []
    for p in paths:
        df = _read_csv_safe(Path(p))
        if df.empty:
            continue
        frames.append(df)

    if not frames:
        return pd.DataFrame()

    out = pd.concat(frames, ignore_index=True)
    return apply_incidents_schema_cleaning(out)
