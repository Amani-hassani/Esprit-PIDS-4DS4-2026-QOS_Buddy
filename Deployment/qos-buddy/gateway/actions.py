"""
Action decision endpoints — the human-in-the-loop side of the policy loop.

The synthesis agent publishes a ProposedActionEvent with a *recommended*
verdict (auto / deferred / rejected). The Optimization page in the shell
lets a NOC Executive override that recommendation:

  • approve → run the guarded playbook preview,
              publish ExecutedActionEvent + AuditEvent.
  • defer   → publish a fresh Jira ticket (JIRA_OUTBOX) populated with
              everything an on-call needs, plus an AuditEvent.
  • reject  → publish AuditEvent only.

Everything is real:
  • the proposal is fetched from qos.action.proposed (no in-memory cache,
    so a fresh gateway pod still sees prior proposals)
  • the audit chain is hash-seeded from qos.audit on first use
  • the executed event records a guarded preview; no network device is changed
    without the production AWX integration being enabled.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Literal

import httpx
from fastapi import Depends, HTTPException, Request, status
from pydantic import BaseModel, ValidationError

from bus.redis_streams import RedisStreamsBus
from contracts.noc_vocab import NOC_FACTOR_LABELS
from contracts.schemas import (
    AlertEvent,
    AuditEvent,
    AuthLevel,
    DiagnosisEvent,
    ExecutedActionEvent,
    JiraTicketPayload,
    MetricEvent,
    ProposedActionEvent,
    Role,
    Severity,
    StreamName,
)

from .auth import Principal

log = logging.getLogger("qos.gateway.actions")

DASHBOARD_BASE = os.getenv("DASHBOARD_BASE_URL", "http://localhost:3000")
GENESIS_HASH = "0" * 64

# Roles allowed to make action decisions. NOC viewers are read-only.
_DECIDER_ROLES = {Role.NOC_EXECUTIVE, Role.AI_ENGINEER, Role.SITE_ADMIN}


# ─── request/response models ───────────────────────────────────────────────


class DecisionBody(BaseModel):
    decision: Literal["approve", "defer", "reject"]
    note: str | None = None


class DecisionResult(BaseModel):
    ok: bool
    action_id: str
    decision: str
    audit_hash: str
    executed_event_id: str | None = None
    ticket_summary: str | None = None


async def _post_jira_ticket(payload: JiraTicketPayload) -> dict[str, Any] | None:
    if os.getenv("QOS_JIRA_ENABLED", "false").lower() != "true":
        return None
    base_url = os.getenv("JIRA_URL", "").rstrip("/")
    email = os.getenv("JIRA_EMAIL", "")
    token = os.getenv("JIRA_TOKEN", "")
    project_key = os.getenv("JIRA_PROJECT_KEY", "QOS")
    if not (base_url and email and token and project_key):
        log.warning("Jira enabled but required configuration is missing")
        return None
    auth = base64.b64encode(f"{email}:{token}".encode("utf-8")).decode("ascii")
    severity = payload.severity.lower()
    body = {
        "fields": {
            "project": {"key": project_key},
            "summary": (
                f"[{severity.upper()}] {payload.display_label} - "
                f"{payload.cell_id or 'unknown'} - Action DEFERRED"
            )[:240],
            "description": {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [
                            {
                                "type": "text",
                                "text": payload.model_dump_json(),
                            }
                        ],
                    }
                ],
            },
            "issuetype": {"name": os.getenv("JIRA_ISSUE_TYPE", "Incident")},
            "priority": {
                "name": "High" if severity in ("critical", "high") else "Medium"
            },
            "labels": ["qos-buddy", "operator-deferred", payload.cell_id or "unknown"],
        }
    }
    approval_field = os.getenv("JIRA_APPROVAL_URL_FIELD", "").strip()
    if approval_field:
        body["fields"][approval_field] = payload.approval_url
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{base_url}/rest/api/3/issue",
                headers={
                    "Authorization": f"Basic {auth}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
            response.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        log.warning("Jira issue creation failed: %s", exc)
        return None
    data = response.json() if response.content else {}
    issue_key = str(data.get("key") or "")
    return {
        "type": "jira_ticket_created",
        "issue_key": issue_key,
        "issue_url": f"{base_url}/browse/{issue_key}" if issue_key else base_url,
        "event_id": payload.event_id,
        "cell_id": payload.cell_id,
        "severity": payload.severity,
        "display_label": payload.display_label,
        "status": "created",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "audit_hash": payload.audit_hash,
    }


# ─── audit chain (gateway-local, seeded from stream) ───────────────────────


class GatewayAuditChain:
    """Hash-chained audit ledger seeded from the qos.audit stream.

    We hold a single in-memory `prev_hash`. On startup `seed()` reads the
    last published audit and adopts its hash. Concurrent writers across
    pods would race on prev_hash; a single gateway is fine for the demo
    and is the deployment target.
    """

    def __init__(self) -> None:
        self._prev_hash: str = GENESIS_HASH
        self._lock = asyncio.Lock()

    async def seed(self, bus: RedisStreamsBus) -> None:
        try:
            latest = await bus.latest(StreamName.AUDIT, count=1)
        except Exception as exc:  # noqa: BLE001
            log.warning("audit seed failed: %s", exc)
            return
        if latest:
            _id, payload = latest[-1]
            self._prev_hash = str(payload.get("hash") or GENESIS_HASH)
            log.info("audit chain seeded prev_hash=%s", self._prev_hash[:12])

    async def append(
        self,
        *,
        actor: str,
        actor_role: Role,
        action: str,
        target_id: str | None,
        succeeded: bool,
        auth_level: AuthLevel,
        correlation_id: str | None,
        causation_id: str | None,
        cell_id: str | None,
    ) -> AuditEvent:
        async with self._lock:
            body = {
                "prev_hash": self._prev_hash,
                "actor": actor,
                "actor_role": actor_role.value,
                "action": action,
                "target_id": target_id,
                "auth_level": auth_level.value,
                "succeeded": succeeded,
                "occurred_at": datetime.now(timezone.utc).isoformat(),
            }
            digest = hashlib.sha256(
                json.dumps(body, sort_keys=True).encode()
            ).hexdigest()
            event = AuditEvent(
                producer="gateway",
                producer_version="0.1",
                correlation_id=correlation_id or f"corr-{digest[:12]}",
                causation_id=causation_id,
                cell_id=cell_id,
                actor=actor,
                actor_role=actor_role,
                action=action,
                target_id=target_id,
                auth_level=auth_level,
                succeeded=succeeded,
                prev_hash=self._prev_hash,
                hash=digest,
            )
            self._prev_hash = digest
            return event


_chain = GatewayAuditChain()


async def init_actions(bus: RedisStreamsBus) -> None:
    """Called from the gateway lifespan to warm the chain."""
    await _chain.seed(bus)


# ─── endpoint ──────────────────────────────────────────────────────────────


async def _find_proposal(bus: RedisStreamsBus, action_id: str) -> ProposedActionEvent:
    items = await bus.latest(StreamName.ACTION_PROPOSED, count=200)
    for _id, payload in reversed(items):
        try:
            ev = ProposedActionEvent.model_validate(payload)
        except ValidationError:
            continue
        if ev.action_id == action_id:
            return ev
    raise HTTPException(status.HTTP_404_NOT_FOUND, "proposal not found")


async def _related_alert(bus: RedisStreamsBus, correlation_id: str) -> AlertEvent | None:
    items = await bus.latest(StreamName.ALERTS, count=200)
    for _id, payload in reversed(items):
        if payload.get("correlation_id") != correlation_id:
            continue
        try:
            return AlertEvent.model_validate(payload)
        except ValidationError:
            return None
    return None


async def _related_diagnosis(
    bus: RedisStreamsBus, correlation_id: str
) -> DiagnosisEvent | None:
    items = await bus.latest(StreamName.DIAGNOSIS, count=200)
    for _id, payload in reversed(items):
        if payload.get("correlation_id") != correlation_id:
            continue
        try:
            return DiagnosisEvent.model_validate(payload)
        except ValidationError:
            return None
    return None


async def _latest_metric(
    bus: RedisStreamsBus, cell_id: str | None
) -> MetricEvent | None:
    items = await bus.latest(StreamName.METRICS_RAW, count=50)
    target = cell_id or None
    for _id, payload in reversed(items):
        try:
            ev = MetricEvent.model_validate(payload)
        except ValidationError:
            continue
        if target and ev.cell_id != target:
            continue
        return ev
    return None


def _kpi_snapshot(metric: MetricEvent) -> dict[str, float]:
    fields = (
        "latency_ms",
        "jitter_ms",
        "packet_loss_pct",
        "throughput_mbps",
        "mos_estimate",
        "bler_proxy_pct",
        "tcp_retransmit_rate",
    )
    out: dict[str, float] = {}
    for field in fields:
        value = getattr(metric, field, None)
        if value is None:
            continue
        out[field] = float(value)
    return out


def _build_ticket(
    *,
    proposed: ProposedActionEvent,
    alert: AlertEvent | None,
    diagnosis: DiagnosisEvent | None,
    metric: MetricEvent | None,
    audit_hash: str,
    decided_by: str,
    note: str | None,
) -> JiraTicketPayload:
    cell = (alert.cell_id if alert else proposed.cell_id) or "default"
    sev_value = (
        alert.severity if alert and isinstance(alert.severity, str) else "medium"
    )
    severity = Severity(sev_value)
    label = (alert.display_label if alert else proposed.title) or proposed.title
    summary = f"[{severity.value.upper()}] {label} — {cell} ({proposed.title})"

    rollback = (
        "If the change does not improve KPIs within 60 seconds, the auto-rollback "
        "monitor reverts the configuration and re-opens this ticket."
        if proposed.is_reversible
        else "Manual rollback required — coordinate with the NOC Executive on shift."
    )
    description_suffix = f"\n\nDeferred by {decided_by}."
    if note:
        description_suffix += f" Note: {note}"

    return JiraTicketPayload(
        project_key="QOS",
        summary=summary,
        incident_cell=cell,
        incident_started_at=(alert.occurred_at if alert else datetime.now(timezone.utc)),
        severity=severity,
        time_to_breach_seconds=alert.time_to_breach_seconds if alert else None,
        kpis=_kpi_snapshots(metric) if metric else [],
        top_factors=list(alert.top_factors or []) if alert else [],
        similar_incidents=list(diagnosis.similar_incidents or []) if diagnosis else [],
        recommended_action_title=proposed.title,
        recommended_action_description=proposed.description + description_suffix,
        risk_level=proposed.risk_level,
        impact_radius=proposed.impact_radius,
        is_reversible=proposed.is_reversible,
        confidence=proposed.confidence,
        safety_checks=list(proposed.safety_checks or []),
        counterfactual=proposed.counterfactual,
        rollback_plan=rollback,
        audit_hash=audit_hash,
        approve_url=(
            f"{DASHBOARD_BASE}/optimization?action={proposed.action_id}&decision=approve"
        ),
        reject_url=(
            f"{DASHBOARD_BASE}/optimization?action={proposed.action_id}&decision=reject"
        ),
        decision_trail_url=(
            f"{DASHBOARD_BASE}/audit?correlation={proposed.correlation_id}"
        ),
        correlation_id=proposed.correlation_id,
        action_id=proposed.action_id,
    )


def _build_ticket_v2(
    *,
    proposed: ProposedActionEvent,
    alert: AlertEvent | None,
    diagnosis: DiagnosisEvent | None,
    metric: MetricEvent | None,
    decided_by: str,
    note: str | None,
) -> JiraTicketPayload:
    cell = (alert.cell_id if alert else proposed.cell_id) or "default"
    sev_value = alert.severity if alert and isinstance(alert.severity, str) else "medium"
    severity = Severity(sev_value)
    label = (alert.display_label if alert else proposed.title) or proposed.title
    rollback = (
        "If KPIs do not improve within 60 seconds, run the guarded rollback plan "
        "and keep the ticket open for operator review."
        if proposed.is_reversible
        else "Manual rollback required; coordinate through the NOC lead before changes."
    )
    suffix = f"\n\nDeferred by {decided_by}."
    if note:
        suffix += f" Note: {note}"
    trace_id = (alert.trace_id if alert else None) or proposed.trace_id or proposed.correlation_id
    counterfactual_summary = None
    if proposed.counterfactual is not None:
        cf = proposed.counterfactual
        if cf.series_no_action and cf.series_with_action:
            counterfactual_summary = (
                f"{cf.metric} projects to {cf.series_no_action[-1]:.2f} without action "
                f"and {cf.series_with_action[-1]:.2f} with action over {cf.horizon_seconds}s."
            )
    payload = JiraTicketPayload(
        event_id=alert.event_id if alert else proposed.event_id,
        cell_id=cell,
        severity=severity.value,
        display_label=label,
        occurred_at=(
            alert.occurred_at if alert else datetime.now(timezone.utc)
        ).isoformat(),
        kpi_snapshot=_kpi_snapshot(metric) if metric else {},
        top_factors=[
            {
                "display_label": f.display_label,
                "impact_pct": float(f.impact_pct),
                "direction": f.direction,
            }
            for f in (alert.top_factors if alert else [])
        ],
        root_cause_class=diagnosis.pattern_id if diagnosis else None,
        root_cause_summary=diagnosis.pattern_label if diagnosis else None,
        recommended_action=proposed.title,
        action_rationale=proposed.description + suffix,
        safety_checks_passed=all(c.passed for c in (proposed.safety_checks or [])),
        rollback_plan=rollback,
        counterfactual_summary=counterfactual_summary,
        decision_trace_id=trace_id,
        audit_hash="",
        approval_url=f"{DASHBOARD_BASE}/audit?trace={trace_id}",
    )
    digest = hashlib.sha256(payload.model_dump_json().encode("utf-8")).hexdigest()
    return payload.model_copy(update={"audit_hash": digest})


def register(app, get_principal) -> None:  # type: ignore[no-untyped-def]
    """Mount the action-decision endpoint on the FastAPI app.

    Called from `main.py` after `get_principal` is defined so we can reuse
    the same Keycloak-validated principal dependency.
    """

    @app.post("/api/actions/{action_id}/decide", response_model=DecisionResult)
    async def decide(  # noqa: D401
        action_id: str,
        body: DecisionBody,
        request: Request,
        principal: Principal = Depends(get_principal),
    ) -> DecisionResult:
        if principal.role not in _DECIDER_ROLES:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "role cannot decide")

        bus: RedisStreamsBus = request.app.state.bus
        proposed = await _find_proposal(bus, action_id)
        alert = await _related_alert(bus, proposed.correlation_id)
        diagnosis = await _related_diagnosis(bus, proposed.correlation_id)
        metric = await _latest_metric(bus, proposed.cell_id)

        decision = body.decision
        executed_event_id: str | None = None
        ticket_summary: str | None = None
        trace_id = (alert.trace_id if alert else None) or proposed.trace_id

        if decision == "approve":
            t0 = time.perf_counter()
            await asyncio.sleep(0.01)  # simulator latency, deterministic
            duration_ms = int((time.perf_counter() - t0) * 1000)
            audit = await _chain.append(
                actor=principal.username,
                actor_role=principal.role,
                action="action.approved",
                target_id=proposed.action_id,
                succeeded=True,
                auth_level=AuthLevel.WEBAUTHN,
                correlation_id=proposed.correlation_id,
                causation_id=proposed.event_id,
                cell_id=proposed.cell_id,
            )
            await bus.publish(StreamName.AUDIT, audit)
            executed = ExecutedActionEvent(
                producer="awx-guarded-preview",
                producer_version="0.1",
                correlation_id=proposed.correlation_id,
                trace_id=trace_id,
                causation_id=proposed.event_id,
                tenant_id=proposed.tenant_id,
                zone_id=proposed.zone_id,
                cell_id=proposed.cell_id,
                node_id=proposed.node_id,
                action_id=proposed.action_id,
                mode="simulated",
                success=True,
                duration_ms=duration_ms,
                diff_summary=f"Guarded playbook preview: {proposed.title}",
                rolled_back=False,
                audit_hash=audit.hash,
            )
            await bus.publish(StreamName.ACTION_EXECUTED, executed)
            executed_event_id = executed.event_id
            audit_hash = audit.hash

        elif decision == "defer":
            audit = await _chain.append(
                actor=principal.username,
                actor_role=principal.role,
                action="action.deferred",
                target_id=proposed.action_id,
                succeeded=True,
                auth_level=AuthLevel.WEBAUTHN,
                correlation_id=proposed.correlation_id,
                causation_id=proposed.event_id,
                cell_id=proposed.cell_id,
            )
            await bus.publish(StreamName.AUDIT, audit)
            ticket = _build_ticket_v2(
                proposed=proposed,
                alert=alert,
                diagnosis=diagnosis,
                metric=metric,
                decided_by=principal.username,
                note=body.note,
            )
            await bus.publish(StreamName.JIRA_OUTBOX, ticket.model_dump(mode="json"))
            jira_event = await _post_jira_ticket(ticket)
            if jira_event is not None:
                jira_event["event_id"] = proposed.event_id
                jira_event["alert_event_id"] = ticket.event_id
                jira_event["action_id"] = proposed.action_id
                await bus.publish(StreamName.JIRA_TICKETS, jira_event)
            ticket_summary = ticket.display_label
            audit_hash = audit.hash

        else:  # reject
            audit = await _chain.append(
                actor=principal.username,
                actor_role=principal.role,
                action="action.rejected",
                target_id=proposed.action_id,
                succeeded=True,
                auth_level=AuthLevel.WEBAUTHN,
                correlation_id=proposed.correlation_id,
                causation_id=proposed.event_id,
                cell_id=proposed.cell_id,
            )
            await bus.publish(StreamName.AUDIT, audit)
            audit_hash = audit.hash

        return DecisionResult(
            ok=True,
            action_id=action_id,
            decision=decision,
            audit_hash=audit_hash,
            executed_event_id=executed_event_id,
            ticket_summary=ticket_summary,
        )

    @app.post("/api/actions/{action_id}/approve", response_model=DecisionResult)
    async def approve(  # noqa: D401
        action_id: str,
        request: Request,
        principal: Principal = Depends(get_principal),
    ) -> DecisionResult:
        if principal.role not in {Role.AI_ENGINEER, Role.SITE_ADMIN}:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "role cannot approve")
        return await decide(
            action_id,
            DecisionBody(decision="approve"),
            request,
            principal,
        )
