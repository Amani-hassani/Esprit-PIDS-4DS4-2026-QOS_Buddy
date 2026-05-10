"""Jira ticket payload and REST helpers for deferred actions."""

from __future__ import annotations

import base64
import hashlib
import logging
import os
from typing import Any

import httpx

from contracts.noc_vocab import NOC_FACTOR_LABELS
from contracts.schemas import (
    AlertEvent,
    DiagnosisEvent,
    JiraTicketPayload,
    MetricEvent,
    ProposedActionEvent,
)

log = logging.getLogger("qos.synthesis.jira")

DASHBOARD_BASE = os.getenv("DASHBOARD_BASE_URL", "http://localhost:3000")


def build_ticket(
    *,
    alert: AlertEvent,
    diagnosis: DiagnosisEvent,
    proposed: ProposedActionEvent,
    metric: MetricEvent,
) -> JiraTicketPayload:
    trace_id = alert.trace_id or proposed.trace_id or alert.correlation_id
    payload = JiraTicketPayload(
        event_id=alert.event_id,
        cell_id=alert.cell_id,
        severity=str(alert.severity),
        display_label=alert.display_label,
        occurred_at=alert.occurred_at.isoformat(),
        kpi_snapshot=_kpi_snapshot(metric),
        top_factors=[
            {
                "display_label": f.display_label,
                "impact_pct": float(f.impact_pct),
                "direction": f.direction,
            }
            for f in (alert.top_factors or [])
        ],
        root_cause_class=diagnosis.pattern_id,
        root_cause_summary=diagnosis.pattern_label,
        recommended_action=proposed.title,
        action_rationale=proposed.description,
        safety_checks_passed=all(c.passed for c in (proposed.safety_checks or [])),
        rollback_plan=_rollback_plan(proposed),
        counterfactual_summary=_counterfactual_summary(proposed),
        decision_trace_id=trace_id,
        audit_hash="",
        approval_url=f"{DASHBOARD_BASE}/audit?trace={trace_id}",
    )
    digest = hashlib.sha256(payload.model_dump_json().encode("utf-8")).hexdigest()
    return payload.model_copy(update={"audit_hash": digest})


def build_adf_description(payload: JiraTicketPayload) -> dict[str, Any]:
    lines = [
        f"Incident: {payload.display_label}",
        f"Cell: {payload.cell_id or 'unknown'}",
        f"Severity: {payload.severity}",
        f"Occurred: {payload.occurred_at}",
        f"Root cause: {payload.root_cause_summary or payload.root_cause_class or 'unknown'}",
        f"Recommended action: {payload.recommended_action or 'None'}",
        f"Rationale: {payload.action_rationale or 'None'}",
        f"Safety checks passed: {'yes' if payload.safety_checks_passed else 'no'}",
        f"Rollback plan: {payload.rollback_plan or 'None'}",
        f"What-if: {payload.counterfactual_summary or 'Not available'}",
        f"Decision trail: {payload.approval_url}",
        f"Audit hash: {payload.audit_hash}",
    ]
    if payload.kpi_snapshot:
        lines.append("KPI snapshot:")
        for key, value in payload.kpi_snapshot.items():
            lines.append(f"- {NOC_FACTOR_LABELS.get(key, key)}: {value}")
    if payload.top_factors:
        lines.append("Top contributing factors:")
        for factor in payload.top_factors[:5]:
            label = factor.get("display_label", "factor")
            impact = factor.get("impact_pct", 0)
            direction = factor.get("direction", "up")
            lines.append(f"- {label}: {impact}% {direction}")

    return {
        "type": "paragraph",
        "content": [{"type": "text", "text": "\n".join(lines)}],
    }


async def create_jira_issue(payload: JiraTicketPayload) -> dict[str, Any] | None:
    if os.getenv("QOS_JIRA_ENABLED", "false").lower() != "true":
        return None

    base_url = os.getenv("JIRA_URL", "").rstrip("/")
    email = os.getenv("JIRA_EMAIL", "")
    token = os.getenv("JIRA_TOKEN", "")
    project_key = os.getenv("JIRA_PROJECT_KEY", "QOS")
    if not (base_url and email and token and project_key):
        log.warning("Jira enabled but URL/email/token/project key is missing")
        return None

    auth = base64.b64encode(f"{email}:{token}".encode("utf-8")).decode("ascii")
    severity = payload.severity.lower()
    fields: dict[str, Any] = {
        "project": {"key": project_key},
        "summary": (
            f"[{severity.upper()}] {payload.display_label} - "
            f"{payload.cell_id or 'unknown'} - Action DEFERRED"
        )[:240],
        "description": {
            "type": "doc",
            "version": 1,
            "content": [build_adf_description(payload)],
        },
        "issuetype": {"name": os.getenv("JIRA_ISSUE_TYPE", "Task")},
        "priority": {
            "name": "High" if severity in ("critical", "high") else "Medium"
        },
        "labels": [
            "qos-buddy",
            "auto-deferred",
            str(payload.cell_id or "unknown").replace(" ", "_"),
        ],
    }
    # Approval-URL custom field is opt-in: team-managed Jira projects (e.g. KAN)
    # don't expose customfield_10000, so writing it unconditionally 400s the request.
    approval_field = os.getenv("JIRA_APPROVAL_URL_FIELD", "").strip()
    if approval_field:
        fields[approval_field] = payload.approval_url
    body = {"fields": fields}
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
        log.warning("Jira create issue failed: %s", exc)
        return None

    data = response.json() if response.content else {}
    issue_key = str(data.get("key") or "")
    issue_url = f"{base_url}/browse/{issue_key}" if issue_key else base_url
    return {
        "type": "jira_ticket_created",
        "issue_key": issue_key,
        "issue_url": issue_url,
        "event_id": payload.event_id,
        "cell_id": payload.cell_id,
        "severity": payload.severity,
        "display_label": payload.display_label,
        "status": "created",
        "created_at": payload.occurred_at,
        "audit_hash": payload.audit_hash,
    }


def _kpi_snapshot(metric: MetricEvent) -> dict[str, float]:
    keys = (
        "latency_ms",
        "jitter_ms",
        "packet_loss_pct",
        "throughput_mbps",
        "mos_estimate",
        "bler_proxy_pct",
        "tcp_retransmit_rate",
    )
    snapshot: dict[str, float] = {}
    for key in keys:
        value = getattr(metric, key, None)
        if value is not None:
            snapshot[key] = float(value)
    return snapshot


def _rollback_plan(proposed: ProposedActionEvent) -> str:
    if proposed.is_reversible:
        return (
            "If KPIs do not improve within 60 seconds, run the dry-run rollback "
            "plan and keep the ticket open for operator review."
        )
    return "Manual rollback required; coordinate through the NOC lead before changes."


def _counterfactual_summary(proposed: ProposedActionEvent) -> str | None:
    cf = proposed.counterfactual
    if cf is None:
        return None
    no_action = cf.series_no_action[-1] if cf.series_no_action else None
    with_action = cf.series_with_action[-1] if cf.series_with_action else None
    if no_action is None or with_action is None:
        return None
    return (
        f"{cf.metric} projects to {no_action:.2f} without action and "
        f"{with_action:.2f} with the recommended action over {cf.horizon_seconds}s."
    )
