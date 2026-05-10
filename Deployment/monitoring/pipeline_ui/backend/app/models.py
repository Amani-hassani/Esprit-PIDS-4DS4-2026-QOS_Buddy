from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field


class Action(BaseModel):
    version: Literal['v1', 'v2_gnn']
    event_id: str
    status: str
    targets: list[str] = Field(default_factory=list)
    domain: str = 'unknown'
    priority: str = 'normal'
    graph_score: float | None = None
    message: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class MonitoringEvent(BaseModel):
    event_id: str
    event_type: str
    timestamp: str
    node_id: str
    severity: str
    reason: str
    domain: str
    payload: dict[str, Any] = Field(default_factory=dict)


class EventDetails(BaseModel):
    event: MonitoringEvent
    action_v1: Action | None = None
    action_v2_gnn: Action | None = None


class PipelineStatus(BaseModel):
    last_message_ts: str | None = None
    bus_activity_last_2m: int = 0
    events_last_2m: int = 0
    actions_last_2m: int = 0
    status: Literal['live', 'stale', 'idle']


class Summary(BaseModel):
    total_events: int
    total_warnings: int
    total_critical: int
    routed_v1: int
    routed_v2: int
    domain_distribution: dict[str, int]
    anomaly_distribution: dict[str, int]
    severity_timeline: list[dict[str, Any]]
    top_anomaly_types: list[dict[str, Any]]
