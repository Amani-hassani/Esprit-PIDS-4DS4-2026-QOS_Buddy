"""
Hash-chained audit ledger — minimal in-process tail.

Every meaningful state transition (alert published, action proposed,
verdict reached, action executed) appends an `AuditEvent` whose `prev_hash`
references the previous event's `hash`. Reading the qos.audit stream and
re-computing the chain lets the UI show a tamper-evident NOC view.

We persist the *previous* hash here only — the qos.audit stream itself is
the source of truth. On startup we pull the latest entry from the stream
to seed the chain.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from contracts.schemas import (
    AuditEvent,
    AuthLevel,
    Role,
    StreamName,
)

from bus.redis_streams import RedisStreamsBus

log = logging.getLogger("qos.synthesis.audit")

GENESIS_HASH = "0" * 64


class AuditChain:
    def __init__(self) -> None:
        self._prev_hash: str = GENESIS_HASH

    async def seed_from_stream(self, bus: RedisStreamsBus) -> None:
        try:
            latest = await bus.latest(StreamName.AUDIT, count=1)
        except Exception as exc:  # noqa: BLE001
            log.warning("could not seed audit chain: %s", exc)
            return
        if latest:
            _msg_id, payload = latest[-1]
            self._prev_hash = str(payload.get("hash") or GENESIS_HASH)
            log.info("audit chain seeded prev_hash=%s", self._prev_hash[:12])

    def append(
        self,
        *,
        actor: str,
        actor_role: Role,
        action: str,
        target_id: str | None,
        succeeded: bool,
        auth_level: AuthLevel = AuthLevel.WEBAUTHN,
        correlation_id: str | None = None,
        causation_id: str | None = None,
        cell_id: str | None = None,
    ) -> AuditEvent:
        body = {
            "prev_hash": self._prev_hash,
            "actor": actor,
            "actor_role": actor_role.value if isinstance(actor_role, Role) else str(actor_role),
            "action": action,
            "target_id": target_id,
            "auth_level": auth_level.value if isinstance(auth_level, AuthLevel) else str(auth_level),
            "succeeded": succeeded,
            "occurred_at": datetime.now(timezone.utc).isoformat(),
        }
        digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
        event = AuditEvent(
            producer="synthesis",
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

    @property
    def prev_hash(self) -> str:
        return self._prev_hash
