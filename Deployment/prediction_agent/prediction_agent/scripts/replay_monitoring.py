"""Replay QoS and incident-aligned monitoring data into the live dashboard store."""

from __future__ import annotations

import argparse
import math
import sys
import time
from pathlib import Path
from typing import Iterable, Iterator, Sequence

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.service import PredictionPlatformService
from config import DATA_INCIDENTS_DIR, DATA_RAW_DIR, LSTM_WINDOW
from data_pipeline.loader import apply_incidents_schema_cleaning, apply_qos_schema_cleaning, load_incidents, load_qos


def _interleave_frames(frames: Sequence[pd.DataFrame]) -> pd.DataFrame:
    ordered: list[pd.DataFrame] = []
    active = [frame.sort_values(["timestamp", "node_id"], na_position="last").reset_index(drop=True) for frame in frames if not frame.empty]
    index = 0
    while active:
        next_active: list[pd.DataFrame] = []
        for frame in active:
            if index < len(frame):
                ordered.append(frame.iloc[[index]])
            if index + 1 < len(frame):
                next_active.append(frame)
        index += 1
        active = next_active
    if not ordered:
        return pd.DataFrame()
    return pd.concat(ordered, ignore_index=True, sort=False)


def _build_incident_scenarios(
    qos: pd.DataFrame,
    incidents: pd.DataFrame,
    *,
    lookback_minutes: int,
    lookahead_minutes: int,
    max_scenarios: int,
) -> list[pd.DataFrame]:
    if incidents.empty or not {"node_id", "start_timestamp"}.issubset(incidents.columns):
        return []

    ranked = incidents.copy()
    if "max_score" in ranked.columns:
        ranked["max_score"] = pd.to_numeric(ranked["max_score"], errors="coerce").fillna(0.0)
    else:
        ranked["max_score"] = 0.0
    severity_series = ranked["severity"] if "severity" in ranked.columns else pd.Series([""] * len(ranked), index=ranked.index)
    ranked["severity_rank"] = severity_series.astype(str).str.lower().map(
        {"critical": 4, "high": 3, "warning": 2, "watch": 1, "normal": 0}
    ).fillna(0)
    ranked = ranked.sort_values(["severity_rank", "max_score", "start_timestamp"], ascending=[False, False, True], na_position="last")

    seen: set[tuple[str, str]] = set()
    scenarios: list[pd.DataFrame] = []
    for incident in ranked.itertuples(index=False):
        node_id = str(getattr(incident, "node_id", ""))
        incident_type = str(getattr(incident, "incident_type", "unknown"))
        key = (node_id, incident_type)
        if not node_id or key in seen:
            continue
        seen.add(key)
        start_ts = getattr(incident, "start_timestamp", None)
        if pd.isna(start_ts):
            continue
        end_ts = getattr(incident, "end_timestamp", None)
        if pd.isna(end_ts):
            end_ts = start_ts
        window_start = pd.Timestamp(start_ts) - pd.Timedelta(minutes=lookback_minutes)
        window_end = pd.Timestamp(end_ts) + pd.Timedelta(minutes=lookahead_minutes)
        scoped = qos[
            (qos["node_id"].astype(str) == node_id)
            & (qos["timestamp"] >= window_start)
            & (qos["timestamp"] <= window_end)
        ].copy()
        if scoped.empty:
            continue
        scenarios.append(scoped)
        if len(scenarios) >= max_scenarios:
            break
    return scenarios


def build_replay_frame(
    qos: pd.DataFrame,
    incidents: pd.DataFrame,
    *,
    min_rows: int = 120,
    node_ids: Sequence[str] | None = None,
    lookback_minutes: int = 15,
    lookahead_minutes: int = 15,
    max_scenarios: int = 6,
) -> pd.DataFrame:
    """Prefer incident-aligned QoS windows and fall back to recent history when needed."""
    qos = apply_qos_schema_cleaning(qos)
    incidents = apply_incidents_schema_cleaning(incidents)
    if qos.empty:
        raise ValueError("No QoS rows found for replay.")

    if node_ids:
        selected = {str(node_id) for node_id in node_ids}
        qos = qos[qos["node_id"].astype(str).isin(selected)].copy()
        incidents = incidents[incidents["node_id"].astype(str).isin(selected)].copy()
        if qos.empty:
            raise ValueError("Requested node filters removed all QoS rows.")

    qos = qos.sort_values(["timestamp", "node_id"], na_position="last").reset_index(drop=True)
    incident_windows = _build_incident_scenarios(
        qos,
        incidents,
        lookback_minutes=lookback_minutes,
        lookahead_minutes=lookahead_minutes,
        max_scenarios=max_scenarios,
    )

    if incident_windows:
        per_scenario = max(LSTM_WINDOW + 5, math.ceil(min_rows / max(len(incident_windows), 1)))
        trimmed = [frame.tail(per_scenario).reset_index(drop=True) for frame in incident_windows]
        replay = _interleave_frames(trimmed)
        replay = replay.drop_duplicates(subset=["timestamp", "node_id"], keep="last")
        selected_nodes = sorted({str(node_id) for node_id in replay["node_id"].dropna().astype(str).tolist()})
        if len(replay) < min_rows and selected_nodes:
            supplemental = qos[qos["node_id"].astype(str).isin(selected_nodes)].copy()
            supplemental = (
                supplemental.groupby("node_id", group_keys=False)
                .tail(max(LSTM_WINDOW, math.ceil((min_rows - len(replay)) / max(len(selected_nodes), 1))))
                .sort_values(["timestamp", "node_id"], na_position="last")
            )
            replay = _interleave_frames([supplemental, replay])
            replay = replay.drop_duplicates(subset=["timestamp", "node_id"], keep="last")
    else:
        node_count = max(int(qos["node_id"].astype(str).nunique()), 1)
        per_node = max(LSTM_WINDOW, math.ceil(min_rows / node_count))
        replay = (
            qos.groupby("node_id", group_keys=False)
            .tail(per_node)
            .sort_values(["timestamp", "node_id"], na_position="last")
            .reset_index(drop=True)
        )

    replay = replay.sort_values(["timestamp", "node_id"], na_position="last").reset_index(drop=True)
    if len(replay) > min_rows:
        replay = replay.tail(min_rows).reset_index(drop=True)
    return replay


def iter_replay_batches(frame: pd.DataFrame, *, timestamps_per_step: int = 1) -> Iterator[pd.DataFrame]:
    """Yield batches grouped by one or more source timestamps."""
    if frame.empty:
        return
    step = max(int(timestamps_per_step), 1)
    timestamps = sorted(frame["timestamp"].dropna().drop_duplicates().tolist())
    for index in range(0, len(timestamps), step):
        chunk = set(timestamps[index : index + step])
        yield frame[frame["timestamp"].isin(chunk)].sort_values(["timestamp", "node_id"], na_position="last").reset_index(drop=True)


def frame_to_json_records(frame: pd.DataFrame) -> list[dict[str, object]]:
    payload = frame.copy()
    for column in payload.columns:
        if pd.api.types.is_datetime64_any_dtype(payload[column]):
            payload[column] = payload[column].map(
                lambda value: None if pd.isna(value) else pd.Timestamp(value).isoformat()
            )
    payload = payload.where(pd.notna(payload), None)
    return payload.to_dict(orient="records")


def reset_monitoring_target(backend_url: str | None, service: PredictionPlatformService | None) -> None:
    if backend_url:
        try:
            response = requests.post(backend_url.rstrip("/") + "/api/monitoring/reset", timeout=60)
            if response.ok:
                return
            print(f"[reset] backend reset unavailable ({response.status_code}); continuing without clearing live feed")
            return
        except Exception as exc:
            print(f"[reset] backend reset failed ({type(exc).__name__}: {exc}); continuing without clearing live feed")
            return

    if service is not None and service.monitoring_kpi_path.exists():
        try:
            service.monitoring_kpi_path.unlink()
        except PermissionError:
            print("[reset] local monitoring file is locked; continuing without clearing live feed")


def replay_monitoring(
    service: PredictionPlatformService | None,
    frame: pd.DataFrame,
    *,
    backend_url: str | None,
    interval_seconds: float,
    generate_llm: bool,
    persist: bool,
    sync_incidents: bool,
    timestamps_per_step: int,
    window_rows: int,
    max_steps: int | None,
    loop_forever: bool,
) -> None:
    step_counter = 0
    synced = False

    while True:
        for batch in iter_replay_batches(frame, timestamps_per_step=timestamps_per_step):
            step_counter += 1
            records = frame_to_json_records(batch)
            if backend_url:
                response = requests.post(
                    backend_url.rstrip("/") + "/api/monitoring/ingest",
                    json={
                        "records": records,
                        "generate_llm": generate_llm,
                        "persist": persist,
                        "sync_incidents": sync_incidents and not synced,
                        "cadence_seconds": max(int(interval_seconds), 1),
                        "window_rows": window_rows,
                    },
                    timeout=120,
                )
                response.raise_for_status()
                result = response.json()
                synced = True
            else:
                assert service is not None
                if sync_incidents and not synced:
                    incident_result = service.sync_incidents(replace=False)
                    print(
                        f"[incidents] status={incident_result.get('status')} "
                        f"ingested={incident_result.get('ingested', 0)}"
                    )
                    synced = True

                result = service.ingest_monitoring_records(
                    records,
                    generate_llm=generate_llm,
                    persist=persist,
                    sync_incidents=False,
                    cadence_seconds=max(int(interval_seconds), 1),
                    window_rows=window_rows,
                )
            print(
                f"[step {step_counter}] rows={result['record_count']} "
                f"nodes={len(result['nodes'])} "
                f"predictions={result['prediction_count']} "
                f"processed={','.join(result['processed_nodes']) or '-'} "
                f"skipped={len(result['skipped_nodes'])}"
            )

            if max_steps is not None and step_counter >= max_steps:
                return
            if interval_seconds > 0:
                time.sleep(interval_seconds)

        if not loop_forever:
            return


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Replay QoS monitoring rows into the dashboard and prediction store.")
    parser.add_argument("--interval-seconds", type=float, default=30.0, help="Delay between replay ticks. Use 0 for fast replay.")
    parser.add_argument("--timestamps-per-step", type=int, default=1, help="How many source timestamps to send on each replay tick.")
    parser.add_argument("--min-rows", type=int, default=120, help="Target number of source rows to replay.")
    parser.add_argument("--window-rows", type=int, default=60, help="History window per node used for prediction after each ingest.")
    parser.add_argument("--max-steps", type=int, default=None, help="Optional cap on replay steps.")
    parser.add_argument("--lookback-minutes", type=int, default=15, help="Minutes of QoS history to include before each incident.")
    parser.add_argument("--lookahead-minutes", type=int, default=15, help="Minutes of QoS history to include after each incident.")
    parser.add_argument("--max-scenarios", type=int, default=6, help="Maximum number of incident scenarios to interleave into the replay.")
    parser.add_argument("--node-id", action="append", dest="node_ids", default=None, help="Optional node filter. Repeat for multiple nodes.")
    parser.add_argument("--loop", action="store_true", help="Restart from the beginning when the selected replay window finishes.")
    parser.set_defaults(generate_llm=True)
    parser.add_argument("--generate-llm", action="store_true", dest="generate_llm", help="Enable LLM synthesis during prediction.")
    parser.add_argument("--no-generate-llm", action="store_false", dest="generate_llm", help="Disable LLM synthesis during prediction.")
    parser.add_argument("--no-persist", action="store_true", help="Do not persist predictions to the runtime database.")
    parser.add_argument("--skip-incident-sync", action="store_true", help="Do not ingest incidents before replay starts.")
    parser.add_argument("--replace-monitoring-file", action="store_true", help="Delete the current monitoring KPI CSV before replaying.")
    parser.add_argument("--backend-url", default="http://127.0.0.1:8000", help="Backend base URL for in-process monitoring ingest. Use empty value to run locally.")
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> None:
    args = parse_args(argv)
    qos = load_qos(DATA_RAW_DIR)
    incidents = load_incidents(DATA_INCIDENTS_DIR)
    replay = build_replay_frame(
        qos,
        incidents,
        min_rows=max(int(args.min_rows), LSTM_WINDOW),
        node_ids=args.node_ids,
        lookback_minutes=args.lookback_minutes,
        lookahead_minutes=args.lookahead_minutes,
        max_scenarios=max(int(args.max_scenarios), 1),
    )

    backend_url = str(args.backend_url or "").strip()
    service = None if backend_url else PredictionPlatformService()
    if args.replace_monitoring_file:
        reset_monitoring_target(backend_url or None, service)

    print(
        f"Prepared {len(replay)} QoS rows across "
        f"{replay['node_id'].astype(str).nunique()} node(s) "
        f"from {replay['timestamp'].min()} to {replay['timestamp'].max()}."
    )
    replay_monitoring(
        service,
        replay,
        backend_url=backend_url or None,
        interval_seconds=max(float(args.interval_seconds), 0.0),
        generate_llm=bool(args.generate_llm),
        persist=not args.no_persist,
        sync_incidents=not args.skip_incident_sync,
        timestamps_per_step=max(int(args.timestamps_per_step), 1),
        window_rows=max(int(args.window_rows), LSTM_WINDOW),
        max_steps=args.max_steps,
        loop_forever=bool(args.loop),
    )


if __name__ == "__main__":
    main()
