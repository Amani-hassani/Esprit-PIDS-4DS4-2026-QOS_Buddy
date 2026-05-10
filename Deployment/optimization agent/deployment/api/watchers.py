from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Optional

from ..agent import decide
from ..core.clock import utc_now, utc_now_iso
from ..core.settings import get_settings
from ..store.repos import AlertsRepo, ApprovalsRepo
from .events import EventBus


logger = logging.getLogger("qos_buddy.alerts")


@dataclass
class WatcherHandle:
    task: asyncio.Task[None]

    def cancel(self) -> None:
        if not self.task.done():
            self.task.cancel()


async def sla_watcher_loop(bus: EventBus, interval_s: float) -> None:
    """Inserts one `pending_untouched` alert per approval that has been pending
    longer than `QOS_PENDING_ALERT_S` (default 5 min). Idempotent per approval."""
    settings = get_settings()
    threshold_seconds = settings.alerts.pending_alert_s
    while True:
        try:
            cutoff = (utc_now() - timedelta(seconds=threshold_seconds)).isoformat()
            stale = ApprovalsRepo.find_untouched(cutoff)
            for row in stale:
                approval_id = row["id"]
                if AlertsRepo.exists_for_approval(approval_id, "pending_untouched"):
                    continue
                risk = str(row.get("risk_level", "medium"))
                severity = "critical" if risk in {"high", "critical"} else "warning"
                minutes = max(1, threshold_seconds // 60)
                subject = (
                    f"Approval untouched > {minutes}m — "
                    f"{row.get('selected_action', 'action')} on {row.get('cell_id', '?')}"
                )
                body = (
                    f"Approval {approval_id} for cell {row.get('cell_id', '?')} "
                    f"(root cause {row.get('root_cause', '?')}) has been pending since "
                    f"{row.get('created_at', '?')} without operator action. Risk level: {risk}."
                )
                alert_id = AlertsRepo.insert(
                    severity=severity,
                    kind="pending_untouched",
                    subject=subject,
                    body=body,
                    approval_id=approval_id,
                    decision_id=row.get("decision_id"),
                )
                bus.publish(
                    "alerts",
                    {
                        "alert_id": alert_id,
                        "approval_id": approval_id,
                        "decision_id": row.get("decision_id"),
                        "kind": "pending_untouched",
                        "severity": severity,
                        "subject": subject,
                    },
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("sla_watcher failed to run; continuing")
        try:
            await asyncio.sleep(interval_s)
        except asyncio.CancelledError:
            raise


def start_sla_watcher(bus: EventBus, interval_s: Optional[float] = None) -> WatcherHandle:
    settings = get_settings()
    interval = interval_s if interval_s is not None else settings.alerts.poll_interval_s
    task = asyncio.create_task(sla_watcher_loop(bus, interval), name="qos_buddy.sla_watcher")
    return WatcherHandle(task=task)


def _publish_decision(bus: EventBus, result: Any) -> None:
    bus.publish(
        "decisions",
        {
            "decision_id": result.decision_id,
            "cell_id": result.cell_id,
            "action": result.selected_action,
            "gate": result.gate_decision,
            "risk": result.risk_level,
            "auto_executed": result.auto_executed,
            "health_delta": round(result.health_after - result.health_before, 3),
            "llm_available": result.llm_available,
            "reasoning_id": result.reasoning_id,
            "ticket_provider": result.ticket_provider,
            "ticket_key": result.ticket_key,
            "ticket_url": result.ticket_url,
        },
    )
    if result.approval_id:
        bus.publish(
            "approvals",
            {
                "approval_id": result.approval_id,
                "decision_id": result.decision_id,
                "cell_id": result.cell_id,
                "action": result.selected_action,
                "risk_level": result.risk_level,
            },
        )
    if result.reasoning_id:
        bus.publish(
            "reasoning",
            {
                "reasoning_id": result.reasoning_id,
                "decision_id": result.decision_id,
                "kind": "agent",
                "available": result.llm_available,
                "chosen": result.selected_action,
                "text": result.llm_reasoning,
            },
        )


async def agent_runtime_loop(bus: EventBus, *, interval_s: float, startup_run: bool, startup_cell_id: str | None) -> None:
    first_pass = True
    while True:
        try:
            if not first_pass or startup_run:
                result = decide(cell_id=startup_cell_id, principal_token="system-agent", principal_role="lead")
                _publish_decision(bus, result)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("agent runtime loop failed; continuing")
        first_pass = False
        try:
            await asyncio.sleep(interval_s)
        except asyncio.CancelledError:
            raise


def start_agent_runtime(bus: EventBus) -> WatcherHandle | None:
    settings = get_settings()
    if not settings.agent.autostart:
        return None
    task = asyncio.create_task(
        agent_runtime_loop(
            bus,
            interval_s=settings.agent.interval_s,
            startup_run=settings.agent.startup_run,
            startup_cell_id=settings.agent.startup_cell_id,
        ),
        name="qos_buddy.agent_runtime",
    )
    return WatcherHandle(task=task)
