from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any

from app.models import Action, MonitoringEvent, PipelineStatus, Summary
from app.services.jsonl_reader import parse_datetime


def normalize_action(row: dict[str, Any]) -> Action | None:
    if 'version' in row and 'action' in row and isinstance(row.get('action'), dict):
        version = str(row.get('version', 'v1'))
        action_raw = row['action']
    else:
        version = 'v1'
        action_raw = row

    event_id = action_raw.get('event_id')
    if not event_id:
        return None

    return Action(
        version='v2_gnn' if version == 'v2_gnn' else 'v1',
        event_id=str(event_id),
        status=str(action_raw.get('status', 'unknown')),
        targets=[str(t) for t in action_raw.get('targets', []) if t is not None],
        domain=str(action_raw.get('domain', 'unknown')),
        priority=str(action_raw.get('priority', 'normal')),
        graph_score=action_raw.get('graph_score'),
        message=action_raw.get('message'),
        raw=action_raw,
    )


def normalize_event(row: dict[str, Any]) -> MonitoringEvent | None:
    if not row.get('event_id') or not row.get('timestamp') or not row.get('node_id'):
        return None

    return MonitoringEvent(
        event_id=str(row.get('event_id')),
        event_type=str(row.get('event_type', 'MonitoringAlertRaised')),
        timestamp=str(row.get('timestamp')),
        node_id=str(row.get('node_id')),
        severity=str(row.get('severity', 'unknown')),
        reason=str(row.get('reason', '')),
        domain=str(row.get('domain', 'unknown')),
        payload=row.get('payload', {}) if isinstance(row.get('payload'), dict) else {},
    )


def build_summary(events: list[MonitoringEvent], actions: list[Action]) -> Summary:
    total_events = len(events)
    total_warnings = sum(1 for e in events if e.severity == 'warning')
    total_critical = sum(1 for e in events if e.severity == 'critical')
    routed_v1 = sum(1 for a in actions if a.version == 'v1' and a.status in {'routed', 'graph_routed'})
    routed_v2 = sum(1 for a in actions if a.version == 'v2_gnn' and a.status in {'routed', 'graph_routed'})

    domain_distribution = Counter(e.domain for e in events)
    anomaly_distribution = Counter(str(e.payload.get('anomaly_type', 'unknown')) for e in events)

    timeline: dict[str, dict[str, int]] = defaultdict(lambda: {'normal': 0, 'warning': 0, 'critical': 0})
    for event in events:
        dt = parse_datetime(event.timestamp)
        if not dt:
            continue
        bucket = dt.replace(second=0, microsecond=0).isoformat()
        sev = event.severity if event.severity in {'normal', 'warning', 'critical'} else 'normal'
        timeline[bucket][sev] += 1

    severity_timeline = [{'timestamp': key, **val} for key, val in sorted(timeline.items(), key=lambda x: x[0])[-60:]]
    top_anomaly_types = [{'name': key, 'count': count} for key, count in anomaly_distribution.most_common(10)]

    return Summary(
        total_events=total_events,
        total_warnings=total_warnings,
        total_critical=total_critical,
        routed_v1=routed_v1,
        routed_v2=routed_v2,
        domain_distribution=dict(domain_distribution),
        anomaly_distribution=dict(anomaly_distribution),
        severity_timeline=severity_timeline,
        top_anomaly_types=top_anomaly_types,
    )


def build_pipeline_status(network_rows: list[dict[str, Any]], events: list[MonitoringEvent], actions: list[Action]) -> PipelineStatus:
    now = datetime.now()
    window = now - timedelta(minutes=2)

    bus_times = [parse_datetime(str(r.get('timestamp') or r.get('published_at') or '')) for r in network_rows]
    event_times = [parse_datetime(e.timestamp) for e in events]
    action_times = [parse_datetime(str(a.raw.get('timestamp') or a.raw.get('graph_packet', {}).get('timestamp') or '')) for a in actions]

    bus_times = [t for t in bus_times if t]
    event_times = [t for t in event_times if t]
    action_times = [t for t in action_times if t]

    last_message = max(bus_times) if bus_times else None
    bus_recent = sum(1 for t in bus_times if t >= window)
    event_recent = sum(1 for t in event_times if t >= window)
    action_recent = sum(1 for t in action_times if t >= window)

    if last_message is None:
        status = 'idle'
    elif last_message >= now - timedelta(seconds=20):
        status = 'live'
    else:
        status = 'stale'

    return PipelineStatus(
        last_message_ts=last_message.isoformat() if last_message else None,
        bus_activity_last_2m=bus_recent,
        events_last_2m=event_recent,
        actions_last_2m=action_recent,
        status=status,
    )
