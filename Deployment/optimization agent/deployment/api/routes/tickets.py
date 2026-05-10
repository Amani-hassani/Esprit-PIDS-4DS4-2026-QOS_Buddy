from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from ...core.access import Principal
from ...integrations import JiraClient, JiraConfig, ticket_provider
from ...store.repos import ChangeTicketsRepo
from .._json import json_safe
from ..deps import engineer_required, viewer_required


router = APIRouter(prefix="/api/tickets", tags=["tickets"])
logger = logging.getLogger("qos_buddy.api.tickets")


def _raise_ticket_conflict(detail: str) -> None:
    raise HTTPException(status_code=409, detail=detail)


def _jira_key_from_evidence(row: dict | None) -> str | None:
    if not row:
        return None
    evidence = row.get("evidence") or {}
    if not isinstance(evidence, dict):
        return None
    if evidence.get("provider") != "jira":
        return None
    key = evidence.get("ticket_key")
    return str(key) if key else None


@router.get("/provider-health")
def provider_health(principal: Principal = Depends(viewer_required)):
    config = JiraConfig.from_settings(refresh=True)
    client = JiraClient(config)
    project_access = None
    if client.is_configured():
        try:
            project_access = client.project_create_access()
        except Exception as exc:
            project_access = {"ok": False, "reason": str(exc)}
    return json_safe(
        {
            "provider": ticket_provider(),
            "configured": config.configured,
            "jira": {
                "url": config.url or None,
                "project_key": config.project_key or None,
                "issue_type": config.issue_type,
                "email": config.email or None,
                "can_create": client.is_configured(),
                "done_transitions": list(config.done_transitions),
                "timeout_s": config.timeout_s,
                "project_access": project_access,
            },
        }
    )


@router.post("/probe")
def probe(principal: Principal = Depends(engineer_required)):
    """Hit Jira `/myself` to validate URL + credentials. Engineer-only."""
    config = JiraConfig.from_settings(refresh=True)
    client = JiraClient(config)
    if not client.is_configured():
        _raise_ticket_conflict("Jira provider is not configured")
    result = client.probe()
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail=str(result.get("error") or result.get("reason") or "Jira probe failed"))
    project_access = result.get("project_access")
    if isinstance(project_access, dict) and not project_access.get("ok"):
        raise HTTPException(
            status_code=409,
            detail=(
                f"Jira account connected but project {project_access.get('project_key')!s} "
                f"is not creatable for issue type {project_access.get('issue_type')!s}"
            ),
        )
    return json_safe(
        {
            "provider": "jira",
            "configured": True,
            **result,
        }
    )


@router.get("")
def list_tickets(
    cell_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    principal: Principal = Depends(viewer_required),
):
    rows = ChangeTicketsRepo.list_recent(limit=limit, status=status, cell_id=cell_id)
    return json_safe({"provider": ticket_provider(), "items": rows})


@router.get("/{ticket_id}")
def get_ticket(
    ticket_id: str,
    principal: Principal = Depends(viewer_required),
):
    row = ChangeTicketsRepo.get(ticket_id)
    if row is None:
        raise HTTPException(status_code=404, detail="ticket not found")
    return json_safe({"provider": ticket_provider(), "ticket": row})


@router.post("/{ticket_id}/refresh")
def refresh_ticket(
    ticket_id: str,
    principal: Principal = Depends(engineer_required),
):
    """Re-pull the linked Jira issue and sync local status + cached fields."""
    row = ChangeTicketsRepo.get(ticket_id)
    if row is None:
        raise HTTPException(status_code=404, detail="ticket not found")
    jira_key = _jira_key_from_evidence(row)
    client = JiraClient(JiraConfig.from_settings(refresh=True))
    if not client.is_configured():
        _raise_ticket_conflict("Jira provider is not configured")
    if not jira_key:
        _raise_ticket_conflict("ticket is not linked to a Jira issue")
    try:
        status = client.get_issue_status(jira_key)
    except Exception as exc:  # network / auth / 404
        logger.warning("Jira refresh failed for %s: %s", jira_key, exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    updated = ChangeTicketsRepo.update_jira_status(ticket_id, status)
    return json_safe(
        {
            "ticket": updated or row,
            "refreshed": True,
            "jira_status": status,
        }
    )


@router.post("/{ticket_id}/close")
def close_ticket(
    ticket_id: str,
    principal: Principal = Depends(engineer_required),
):
    row = ChangeTicketsRepo.get(ticket_id)
    if row is None:
        raise HTTPException(status_code=404, detail="ticket not found")
    if row.get("status") == "CLOSED":
        return json_safe({"ticket": row, "transitioned": False, "reason": "already_closed"})

    jira_key = _jira_key_from_evidence(row)
    client = JiraClient(JiraConfig.from_settings(refresh=True))
    transition_result: dict | None = None
    upstream_error: str | None = None

    if jira_key and client.is_configured():
        try:
            transition_result = client.transition_to_done(
                jira_key,
                comment=f"Closed from QoS Buddy by {principal.token}",
            )
        except Exception as exc:
            logger.warning("Jira transition failed for %s: %s", jira_key, exc)
            upstream_error = str(exc)

    jira_status = (transition_result or {}).get("status") if transition_result else None
    closed = ChangeTicketsRepo.close(ticket_id, principal.token, jira_status=jira_status)
    if closed is None:
        raise HTTPException(status_code=404, detail="ticket not found")
    return json_safe(
        {
            "ticket": closed,
            "transitioned": bool(transition_result and transition_result.get("transitioned")),
            "transition": transition_result,
            "upstream_error": upstream_error,
        }
    )
