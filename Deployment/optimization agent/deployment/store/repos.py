from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from ..core.clock import utc_now_iso
from ..core.clock import parse_iso, utc_now
from ..core.ids import short_id, ulid
from ..core.settings import get_settings
from .db import cursor, read_cursor, row_to_dict, rows_to_list


def _dump(value: Any) -> str:
    return json.dumps(value, default=str, sort_keys=True)


def _load(text: str | None, default: Any) -> Any:
    if not text:
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return default


@dataclass
class DecisionRow:
    id: str
    created_at: str
    cell_id: str
    root_cause: str
    rc_confidence: float
    selected_action: str
    selected_source: str
    hybrid_score: float
    gate_decision: str
    gate_reason: str
    risk_level: str
    impact_radius: str
    auto_executed: bool
    principal: str | None
    evidence: list[str]
    candidates: list[dict[str, Any]]
    validators: list[dict[str, Any]]
    kpi_before: dict[str, Any]
    kpi_after: dict[str, Any] | None
    health_before: float | None
    health_after: float | None
    mlflow_run_id: str | None


def _hydrate_decision(row: dict[str, Any]) -> DecisionRow:
    return DecisionRow(
        id=row["id"],
        created_at=row["created_at"],
        cell_id=row["cell_id"],
        root_cause=row["root_cause"],
        rc_confidence=float(row["rc_confidence"]),
        selected_action=row["selected_action"],
        selected_source=row["selected_source"],
        hybrid_score=float(row["hybrid_score"]),
        gate_decision=row["gate_decision"],
        gate_reason=row["gate_reason"],
        risk_level=row["risk_level"],
        impact_radius=row["impact_radius"],
        auto_executed=bool(row["auto_executed"]),
        principal=row["principal"],
        evidence=_load(row["evidence_json"], []),
        candidates=_load(row["candidates_json"], []),
        validators=_load(row["validators_json"], []),
        kpi_before=_load(row["kpi_before_json"], {}),
        kpi_after=_load(row["kpi_after_json"], None),
        health_before=row["health_before"],
        health_after=row["health_after"],
        mlflow_run_id=row["mlflow_run_id"],
    )


class DecisionsRepo:
    @staticmethod
    def insert(
        *,
        cell_id: str,
        root_cause: str,
        rc_confidence: float,
        selected_action: str,
        selected_source: str,
        hybrid_score: float,
        gate_decision: str,
        gate_reason: str,
        risk_level: str,
        impact_radius: str,
        auto_executed: bool,
        principal: str | None,
        evidence: list[str],
        candidates: list[dict[str, Any]],
        validators: list[dict[str, Any]],
        kpi_before: dict[str, Any],
        kpi_after: dict[str, Any] | None,
        health_before: float | None,
        health_after: float | None,
        mlflow_run_id: str | None,
    ) -> str:
        decision_id = short_id("dec")
        with cursor() as cur:
            cur.execute(
                """
                INSERT INTO decisions (
                    id, created_at, cell_id, root_cause, rc_confidence,
                    selected_action, selected_source, hybrid_score,
                    gate_decision, gate_reason, risk_level, impact_radius,
                    auto_executed, principal, evidence_json, candidates_json,
                    validators_json, kpi_before_json, kpi_after_json,
                    health_before, health_after, mlflow_run_id
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    decision_id,
                    utc_now_iso(),
                    cell_id,
                    root_cause,
                    rc_confidence,
                    selected_action,
                    selected_source,
                    hybrid_score,
                    gate_decision,
                    gate_reason,
                    risk_level,
                    impact_radius,
                    1 if auto_executed else 0,
                    principal,
                    _dump(evidence),
                    _dump(candidates),
                    _dump(validators),
                    _dump(kpi_before),
                    _dump(kpi_after) if kpi_after is not None else None,
                    health_before,
                    health_after,
                    mlflow_run_id,
                ),
            )
        return decision_id

    @staticmethod
    def set_post_execution(decision_id: str, kpi_after: dict[str, Any], health_after: float) -> None:
        with cursor() as cur:
            cur.execute(
                "UPDATE decisions SET kpi_after_json = ?, health_after = ? WHERE id = ?",
                (_dump(kpi_after), health_after, decision_id),
            )

    @staticmethod
    def update_gate_state(
        decision_id: str,
        *,
        gate_decision: str,
        gate_reason: str,
        auto_executed: bool,
    ) -> None:
        with cursor() as cur:
            cur.execute(
                """
                UPDATE decisions
                SET gate_decision = ?, gate_reason = ?, auto_executed = ?
                WHERE id = ?
                """,
                (gate_decision, gate_reason, 1 if auto_executed else 0, decision_id),
            )

    @staticmethod
    def get(decision_id: str) -> DecisionRow | None:
        with read_cursor() as cur:
            cur.execute("SELECT * FROM decisions WHERE id = ?", (decision_id,))
            row = row_to_dict(cur.fetchone())
        return _hydrate_decision(row) if row else None

    @staticmethod
    def list_recent(limit: int = 50, cell_id: str | None = None, gate: str | None = None) -> list[DecisionRow]:
        sql = "SELECT * FROM decisions"
        params: list[Any] = []
        clauses = []
        if cell_id:
            clauses.append("cell_id = ?")
            params.append(cell_id)
        if gate:
            clauses.append("gate_decision = ?")
            params.append(gate)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with read_cursor() as cur:
            cur.execute(sql, params)
            rows = rows_to_list(cur.fetchall())
        return [_hydrate_decision(r) for r in rows]


class ToolCallsRepo:
    @staticmethod
    def insert(
        *,
        decision_id: str,
        seq: int,
        tool_name: str,
        input_payload: dict[str, Any],
        output_payload: dict[str, Any],
        duration_ms: float,
        error: str | None = None,
    ) -> str:
        call_id = short_id("tc")
        with cursor() as cur:
            cur.execute(
                """
                INSERT INTO tool_calls (id, decision_id, seq, created_at, tool_name,
                                        input_json, output_json, duration_ms, error)
                VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (
                    call_id,
                    decision_id,
                    seq,
                    utc_now_iso(),
                    tool_name,
                    _dump(input_payload),
                    _dump(output_payload),
                    duration_ms,
                    error,
                ),
            )
        return call_id

    @staticmethod
    def for_decision(decision_id: str) -> list[dict[str, Any]]:
        with read_cursor() as cur:
            cur.execute(
                "SELECT * FROM tool_calls WHERE decision_id = ? ORDER BY seq ASC",
                (decision_id,),
            )
            rows = rows_to_list(cur.fetchall())
        for row in rows:
            row["input"] = _load(row.pop("input_json"), {})
            row["output"] = _load(row.pop("output_json"), {})
        return rows


class ReasoningsRepo:
    @staticmethod
    def insert(
        *,
        decision_id: str | None,
        kind: str,
        prompt_hash: str,
        prompt_version: str,
        model: str,
        available: bool,
        chosen_action: str | None,
        confidence: float | None,
        reasoning_text: str,
        raw: dict[str, Any],
        latency_ms: float | None,
        error: str | None,
    ) -> str:
        reasoning_id = short_id("rsn")
        with cursor() as cur:
            cur.execute(
                """
                INSERT INTO reasonings (id, decision_id, created_at, kind,
                                        prompt_hash, prompt_version, model, available,
                                        chosen_action, confidence, reasoning_text, raw_json,
                                        latency_ms, error)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    reasoning_id,
                    decision_id,
                    utc_now_iso(),
                    kind,
                    prompt_hash,
                    prompt_version,
                    model,
                    1 if available else 0,
                    chosen_action,
                    confidence,
                    reasoning_text,
                    _dump(raw),
                    latency_ms,
                    error,
                ),
            )
        return reasoning_id

    @staticmethod
    def update_text(reasoning_id: str, reasoning_text: str) -> None:
        with cursor() as cur:
            cur.execute(
                "UPDATE reasonings SET reasoning_text = ? WHERE id = ?",
                (reasoning_text, reasoning_id),
            )

    @staticmethod
    def list_recent(
        limit: int = 50,
        kind: str | None = None,
        after_id: str | None = None,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM reasonings"
        clauses: list[str] = []
        params: list[Any] = []
        if kind:
            clauses.append("kind = ?")
            params.append(kind)
        if after_id:
            with read_cursor() as cur:
                cur.execute("SELECT created_at, id FROM reasonings WHERE id = ?", (after_id,))
                cursor_row = row_to_dict(cur.fetchone())
            if cursor_row:
                clauses.append("(created_at < ? OR (created_at = ? AND id < ?))")
                params.extend([cursor_row["created_at"], cursor_row["created_at"], cursor_row["id"]])
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
        params.append(limit)
        with read_cursor() as cur:
            cur.execute(sql, params)
            rows = rows_to_list(cur.fetchall())
        for row in rows:
            row["raw"] = _load(row.pop("raw_json"), {})
            row["available"] = bool(row.get("available"))
        return rows

    @staticmethod
    def get(reasoning_id: str) -> dict[str, Any] | None:
        with read_cursor() as cur:
            cur.execute("SELECT * FROM reasonings WHERE id = ?", (reasoning_id,))
            row = row_to_dict(cur.fetchone())
        if row is None:
            return None
        row["raw"] = _load(row.pop("raw_json"), {})
        row["available"] = bool(row.get("available"))
        return row

    @staticmethod
    def for_decision(decision_id: str, limit: int = 10) -> list[dict[str, Any]]:
        with read_cursor() as cur:
            cur.execute(
                "SELECT * FROM reasonings WHERE decision_id = ? ORDER BY created_at DESC LIMIT ?",
                (decision_id, limit),
            )
            rows = rows_to_list(cur.fetchall())
        for row in rows:
            row["raw"] = _load(row.pop("raw_json"), {})
            row["available"] = bool(row.get("available"))
        return rows


class ApprovalsRepo:
    @staticmethod
    def insert(*, decision_id: str, sla_deadline_iso: str) -> str:
        approval_id = short_id("appr")
        with cursor() as cur:
            cur.execute(
                """
                INSERT INTO approvals (id, decision_id, created_at, sla_deadline, status)
                VALUES (?, ?, ?, ?, 'PENDING_APPROVAL')
                """,
                (approval_id, decision_id, utc_now_iso(), sla_deadline_iso),
            )
        return approval_id

    @staticmethod
    def decide(approval_id: str, status: str, actor: str, reason: str | None = None) -> dict[str, Any] | None:
        if status not in {"APPROVED", "REJECTED", "DEFERRED", "EXPIRED"}:
            raise ValueError(f"invalid approval status: {status}")
        with cursor() as cur:
            cur.execute(
                """
                UPDATE approvals
                SET status = ?, decided_at = ?, actor = ?, reason = COALESCE(?, reason)
                WHERE id = ? AND status = 'PENDING_APPROVAL'
                """,
                (status, utc_now_iso(), actor, reason, approval_id),
            )
            if cur.rowcount == 0:
                cur.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,))
                return row_to_dict(cur.fetchone())
            cur.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,))
            return row_to_dict(cur.fetchone())

    @staticmethod
    def pending(limit: int = 100) -> list[dict[str, Any]]:
        with read_cursor() as cur:
            cur.execute(
                """
                SELECT a.*, d.cell_id, d.selected_action, d.root_cause, d.risk_level,
                       d.gate_reason, d.health_before
                FROM approvals a
                JOIN decisions d ON d.id = a.decision_id
                WHERE a.status = 'PENDING_APPROVAL'
                ORDER BY a.sla_deadline ASC
                LIMIT ?
                """,
                (limit,),
            )
            return rows_to_list(cur.fetchall())

    @staticmethod
    def find_overdue(now_iso: str) -> list[dict[str, Any]]:
        with read_cursor() as cur:
            cur.execute(
                """
                SELECT a.*, d.cell_id, d.selected_action, d.risk_level
                FROM approvals a
                JOIN decisions d ON d.id = a.decision_id
                WHERE a.status = 'PENDING_APPROVAL' AND a.sla_deadline <= ?
                """,
                (now_iso,),
            )
            return rows_to_list(cur.fetchall())

    @staticmethod
    def find_untouched(threshold_iso: str) -> list[dict[str, Any]]:
        """Return approvals still PENDING that were created at/before threshold_iso."""
        with read_cursor() as cur:
            cur.execute(
                """
                SELECT a.*, d.cell_id, d.selected_action, d.risk_level, d.root_cause
                FROM approvals a
                JOIN decisions d ON d.id = a.decision_id
                WHERE a.status = 'PENDING_APPROVAL' AND a.created_at <= ?
                """,
                (threshold_iso,),
            )
            return rows_to_list(cur.fetchall())

    @staticmethod
    def get(approval_id: str) -> dict[str, Any] | None:
        with read_cursor() as cur:
            cur.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,))
            return row_to_dict(cur.fetchone())

    @staticmethod
    def for_decision(decision_id: str) -> dict[str, Any] | None:
        with read_cursor() as cur:
            cur.execute(
                "SELECT * FROM approvals WHERE decision_id = ? ORDER BY created_at DESC LIMIT 1",
                (decision_id,),
            )
            return row_to_dict(cur.fetchone())


class AlertsRepo:
    @staticmethod
    def insert(
        *,
        severity: str,
        kind: str,
        subject: str,
        body: str,
        approval_id: str | None = None,
        decision_id: str | None = None,
    ) -> str:
        alert_id = short_id("al")
        with cursor() as cur:
            cur.execute(
                """
                INSERT INTO alerts (id, created_at, severity, kind, subject, body,
                                    approval_id, decision_id, acknowledged)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (alert_id, utc_now_iso(), severity, kind, subject, body, approval_id, decision_id),
            )
        return alert_id

    @staticmethod
    def exists_for_approval(approval_id: str, kind: str) -> bool:
        with read_cursor() as cur:
            cur.execute(
                "SELECT 1 FROM alerts WHERE approval_id = ? AND kind = ? LIMIT 1",
                (approval_id, kind),
            )
            return cur.fetchone() is not None

    @staticmethod
    def acknowledge(alert_id: str, actor: str) -> dict[str, Any] | None:
        with cursor() as cur:
            cur.execute(
                """
                UPDATE alerts SET acknowledged = 1, acknowledged_at = ?, acknowledged_by = ?
                WHERE id = ? AND acknowledged = 0
                """,
                (utc_now_iso(), actor, alert_id),
            )
            cur.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,))
            return row_to_dict(cur.fetchone())

    @staticmethod
    def list_recent(limit: int = 50, unacknowledged_only: bool = False) -> list[dict[str, Any]]:
        sql = "SELECT * FROM alerts"
        params: list[Any] = []
        if unacknowledged_only:
            sql += " WHERE acknowledged = 0"
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with read_cursor() as cur:
            cur.execute(sql, params)
            return rows_to_list(cur.fetchall())


class ChangeTicketsRepo:
    @staticmethod
    def insert(
        *,
        decision_id: str | None,
        cell_id: str,
        action_code: str,
        summary: str,
        evidence: dict[str, Any],
        opened_by: str,
    ) -> str:
        ticket_id = short_id("tkt")
        with cursor() as cur:
            cur.execute(
                """
                INSERT INTO change_tickets (id, created_at, decision_id, cell_id,
                                            action_code, summary, evidence_json, opened_by, status)
                VALUES (?,?,?,?,?,?,?,?, 'OPEN')
                """,
                (
                    ticket_id,
                    utc_now_iso(),
                    decision_id,
                    cell_id,
                    action_code,
                    summary,
                    _dump(evidence),
                    opened_by,
                ),
            )
        return ticket_id

    @staticmethod
    def list_recent(limit: int = 50, status: str | None = None, cell_id: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM change_tickets"
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if cell_id:
            clauses.append("cell_id = ?")
            params.append(cell_id)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with read_cursor() as cur:
            cur.execute(sql, params)
            rows = rows_to_list(cur.fetchall())
        for row in rows:
            row["evidence"] = _load(row.pop("evidence_json"), {})
        return rows

    @staticmethod
    def get(ticket_id: str) -> dict[str, Any] | None:
        with read_cursor() as cur:
            cur.execute("SELECT * FROM change_tickets WHERE id = ?", (ticket_id,))
            row = row_to_dict(cur.fetchone())
        if row is None:
            return None
        row["evidence"] = _load(row.pop("evidence_json"), {})
        return row

    @staticmethod
    def close(ticket_id: str, actor: str, *, jira_status: dict[str, Any] | None = None) -> dict[str, Any] | None:
        with cursor() as cur:
            cur.execute("SELECT evidence_json FROM change_tickets WHERE id = ?", (ticket_id,))
            current = row_to_dict(cur.fetchone())
            if current is None:
                return None
            evidence = _load(current.get("evidence_json"), {}) or {}
            evidence["closed_by"] = actor
            evidence["closed_at"] = utc_now_iso()
            if jira_status is not None:
                evidence["jira_status"] = jira_status
            cur.execute(
                "UPDATE change_tickets SET status = 'CLOSED', evidence_json = ? WHERE id = ?",
                (_dump(evidence), ticket_id),
            )
            cur.execute("SELECT * FROM change_tickets WHERE id = ?", (ticket_id,))
            row = row_to_dict(cur.fetchone())
        if row is not None:
            row["evidence"] = _load(row.pop("evidence_json"), {})
        return row

    @staticmethod
    def update_jira_status(ticket_id: str, jira_status: dict[str, Any]) -> dict[str, Any] | None:
        """Refresh the cached Jira state on a ticket and sync the local status column.

        `jira_status` should be the dict returned by `JiraClient.get_issue_status()`.
        We mirror its `local_status` (OPEN/CLOSED) onto the row so list filters
        stay correct without a second round-trip.
        """
        with cursor() as cur:
            cur.execute("SELECT evidence_json, status FROM change_tickets WHERE id = ?", (ticket_id,))
            current = row_to_dict(cur.fetchone())
            if current is None:
                return None
            evidence = _load(current.get("evidence_json"), {}) or {}
            evidence["jira_status"] = jira_status
            evidence["jira_refreshed_at"] = utc_now_iso()
            new_status = str(jira_status.get("local_status") or current.get("status") or "OPEN")
            cur.execute(
                "UPDATE change_tickets SET status = ?, evidence_json = ? WHERE id = ?",
                (new_status, _dump(evidence), ticket_id),
            )
            cur.execute("SELECT * FROM change_tickets WHERE id = ?", (ticket_id,))
            row = row_to_dict(cur.fetchone())
        if row is not None:
            row["evidence"] = _load(row.pop("evidence_json"), {})
        return row

    @staticmethod
    def for_decision(decision_id: str) -> list[dict[str, Any]]:
        with read_cursor() as cur:
            cur.execute(
                "SELECT * FROM change_tickets WHERE decision_id = ? ORDER BY created_at DESC",
                (decision_id,),
            )
            rows = rows_to_list(cur.fetchall())
        for row in rows:
            row["evidence"] = _load(row.pop("evidence_json"), {})
        return rows


class PromptRegistryRepo:
    @staticmethod
    def upsert(*, prompt_hash: str, prompt_name: str, prompt_version: str, template: str) -> None:
        with cursor() as cur:
            cur.execute(
                """
                INSERT INTO prompt_registry (prompt_hash, prompt_name, prompt_version, template, created_at)
                VALUES (?,?,?,?,?)
                ON CONFLICT(prompt_hash) DO NOTHING
                """,
                (prompt_hash, prompt_name, prompt_version, template, utc_now_iso()),
            )

    @staticmethod
    def all() -> list[dict[str, Any]]:
        with read_cursor() as cur:
            cur.execute(
                "SELECT prompt_hash, prompt_name, prompt_version, created_at, LENGTH(template) AS size FROM prompt_registry ORDER BY prompt_name"
            )
            return rows_to_list(cur.fetchall())


class LLMCacheRepo:
    @staticmethod
    def get(key: str) -> dict[str, Any] | None:
        with cursor() as cur:
            cur.execute("SELECT * FROM llm_cache WHERE key = ?", (key,))
            row = row_to_dict(cur.fetchone())
            if row is None:
                return None
            cur.execute("UPDATE llm_cache SET hits = hits + 1 WHERE key = ?", (key,))
            row["response"] = _load(row.pop("response_json"), {})
            return row

    @staticmethod
    def put(*, key: str, prompt_hash: str, model: str, response: dict[str, Any]) -> None:
        with cursor() as cur:
            cur.execute(
                """
                INSERT INTO llm_cache (key, prompt_hash, model, response_json, created_at, hits)
                VALUES (?,?,?,?,?,0)
                ON CONFLICT(key) DO UPDATE SET response_json = excluded.response_json, created_at = excluded.created_at
                """,
                (key, prompt_hash, model, _dump(response), utc_now_iso()),
            )

    @staticmethod
    def stats() -> dict[str, Any]:
        with read_cursor() as cur:
            cur.execute("SELECT COUNT(*) AS entries, COALESCE(SUM(hits), 0) AS total_hits FROM llm_cache")
            return row_to_dict(cur.fetchone()) or {"entries": 0, "total_hits": 0}


class SessionsRepo:
    @staticmethod
    def create(*, principal_token: str, principal_role: str) -> dict[str, Any]:
        session_id = ulid()
        now = utc_now()
        expires_at = now + timedelta(seconds=float(get_settings().api.session_ttl_s))
        row = {
            "id": session_id,
            "created_at": now.isoformat(),
            "last_seen_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
            "revoked_at": None,
            "revoked_by": None,
            "principal_token": principal_token,
            "principal_role": principal_role,
        }
        with cursor() as cur:
            cur.execute(
                """
                INSERT INTO sessions (
                    id, created_at, last_seen_at, expires_at, revoked_at, revoked_by, principal_token, principal_role
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["id"],
                    row["created_at"],
                    row["last_seen_at"],
                    row["expires_at"],
                    row["revoked_at"],
                    row["revoked_by"],
                    row["principal_token"],
                    row["principal_role"],
                ),
            )
        return row

    @staticmethod
    def get_active(session_id: str, *, touch: bool = False) -> dict[str, Any] | None:
        with cursor() if touch else read_cursor() as cur:
            cur.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
            row = row_to_dict(cur.fetchone())
            if row is None:
                return None
            if row.get("revoked_at"):
                return None
            expires_at = parse_iso(row.get("expires_at"))
            if expires_at is None or expires_at <= utc_now():
                return None
            if touch:
                now = utc_now_iso()
                cur.execute("UPDATE sessions SET last_seen_at = ? WHERE id = ?", (now, session_id))
                row["last_seen_at"] = now
            return row

    @staticmethod
    def revoke(session_id: str, *, actor: str) -> dict[str, Any] | None:
        with cursor() as cur:
            cur.execute(
                """
                UPDATE sessions
                SET revoked_at = COALESCE(revoked_at, ?), revoked_by = COALESCE(revoked_by, ?)
                WHERE id = ?
                """,
                (utc_now_iso(), actor, session_id),
            )
            cur.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
            return row_to_dict(cur.fetchone())

    @staticmethod
    def list_active(limit: int = 100) -> list[dict[str, Any]]:
        with read_cursor() as cur:
            cur.execute(
                """
                SELECT id, created_at, last_seen_at, expires_at, principal_role
                FROM sessions
                WHERE revoked_at IS NULL
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            )
            rows = rows_to_list(cur.fetchall())
        now = utc_now()
        return [row for row in rows if (parse_iso(row.get("expires_at")) or now) > now]


class MonitoringSnapshotsRepo:
    @staticmethod
    def insert(
        *,
        observed_at: str,
        source_system: str,
        zone_id: str,
        node_id: str,
        cell_id: str,
        payload: dict[str, Any],
    ) -> str:
        snapshot_id = short_id("mon")
        with cursor() as cur:
            cur.execute(
                """
                INSERT INTO monitoring_snapshots (
                    id, received_at, observed_at, source_system, zone_id, node_id, cell_id, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    utc_now_iso(),
                    observed_at,
                    source_system,
                    zone_id,
                    node_id,
                    cell_id,
                    _dump(payload),
                ),
            )
        return snapshot_id

    @staticmethod
    def latest(cell_id: str | None = None) -> dict[str, Any] | None:
        sql = "SELECT * FROM monitoring_snapshots"
        params: list[Any] = []
        if cell_id:
            sql += " WHERE cell_id = ?"
            params.append(cell_id)
        sql += " ORDER BY observed_at DESC, received_at DESC LIMIT 1"
        with read_cursor() as cur:
            cur.execute(sql, params)
            row = row_to_dict(cur.fetchone())
        if row is None:
            return None
        row["payload"] = _load(row.pop("payload_json"), {})
        return row

    @staticmethod
    def list_recent(limit: int = 100, cell_id: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM monitoring_snapshots"
        params: list[Any] = []
        if cell_id:
            sql += " WHERE cell_id = ?"
            params.append(cell_id)
        sql += " ORDER BY observed_at DESC, received_at DESC LIMIT ?"
        params.append(limit)
        with read_cursor() as cur:
            cur.execute(sql, params)
            rows = rows_to_list(cur.fetchall())
        for row in rows:
            row["payload"] = _load(row.pop("payload_json"), {})
        return rows

    @staticmethod
    def latest_per_cell(limit: int = 500) -> list[dict[str, Any]]:
        with read_cursor() as cur:
            cur.execute(
                """
                SELECT ms.*
                FROM monitoring_snapshots ms
                JOIN (
                    SELECT cell_id, MAX(observed_at) AS observed_at
                    FROM monitoring_snapshots
                    GROUP BY cell_id
                ) latest
                  ON latest.cell_id = ms.cell_id
                 AND latest.observed_at = ms.observed_at
                ORDER BY ms.zone_id, ms.node_id, ms.cell_id
                LIMIT ?
                """,
                (limit,),
            )
            rows = rows_to_list(cur.fetchall())
        for row in rows:
            row["payload"] = _load(row.pop("payload_json"), {})
        return rows


class ExecutionStateRepo:
    """Tracks the live execution state of staged action tools (buffer profile,
    handover profile, scheduler profile) per cell. Used by the agent to detect
    re-application, validate post-change KPIs, and roll back."""

    @staticmethod
    def get_active(cell_id: str, profile_kind: str) -> dict[str, Any] | None:
        with read_cursor() as cur:
            cur.execute(
                """
                SELECT * FROM execution_state
                WHERE cell_id = ? AND profile_kind = ? AND state IN ('staged', 'active')
                ORDER BY updated_at DESC LIMIT 1
                """,
                (cell_id, profile_kind),
            )
            row = row_to_dict(cur.fetchone())
        if row is None:
            return None
        row["parameters"] = _load(row.pop("parameters_json"), {})
        row["before_kpis"] = _load(row.pop("before_kpis_json"), {})
        row["after_kpis"] = _load(row.pop("after_kpis_json"), {})
        row["validation"] = _load(row.pop("validation_json"), {})
        return row

    @staticmethod
    def insert(
        *,
        cell_id: str,
        profile_kind: str,
        action_code: str,
        state: str,
        decision_id: str | None,
        snapshot_id: str | None,
        parameters: dict[str, Any],
        before_kpis: dict[str, Any],
        after_kpis: dict[str, Any],
        validation: dict[str, Any],
        rollback_token: str | None,
        actor: str | None,
    ) -> str:
        record_id = short_id("xst")
        now = utc_now_iso()
        with cursor() as cur:
            cur.execute(
                """
                INSERT INTO execution_state (
                    id, created_at, updated_at, cell_id, profile_kind, action_code,
                    state, decision_id, snapshot_id, parameters_json, before_kpis_json,
                    after_kpis_json, validation_json, rollback_token, actor
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    record_id,
                    now,
                    now,
                    cell_id,
                    profile_kind,
                    action_code,
                    state,
                    decision_id,
                    snapshot_id,
                    _dump(parameters),
                    _dump(before_kpis),
                    _dump(after_kpis),
                    _dump(validation),
                    rollback_token,
                    actor,
                ),
            )
        return record_id

    @staticmethod
    def mark_rolled_back(record_id: str, actor: str) -> None:
        now = utc_now_iso()
        with cursor() as cur:
            cur.execute(
                """
                UPDATE execution_state
                SET state = 'rolled_back', updated_at = ?, actor = ?
                WHERE id = ?
                """,
                (now, actor, record_id),
            )

    @staticmethod
    def list_for_cell(cell_id: str, limit: int = 20) -> list[dict[str, Any]]:
        with read_cursor() as cur:
            cur.execute(
                """
                SELECT * FROM execution_state
                WHERE cell_id = ?
                ORDER BY created_at DESC LIMIT ?
                """,
                (cell_id, limit),
            )
            rows = rows_to_list(cur.fetchall())
        for row in rows:
            row["parameters"] = _load(row.pop("parameters_json"), {})
            row["before_kpis"] = _load(row.pop("before_kpis_json"), {})
            row["after_kpis"] = _load(row.pop("after_kpis_json"), {})
            row["validation"] = _load(row.pop("validation_json"), {})
        return rows


class DiagnosticContractsRepo:
    @staticmethod
    def insert(
        *,
        observed_at: str,
        source_system: str,
        zone_id: str | None,
        node_id: str | None,
        cell_id: str,
        root_cause: str,
        confidence: float,
        recommended_action: str | None,
        summary: str | None,
        evidence: list[str],
    ) -> str:
        contract_id = short_id("diag")
        with cursor() as cur:
            cur.execute(
                """
                INSERT INTO diagnostic_contracts (
                    id, received_at, observed_at, source_system, zone_id, node_id, cell_id,
                    root_cause, confidence, recommended_action, summary, evidence_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    contract_id,
                    utc_now_iso(),
                    observed_at,
                    source_system,
                    zone_id,
                    node_id,
                    cell_id,
                    root_cause,
                    confidence,
                    recommended_action,
                    summary,
                    _dump(evidence),
                ),
            )
        return contract_id

    @staticmethod
    def latest(cell_id: str | None = None) -> dict[str, Any] | None:
        sql = "SELECT * FROM diagnostic_contracts"
        params: list[Any] = []
        if cell_id:
            sql += " WHERE cell_id = ?"
            params.append(cell_id)
        sql += " ORDER BY observed_at DESC, received_at DESC LIMIT 1"
        with read_cursor() as cur:
            cur.execute(sql, params)
            row = row_to_dict(cur.fetchone())
        if row is None:
            return None
        row["evidence"] = _load(row.pop("evidence_json"), [])
        return row

    @staticmethod
    def list_recent(limit: int = 100, cell_id: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM diagnostic_contracts"
        params: list[Any] = []
        if cell_id:
            sql += " WHERE cell_id = ?"
            params.append(cell_id)
        sql += " ORDER BY observed_at DESC, received_at DESC LIMIT ?"
        params.append(limit)
        with read_cursor() as cur:
            cur.execute(sql, params)
            rows = rows_to_list(cur.fetchall())
        for row in rows:
            row["evidence"] = _load(row.pop("evidence_json"), [])
        return rows
