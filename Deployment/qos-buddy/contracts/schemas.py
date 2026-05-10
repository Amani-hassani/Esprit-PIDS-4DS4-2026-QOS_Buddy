"""
QOS-Buddy bus contracts — single source of truth for every event flowing on Redis Streams.

Every event carries:
  • a stable id + correlation/trace ids for end-to-end provenance
  • tenant + cell scoping for multi-site safety
  • BOTH a `display_label` (NOC-language, no jargon) AND a `technical_label`
    (engineer-facing) so the UI can pick per role without leaking jargon.

The NOC-language rule is enforced at the producer side:
producers MUST set `display_label` using the vocabulary defined below.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


# ───────────────────────────────── enums ─────────────────────────────────

class StreamName(str, Enum):
    METRICS_RAW = "qos.metrics.raw"
    ALERTS = "qos.alerts"
    DIAGNOSIS = "qos.diagnosis"
    INSIGHT = "qos.insight"
    ACTION_PROPOSED = "qos.action.proposed"
    ACTION_EXECUTED = "qos.action.executed"
    AUDIT = "qos.audit"
    DLQ = "qos.dlq"
    JIRA_OUTBOX = "qos.jira.outbox"
    JIRA_TICKETS = "qos.jira"


class EventType(str, Enum):
    METRIC = "metric"
    ALERT = "alert"
    DIAGNOSIS = "diagnosis"
    INSIGHT = "insight"
    ACTION_PROPOSED = "action_proposed"
    ACTION_EXECUTED = "action_executed"
    AUDIT = "audit"


class Severity(str, Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ImpactRadius(str, Enum):
    LOCAL = "local"
    SECTOR = "sector"
    REGIONAL = "regional"
    NATIONAL = "national"


class Role(str, Enum):
    NOC_VIEWER = "noc_viewer"
    NOC_EXECUTIVE = "noc_executive"
    AI_ENGINEER = "ai_engineer"
    SITE_ADMIN = "site_admin"


class AuthLevel(str, Enum):
    PASSWORD = "password"
    WEBAUTHN = "webauthn"
    WEBAUTHN_PLUS_BIOMETRIC = "webauthn_plus_biometric"


# ─────────────────────────── envelope (every event) ───────────────────────

class BusEnvelope(BaseModel):
    """Common header on every event published to any Redis Stream."""

    model_config = ConfigDict(populate_by_name=True, use_enum_values=True)

    event_id: str = Field(default_factory=lambda: f"evt-{uuid4().hex[:12]}")
    event_type: EventType
    schema_version: Literal["1"] = "1"

    # provenance — links across the whole pipeline
    correlation_id: str = Field(
        default_factory=lambda: f"corr-{uuid4().hex[:12]}",
        description="Stable id linking metric → alert → diagnosis → insight → action.",
    )
    trace_id: str | None = Field(
        default=None, description="OpenTelemetry trace id when available."
    )
    causation_id: str | None = Field(
        default=None, description="event_id of the parent event that caused this one."
    )

    # scoping
    tenant_id: str = "default"
    zone_id: str | None = None
    cell_id: str | None = None
    node_id: str | None = None

    # timing
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    published_at: datetime | None = None  # set by the bus on publish

    # producer
    producer: str = Field(..., description='Logical agent name, e.g. "monitoring".')
    producer_version: str | None = None


# ──────────────────────────────── metrics ────────────────────────────────

class MetricEvent(BusEnvelope):
    """A single sample of network KPIs from the monitoring agent.

    Field set is a strict superset of what `monitoring/qos_buddy_collector.py`
    already produces, so the bridge is a 1:1 forward with NOC-language labels added.
    """

    event_type: EventType = EventType.METRIC

    # ── core KPIs ──────────────────────────────────────────────────────
    latency_ms: float | None = None
    jitter_ms: float | None = None
    packet_loss_pct: float | None = None
    throughput_mbps: float | None = None

    # ── derived / quality ──────────────────────────────────────────────
    mos_estimate: float | None = None
    bler_proxy_pct: float | None = None
    tcp_retransmit_rate: float | None = None
    anomaly_score: float | None = None
    anomaly_flag: bool = False
    anomaly_type: str | None = None

    # ── radio (when available) ────────────────────────────────────────
    rsrp_dbm: float | None = None
    rsrq_db: float | None = None
    sinr_db: float | None = None
    rssi_dbm: float | None = None
    cqi: float | None = None
    pci: int | None = None
    earfcn: int | None = None

    # ── host ──────────────────────────────────────────────────────────
    cpu_pct: float | None = None
    memory_pct: float | None = None
    active_connections: int | None = None

    # ── meta ──────────────────────────────────────────────────────────
    data_source: str | None = None
    data_quality_rating: str | None = None
    device_type: str | None = None

    # rolling stats — kept for downstream consumers, hidden in NOC view
    extra: dict[str, Any] = Field(
        default_factory=dict,
        description="Pass-through fields not in the strict KPI set (rolling means, etc.).",
    )


# ──────────────────────────────── alerts ─────────────────────────────────

class AlertEvent(BusEnvelope):
    event_type: EventType = EventType.ALERT
    severity: Severity

    # NOC-language first
    display_label: str = Field(
        ..., description='Human-friendly alert title shown in NOC views.'
    )
    technical_label: str | None = Field(
        default=None, description="Detector-specific label (LSTM-anomaly-X). AI Engineer view only."
    )

    # what fired it
    detector: Literal["behavioral", "threshold", "forecast", "composite"] = "behavioral"
    confidence: float = Field(..., ge=0.0, le=1.0)

    # forecast-derived fields (when detector=forecast)
    time_to_breach_seconds: int | None = None
    breach_threshold: float | None = None
    breach_metric: str | None = None  # "latency_ms" etc.

    # NOC-language top contributing factors
    top_factors: list["TopFactor"] = Field(default_factory=list)

    # links
    metric_correlation_id: str | None = None

    # snapshot of the metric row that fired the alert. Carried so the
    # diagnostic agent — which expects monitoring features in its ingest
    # payload — can resolve a real root cause instead of falling into
    # `waiting_for_monitoring`. Engineer/AI Lab views may surface this;
    # the NOC view ignores it.
    monitoring_features: dict[str, float] = Field(default_factory=dict)


class TopFactor(BaseModel):
    """One contributing factor displayed to the NOC.

    `display_label` is mandatory and must NOT contain jargon.
    `technical_name` is the underlying feature name (engineer view only).
    """

    display_label: str
    impact_pct: float = Field(..., ge=0.0, le=100.0)
    direction: Literal["up", "down"] = "up"
    technical_name: str | None = None


# ─────────────────────────────── diagnosis ───────────────────────────────

class SimilarIncident(BaseModel):
    incident_id: str
    similarity_pct: float = Field(..., ge=0.0, le=100.0)
    summary: str
    resolution: str
    occurred_at: datetime | None = None
    lesson: str | None = None
    relevance_pct: int | None = Field(default=None, ge=0, le=100)
    occurred_days_ago: int | None = Field(default=None, ge=0)


class ContributingKpi(BaseModel):
    name: str
    display_label: str
    z_score: float


class CausalEdge(BaseModel):
    from_kpi: str
    to_kpi: str
    lag_seconds: int
    strength: float = Field(..., ge=0.0, le=1.0)


class DiagnosisEvent(BusEnvelope):
    event_type: EventType = EventType.DIAGNOSIS
    alert_id: str

    pattern_id: str
    pattern_label: str  # NOC-language ("Buffer pressure cluster")

    similar_incidents: list[SimilarIncident] = Field(default_factory=list)
    contributing_kpis: list[ContributingKpi] = Field(default_factory=list)
    causal_edges: list[CausalEdge] = Field(default_factory=list)
    llm_summary: str | None = None
    log_window_seconds: int = 60


# ──────────────────────────────── insight ────────────────────────────────

class InsightEvent(BusEnvelope):
    """RAG output — lesson-learned and recommended posture, NOC-language."""

    event_type: EventType = EventType.INSIGHT
    diagnosis_id: str

    summary: str  # 1-2 sentences, NOC-friendly
    lesson_id: str | None = None
    citations: list["Citation"] = Field(default_factory=list)
    confidence: float = Field(..., ge=0.0, le=1.0)


class Citation(BaseModel):
    doc_id: str
    title: str
    snippet: str
    score: float


# ────────────────────────────── safety / policy ──────────────────────────

class SafetyCheck(BaseModel):
    """One policy gate validator result, NOC-language for both pass and fail reasons."""

    name: str  # internal id, e.g. "risk_threshold"
    display_label: str  # "Risk level acceptable for auto-execution"
    passed: bool
    reason: str  # NOC-friendly reason


class PolicyVerdict(str, Enum):
    AUTO = "auto"
    DEFERRED = "deferred"
    REJECTED = "rejected"


# ──────────────────────────── proposed action ────────────────────────────

class ProposedActionEvent(BusEnvelope):
    event_type: EventType = EventType.ACTION_PROPOSED
    insight_id: str | None = None

    action_id: str = Field(default_factory=lambda: f"act-{uuid4().hex[:8]}")
    title: str  # NOC-language
    description: str  # NOC-language

    risk_level: RiskLevel
    impact_radius: ImpactRadius
    is_reversible: bool = True
    rollback_available: bool = True

    confidence: float = Field(..., ge=0.0, le=1.0)
    estimated_users_affected: int | None = None
    estimated_sla_burn_pct: float | None = None

    safety_checks: list[SafetyCheck] = Field(default_factory=list)
    verdict: PolicyVerdict

    # what-if comparison snapshot (small, for the UI mini-chart)
    counterfactual: "Counterfactual | None" = None

    # the actual playbook payload, opaque to the UI
    playbook_id: str | None = None
    playbook_params: dict[str, Any] = Field(default_factory=dict)


class Counterfactual(BaseModel):
    metric: str  # e.g. "latency_ms"
    horizon_seconds: int
    series_no_action: list[float]
    series_with_action: list[float]


# ──────────────────────────── executed action ────────────────────────────

class ExecutedActionEvent(BusEnvelope):
    event_type: EventType = EventType.ACTION_EXECUTED
    action_id: str

    mode: Literal["dry_run", "simulated", "real"] = "simulated"
    success: bool
    duration_ms: int | None = None

    diff_summary: str | None = None
    rolled_back: bool = False
    rollback_reason: str | None = None

    audit_hash: str  # hash-chained for the WORM ledger


# ─────────────────────────────── audit ───────────────────────────────────

class AuditEvent(BusEnvelope):
    event_type: EventType = EventType.AUDIT
    actor: str
    actor_role: Role
    action: str
    target_id: str | None = None
    auth_level: AuthLevel
    succeeded: bool
    prev_hash: str | None = None
    hash: str


# ────────────────────────────── jira ticket ──────────────────────────────

class JiraKpiSnapshot(BaseModel):
    name: str
    display_label: str
    value: float | None
    unit: str
    baseline: float | None = None
    change_pct: float | None = None


class JiraTicketPayload(BaseModel):
    """Full Jira payload created automatically when an action is deferred."""

    event_id: str
    action_id: str | None = None
    cell_id: str | None
    severity: str
    display_label: str
    occurred_at: str
    kpi_snapshot: dict[str, float]
    top_factors: list[dict[str, Any]]
    root_cause_class: str | None
    root_cause_summary: str | None
    recommended_action: str | None
    action_rationale: str | None
    safety_checks_passed: bool
    rollback_plan: str | None
    counterfactual_summary: str | None
    decision_trace_id: str | None
    audit_hash: str
    approval_url: str


# resolve forward refs
AlertEvent.model_rebuild()
ProposedActionEvent.model_rebuild()
InsightEvent.model_rebuild()
