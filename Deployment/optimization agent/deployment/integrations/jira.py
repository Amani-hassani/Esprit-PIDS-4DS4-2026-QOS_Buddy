"""Jira REST client used by the agent loop and tickets API.

Configured via env vars (read once into `JiraSettings` in `deployment/core/settings.py`):

    JIRA_URL=https://company.atlassian.net
    JIRA_EMAIL=ops@company.com
    JIRA_TOKEN=...                              # API token
    JIRA_PROJECT_KEY=NOC
    JIRA_ISSUE_TYPE=Task                        # optional, default 'Task'
    JIRA_DONE_TRANSITIONS=Done,Close,Closed,Resolve,Resolve Issue   # optional
    JIRA_TIMEOUT_S=10                           # optional

When `JIRA_URL`/`JIRA_TOKEN` are missing the client stays in `local` mode and
`open_change_ticket()` falls back to the SQLite `change_tickets` table — that
lets us develop and demo without third-party state. Either way the dashboard
receives a ticket key + URL plus a `provider` field so it can render the right
badge.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import requests

from ..core.clock import utc_now_iso
from ..core.ids import short_id
from ..core.settings import JiraSettings, get_settings, reload_settings
from ..store.repos import ChangeTicketsRepo


logger = logging.getLogger("qos_buddy.jira")
NO_PROXY = {"http": "", "https": ""}


def _post_direct(*args, **kwargs):
    kwargs.setdefault("proxies", NO_PROXY)
    try:
        return requests.post(*args, **kwargs)
    except TypeError as exc:
        if "proxies" not in str(exc):
            raise
        kwargs.pop("proxies", None)
        return requests.post(*args, **kwargs)


def _get_direct(*args, **kwargs):
    kwargs.setdefault("proxies", NO_PROXY)
    try:
        return requests.get(*args, **kwargs)
    except TypeError as exc:
        if "proxies" not in str(exc):
            raise
        kwargs.pop("proxies", None)
        return requests.get(*args, **kwargs)


class JiraRequestError(RuntimeError):
    def __init__(self, *, operation: str, status_code: int | None, detail: str) -> None:
        self.operation = operation
        self.status_code = status_code
        self.detail = detail
        suffix = f" ({status_code})" if status_code is not None else ""
        super().__init__(f"Jira {operation} failed{suffix}: {detail}")


@dataclass(frozen=True)
class JiraConfig:
    url: str
    email: str
    token: str
    project_key: str
    issue_type: str = "Task"
    done_transitions: tuple[str, ...] = ("Done", "Close", "Closed", "Resolve", "Resolve Issue")
    timeout_s: float = 10.0

    @property
    def configured(self) -> bool:
        return bool(self.url and self.email and self.token and self.project_key)

    @classmethod
    def from_settings(
        cls,
        settings: JiraSettings | None = None,
        *,
        refresh: bool = False,
    ) -> "JiraConfig":
        s = settings or (reload_settings().jira if refresh else get_settings().jira)
        return cls(
            url=s.url,
            email=s.email,
            token=s.token,
            project_key=s.project_key,
            issue_type=s.issue_type,
            done_transitions=tuple(s.done_transitions),
            timeout_s=s.timeout_s,
        )

    @classmethod
    def from_env(cls) -> "JiraConfig":
        # Kept for backwards compatibility with code paths that still call
        # `from_env()` directly. Reads through the centralized Settings.
        return cls.from_settings()


def ticket_provider() -> str:
    return "jira" if JiraConfig.from_settings(refresh=True).configured else "local"


@dataclass
class JiraTicket:
    provider: str
    key: str
    url: str
    raw: dict[str, Any]


# Jira's status categories: "new" | "indeterminate" | "done". We map "done" to
# our local CLOSED state and everything else to OPEN.
_JIRA_DONE_CATEGORY = "done"


def _local_status_from_jira_category(category_key: str | None) -> str:
    if category_key and category_key.lower() == _JIRA_DONE_CATEGORY:
        return "CLOSED"
    return "OPEN"


class JiraClient:
    """Thin synchronous wrapper around the Jira Cloud REST API v3."""

    def __init__(self, config: JiraConfig | None = None, *, timeout_s: float | None = None) -> None:
        self.config = config or JiraConfig.from_settings()
        self.timeout_s = timeout_s if timeout_s is not None else self.config.timeout_s

    def is_configured(self) -> bool:
        return self.config.configured

    def _auth(self) -> tuple[str, str]:
        return (self.config.email, self.config.token)

    def _headers(self) -> dict[str, str]:
        return {"Accept": "application/json", "Content-Type": "application/json"}

    def _http_error_detail(self, response: requests.Response | None) -> str:
        if response is None:
            return "request failed without a Jira response"
        try:
            payload = response.json() if response.content else {}
        except Exception:
            payload = {}
        parts: list[str] = []
        if isinstance(payload, dict):
            error_messages = payload.get("errorMessages")
            if isinstance(error_messages, list):
                parts.extend(str(item) for item in error_messages if item)
            field_errors = payload.get("errors")
            if isinstance(field_errors, dict):
                parts.extend(f"{key}: {value}" for key, value in field_errors.items() if value)
        if not parts:
            text = response.text.strip() if response.text else ""
            if text:
                parts.append(text[:400])
        if not parts:
            parts.append(response.reason or "unknown Jira error")
        return "; ".join(parts)

    def _raise_for_status(self, response: requests.Response, operation: str) -> None:
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise JiraRequestError(
                operation=operation,
                status_code=response.status_code,
                detail=self._http_error_detail(response),
            ) from exc

    def _adf_paragraph(self, text: str) -> dict[str, Any]:
        return {
            "type": "paragraph",
            "content": [{"type": "text", "text": text}],
        }

    def _description(self, *, summary: str, body: str, evidence: list[str], kpi_lines: list[str]) -> dict[str, Any]:
        nodes: list[dict[str, Any]] = [self._adf_paragraph(summary)]
        if body:
            nodes.append(self._adf_paragraph(body))
        if evidence:
            nodes.append(self._adf_paragraph("Evidence:"))
            nodes.append(
                {
                    "type": "bulletList",
                    "content": [
                        {
                            "type": "listItem",
                            "content": [self._adf_paragraph(str(item))],
                        }
                        for item in evidence
                    ],
                }
            )
        if kpi_lines:
            nodes.append(self._adf_paragraph("KPI snapshot:"))
            nodes.append(
                {
                    "type": "bulletList",
                    "content": [
                        {
                            "type": "listItem",
                            "content": [self._adf_paragraph(str(item))],
                        }
                        for item in kpi_lines
                    ],
                }
            )
        return {"type": "doc", "version": 1, "content": nodes}

    def create_issue(
        self,
        *,
        summary: str,
        body: str,
        evidence: list[str],
        kpi_lines: list[str],
        labels: list[str] | None = None,
    ) -> JiraTicket:
        if not self.is_configured():
            raise RuntimeError("Jira is not configured")
        payload: dict[str, Any] = {
            "fields": {
                "project": {"key": self.config.project_key},
                "summary": summary[:240],
                "issuetype": {"name": self.config.issue_type},
                "description": self._description(
                    summary=summary, body=body, evidence=evidence, kpi_lines=kpi_lines
                ),
            }
        }
        if labels:
            payload["fields"]["labels"] = [str(label).replace(" ", "_") for label in labels]
        endpoint = f"{self.config.url}/rest/api/3/issue"
        response = _post_direct(
            endpoint,
            json=payload,
            auth=self._auth(),
            headers=self._headers(),
            timeout=self.timeout_s,
            proxies=NO_PROXY,
        )
        self._raise_for_status(response, "create_issue")
        data = response.json() if response.content else {}
        key = str(data.get("key") or "")
        url = f"{self.config.url}/browse/{key}" if key else self.config.url
        return JiraTicket(provider="jira", key=key, url=url, raw=data)

    def get_issue(self, issue_key: str) -> dict[str, Any]:
        """Fetch a single issue with status fields."""
        if not self.is_configured():
            raise RuntimeError("Jira is not configured")
        endpoint = f"{self.config.url}/rest/api/3/issue/{issue_key}"
        response = _get_direct(
            endpoint,
            params={"fields": "summary,status,resolution,updated"},
            auth=self._auth(),
            headers={"Accept": "application/json"},
            timeout=self.timeout_s,
            proxies=NO_PROXY,
        )
        self._raise_for_status(response, "get_issue")
        return response.json() if response.content else {}

    def get_issue_status(self, issue_key: str) -> dict[str, Any]:
        """Return a small dict describing the current status of the issue.

        Shape: {name, category_key, category_name, resolution, updated, local_status}
        """
        data = self.get_issue(issue_key)
        fields = data.get("fields", {}) if isinstance(data, dict) else {}
        status = fields.get("status") or {}
        category = status.get("statusCategory") or {}
        resolution = fields.get("resolution") or {}
        category_key = str(category.get("key") or "") or None
        return {
            "name": str(status.get("name") or "") or None,
            "category_key": category_key,
            "category_name": str(category.get("name") or "") or None,
            "resolution": str(resolution.get("name") or "") or None,
            "updated": str(fields.get("updated") or "") or None,
            "local_status": _local_status_from_jira_category(category_key),
        }

    def get_transitions(self, issue_key: str) -> list[dict[str, Any]]:
        """List the transitions available from the issue's current status."""
        if not self.is_configured():
            raise RuntimeError("Jira is not configured")
        endpoint = f"{self.config.url}/rest/api/3/issue/{issue_key}/transitions"
        response = _get_direct(
            endpoint,
            auth=self._auth(),
            headers={"Accept": "application/json"},
            timeout=self.timeout_s,
            proxies=NO_PROXY,
        )
        self._raise_for_status(response, "get_transitions")
        body = response.json() if response.content else {}
        items = body.get("transitions", []) if isinstance(body, dict) else []
        return [t for t in items if isinstance(t, dict)]

    def _pick_done_transition(self, transitions: list[dict[str, Any]]) -> dict[str, Any] | None:
        # Prefer transitions whose target status sits in the "done" category.
        for t in transitions:
            target = t.get("to") or {}
            cat = (target.get("statusCategory") or {}).get("key")
            if isinstance(cat, str) and cat.lower() == _JIRA_DONE_CATEGORY:
                return t
        # Otherwise, fall back to a configured name match.
        wanted = [name.strip().lower() for name in self.config.done_transitions if name.strip()]
        for t in transitions:
            name = str(t.get("name") or "").strip().lower()
            if name and name in wanted:
                return t
        return None

    def transition_to_done(self, issue_key: str, *, comment: str | None = None) -> dict[str, Any]:
        """Move an issue into a Done-category status. Returns the chosen transition + post-state."""
        if not self.is_configured():
            raise RuntimeError("Jira is not configured")
        # Already done? Don't fight Jira's transition graph.
        current = self.get_issue_status(issue_key)
        if current.get("category_key") == _JIRA_DONE_CATEGORY:
            return {"transitioned": False, "reason": "already_done", "status": current}
        transitions = self.get_transitions(issue_key)
        chosen = self._pick_done_transition(transitions)
        if chosen is None:
            available = [str(t.get("name") or "") for t in transitions]
            raise RuntimeError(
                f"no done-category transition available for {issue_key} (have: {', '.join(available) or 'none'})"
            )
        endpoint = f"{self.config.url}/rest/api/3/issue/{issue_key}/transitions"
        payload: dict[str, Any] = {"transition": {"id": str(chosen.get("id"))}}
        if comment:
            payload["update"] = {
                "comment": [
                    {
                        "add": {
                            "body": {
                                "type": "doc",
                                "version": 1,
                                "content": [self._adf_paragraph(comment)],
                            }
                        }
                    }
                ]
            }
        response = _post_direct(
            endpoint,
            json=payload,
            auth=self._auth(),
            headers=self._headers(),
            timeout=self.timeout_s,
            proxies=NO_PROXY,
        )
        self._raise_for_status(response, "transition_to_done")
        post = self.get_issue_status(issue_key)
        return {
            "transitioned": True,
            "transition_id": str(chosen.get("id")),
            "transition_name": str(chosen.get("name") or ""),
            "status": post,
        }

    def probe(self) -> dict[str, Any]:
        """Hit `/myself` to validate URL + credentials. Used by `/api/tickets/probe`."""
        if not self.is_configured():
            return {"ok": False, "reason": "not_configured"}
        endpoint = f"{self.config.url}/rest/api/3/myself"
        try:
            response = _get_direct(
                endpoint,
                auth=self._auth(),
                headers={"Accept": "application/json"},
                timeout=self.timeout_s,
                proxies=NO_PROXY,
            )
            response.raise_for_status()
            data = response.json() if response.content else {}
            project_access = self.project_create_access()
            return {
                "ok": True,
                "account_id": str(data.get("accountId") or "") or None,
                "display_name": str(data.get("displayName") or "") or None,
                "project_key": self.config.project_key,
                "issue_type": self.config.issue_type,
                "project_access": project_access,
            }
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            return {
                "ok": False,
                "reason": f"http_{status}",
                "error": self._http_error_detail(exc.response),
            }
        except Exception as exc:
            return {"ok": False, "reason": "network", "error": str(exc)}

    def project_create_access(self) -> dict[str, Any]:
        if not self.is_configured():
            return {"ok": False, "reason": "not_configured"}
        endpoint = f"{self.config.url}/rest/api/3/issue/createmeta"
        response = _get_direct(
            endpoint,
            auth=self._auth(),
            headers={"Accept": "application/json"},
            params={"projectKeys": self.config.project_key, "expand": "projects.issuetypes"},
            timeout=self.timeout_s,
            proxies=NO_PROXY,
        )
        self._raise_for_status(response, "project_create_access")
        data = response.json() if response.content else {}
        projects = data.get("projects", []) if isinstance(data, dict) else []
        if not projects:
            return {
                "ok": False,
                "reason": "project_not_creatable",
                "project_key": self.config.project_key,
                "issue_type": self.config.issue_type,
                "available_issue_types": [],
            }
        project = projects[0]
        issue_types = [item for item in project.get("issuetypes", []) if isinstance(item, dict)]
        available_issue_types = [str(item.get("name") or "") for item in issue_types if item.get("name")]
        issue_type_ok = self.config.issue_type in available_issue_types
        return {
            "ok": issue_type_ok,
            "reason": "ok" if issue_type_ok else "issue_type_not_creatable",
            "project_key": str(project.get("key") or self.config.project_key),
            "project_name": str(project.get("name") or "") or None,
            "issue_type": self.config.issue_type,
            "available_issue_types": available_issue_types,
        }


def _kpi_lines(kpis: dict[str, Any]) -> list[str]:
    keep = (
        ("rssi_dbm", " dBm", 1),
        ("sinr_db", " dB", 1),
        ("throughput_mbps", " Mbps", 1),
        ("latency_ms", " ms", 0),
        ("packet_loss_pct", " %", 2),
        ("jitter_ms", " ms", 1),
    )
    out: list[str] = []
    for name, unit, digits in keep:
        if name not in kpis or kpis[name] is None:
            continue
        try:
            out.append(f"{name}: {float(kpis[name]):.{digits}f}{unit}")
        except (TypeError, ValueError):
            continue
    return out


def open_change_ticket(
    *,
    decision_id: str | None,
    cell_id: str,
    action_code: str,
    summary: str,
    reasoning: str,
    evidence: list[str],
    kpis: dict[str, Any],
    risk_level: str,
    opened_by: str,
    extra_labels: list[str] | None = None,
) -> dict[str, Any]:
    """Create a change ticket against Jira (if configured) or the local table.

    Always persists a row in `change_tickets` so the audit trail and tickets UI
    work whether or not the upstream is reachable. The returned dict carries
    `provider`, `ticket_key`, `ticket_url`, and `local_id` so the agent loop can
    relay them to the dashboard.
    """
    config = JiraConfig.from_settings(refresh=True)
    labels = ["qos-buddy", action_code.lower(), f"risk-{risk_level.lower()}"]
    if extra_labels:
        labels.extend(extra_labels)

    body_lines = [
        f"Cell: {cell_id}",
        f"Action: {action_code}",
        f"Risk: {risk_level}",
        f"Decision: {decision_id or 'n/a'}",
        "",
        "Reasoning:",
        reasoning or "(none)",
    ]
    body = "\n".join(body_lines)
    kpi_lines = _kpi_lines(kpis)

    provider = "jira" if config.configured else "local"
    ticket_key: str | None = None
    ticket_url: str | None = None
    upstream_error: str | None = None
    raw: dict[str, Any] = {}

    if config.configured:
        try:
            ticket = JiraClient(config).create_issue(
                summary=summary,
                body=body,
                evidence=evidence,
                kpi_lines=kpi_lines,
                labels=labels,
            )
            ticket_key = ticket.key
            ticket_url = ticket.url
            raw = ticket.raw
        except Exception as exc:
            logger.warning("Jira create_issue failed: %s", exc)
            provider = "local"
            upstream_error = str(exc)

    if provider == "local":
        ticket_key = ticket_key or f"NOC-{short_id('lt').upper()}"
        ticket_url = None

    evidence_envelope = {
        "provider": provider,
        "ticket_key": ticket_key,
        "ticket_url": ticket_url,
        "labels": labels,
        "kpi_lines": kpi_lines,
        "evidence": evidence,
        "reasoning": reasoning,
        "risk_level": risk_level,
        "opened_at": utc_now_iso(),
        "upstream_error": upstream_error,
        "raw": raw,
    }

    local_id = ChangeTicketsRepo.insert(
        decision_id=decision_id,
        cell_id=cell_id,
        action_code=action_code,
        summary=summary,
        evidence=evidence_envelope,
        opened_by=opened_by,
    )

    return {
        "provider": provider,
        "ticket_key": ticket_key,
        "ticket_url": ticket_url,
        "local_id": local_id,
        "upstream_error": upstream_error,
    }
