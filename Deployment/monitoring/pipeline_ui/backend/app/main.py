from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any

from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.models import EventDetails
from app.services.analytics import build_pipeline_status, build_summary, normalize_action, normalize_event
from app.services.jsonl_reader import parse_datetime, read_jsonl, tail_jsonl_raw

settings = get_settings()
app = FastAPI(title='Pipeline Monitoring UI API', version='1.0.0')

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)


def _load_events(limit: int | None = None):
    return [event for row in read_jsonl(settings.monitoring_events_file, limit=limit) if (event := normalize_event(row))]


def _load_actions(limit: int | None = None):
    return [action for row in read_jsonl(settings.workflow_actions_file, limit=limit) if (action := normalize_action(row))]


@app.get('/api/summary')
def get_summary(limit: int = Query(default=5000, ge=100, le=20000)):
    return build_summary(_load_events(limit=limit), _load_actions(limit=limit * 2))


@app.get('/api/events')
def get_events(
    node_id: str | None = None,
    severity: str | None = None,
    domain: str | None = None,
    anomaly_type: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    limit: int = Query(default=500, ge=1, le=5000),
):
    events = _load_events(limit=50000)
    start_dt = parse_datetime(start_time)
    end_dt = parse_datetime(end_time)

    out = []
    for event in events:
        if node_id and event.node_id != node_id:
            continue
        if severity and event.severity != severity:
            continue
        if domain and event.domain != domain:
            continue
        if anomaly_type and str(event.payload.get('anomaly_type', '')).lower() != anomaly_type.lower():
            continue

        evt_dt = parse_datetime(event.timestamp)
        if start_dt and evt_dt and evt_dt < start_dt:
            continue
        if end_dt and evt_dt and evt_dt > end_dt:
            continue
        out.append(event)

    out.sort(key=lambda e: parse_datetime(e.timestamp) or datetime.min, reverse=True)
    return out[:limit]


@app.get('/api/events/{event_id}')
def get_event_details(event_id: str):
    events = _load_events(limit=50000)
    actions = _load_actions(limit=100000)

    event = next((item for item in events if item.event_id == event_id), None)
    if not event:
        raise HTTPException(status_code=404, detail='event not found')

    action_v1 = next((a for a in reversed(actions) if a.event_id == event_id and a.version == 'v1'), None)
    action_v2 = next((a for a in reversed(actions) if a.event_id == event_id and a.version == 'v2_gnn'), None)

    return EventDetails(event=event, action_v1=action_v1, action_v2_gnn=action_v2)


@app.get('/api/actions')
def get_actions(version: str | None = None, domain: str | None = None, event_id: str | None = None, limit: int = Query(default=500, ge=1, le=5000)):
    actions = _load_actions(limit=100000)
    out = []
    for action in actions:
        if version and action.version != version:
            continue
        if domain and action.domain != domain:
            continue
        if event_id and action.event_id != event_id:
            continue
        out.append(action)
    return out[-limit:][::-1]


@app.get('/api/actions/comparison')
def get_action_comparison(limit: int = Query(default=300, ge=1, le=5000)):
    grouped: dict[str, dict[str, Any]] = defaultdict(lambda: {'event_id': '', 'v1': None, 'v2_gnn': None})
    for action in _load_actions(limit=100000):
        item = grouped[action.event_id]
        item['event_id'] = action.event_id
        item['v1' if action.version == 'v1' else 'v2_gnn'] = action
    comparisons = list(grouped.values())
    comparisons.sort(key=lambda x: int(x['event_id'].split('_')[-1]) if '_' in x['event_id'] else 0, reverse=True)
    return comparisons[:limit]


@app.get('/api/logs/raw')
def get_raw_logs(limit: int = Query(default=100, ge=10, le=1000)):
    return {
        'network_stream': tail_jsonl_raw(settings.network_stream_file, limit=limit),
        'monitoring_events': tail_jsonl_raw(settings.monitoring_events_file, limit=limit),
        'workflow_actions': tail_jsonl_raw(settings.workflow_actions_file, limit=limit),
    }


@app.get('/api/pipeline/status')
def get_pipeline_status():
    return build_pipeline_status(
        network_rows=read_jsonl(settings.network_stream_file, limit=5000),
        events=_load_events(limit=5000),
        actions=_load_actions(limit=10000),
    )


@app.get('/health')
def health():
    return {'status': 'ok'}
