"""
Role-based access control for bus streams.

The gateway never streams data a role isn't allowed to see — enforced at
subscription time so the browser cannot ask for streams it shouldn't.

Display vs. technical labels are also chosen here: the NOC views get the
NOC-language version; the AI Engineer view gets the technical artifacts.
"""

from __future__ import annotations

from typing import Any

from contracts.schemas import Role, StreamName

# Streams every role can subscribe to (read-only).
_ROLE_STREAMS: dict[Role, frozenset[StreamName]] = {
    Role.NOC_VIEWER: frozenset(
        {
            StreamName.METRICS_RAW,
            StreamName.ALERTS,
            StreamName.INSIGHT,
            StreamName.ACTION_EXECUTED,
            StreamName.JIRA_TICKETS,
        }
    ),
    Role.NOC_EXECUTIVE: frozenset(
        {
            StreamName.METRICS_RAW,
            StreamName.ALERTS,
            StreamName.DIAGNOSIS,
            StreamName.INSIGHT,
            StreamName.ACTION_PROPOSED,
            StreamName.ACTION_EXECUTED,
            StreamName.AUDIT,
            StreamName.JIRA_OUTBOX,
            StreamName.JIRA_TICKETS,
        }
    ),
    Role.AI_ENGINEER: frozenset(
        {
            StreamName.METRICS_RAW,
            StreamName.ALERTS,
            StreamName.DIAGNOSIS,
            StreamName.INSIGHT,
            StreamName.ACTION_PROPOSED,
            StreamName.ACTION_EXECUTED,
            StreamName.AUDIT,
            StreamName.JIRA_OUTBOX,
            StreamName.JIRA_TICKETS,
            StreamName.DLQ,
        }
    ),
    Role.SITE_ADMIN: frozenset(
        {
            StreamName.METRICS_RAW,
            StreamName.ALERTS,
            StreamName.DIAGNOSIS,
            StreamName.INSIGHT,
            StreamName.ACTION_PROPOSED,
            StreamName.ACTION_EXECUTED,
            StreamName.AUDIT,
            StreamName.DLQ,
            StreamName.JIRA_OUTBOX,
            StreamName.JIRA_TICKETS,
        }
    ),
}

# Fields removed from payload when shaping for NOC roles.
# These are technical artifacts that exist for engineers only.
_NOC_HIDDEN_FIELDS: frozenset[str] = frozenset(
    {
        "technical_label",
        "technical_name",
        "trace_id",
        "causation_id",
        "playbook_params",
        "playbook_id",
        "raw_features",
        "feature_importance",
        "shap_values",
        "embedding",
        "model_version",
    }
)


def can_subscribe(role: Role, stream: StreamName) -> bool:
    return stream in _ROLE_STREAMS.get(role, frozenset())


def allowed_streams(role: Role) -> list[str]:
    return sorted(s.value for s in _ROLE_STREAMS.get(role, frozenset()))


def shape_payload(role: Role, payload: dict[str, Any]) -> dict[str, Any]:
    """Strip technical fields for NOC-facing roles. Engineer/admin see everything."""
    if role in (Role.AI_ENGINEER, Role.SITE_ADMIN):
        return payload

    return _strip(payload)


def _strip(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: _strip(v) for k, v in value.items() if k not in _NOC_HIDDEN_FIELDS
        }
    if isinstance(value, list):
        return [_strip(v) for v in value]
    return value
