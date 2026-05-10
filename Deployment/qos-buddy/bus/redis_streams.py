"""
Redis Streams bus for QOS-Buddy.

Why Streams (not Pub/Sub):
  • durability — events survive a consumer restart
  • consumer groups — multiple agents share work without dupes
  • replay — UIs can backfill from a checkpoint on (re)connect
  • DLQ — unprocessable events go to qos.dlq with the original payload
  • XPENDING / XCLAIM — visibility for operators

Public API mirrors `monitoring/shared_jsonl_bus.JSONLBus.publish/tail` so existing
agents can swap with minimal change.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Awaitable, Callable

import orjson
import redis.asyncio as redis
from opentelemetry import context as otel_context, trace
from opentelemetry.trace import SpanKind, Status, StatusCode
from pydantic import BaseModel
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from contracts.schemas import BusEnvelope, StreamName

from .otel import extract_context, inject_context

log = logging.getLogger("qos.bus")
_tracer = trace.get_tracer("qos.bus")

DEFAULT_MAXLEN = int(os.getenv("QOS_BUS_MAXLEN", "5000"))
DEFAULT_BLOCK_MS = int(os.getenv("QOS_BUS_BLOCK_MS", "5000"))
DEFAULT_BATCH = int(os.getenv("QOS_BUS_BATCH", "32"))


class RedisStreamsBus:
    """Async Redis Streams wrapper with consumer groups, JSON encoding, and DLQ."""

    def __init__(
        self,
        url: str | None = None,
        *,
        maxlen: int = DEFAULT_MAXLEN,
        block_ms: int = DEFAULT_BLOCK_MS,
        batch: int = DEFAULT_BATCH,
    ) -> None:
        self.url = url or os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self._maxlen = maxlen
        self._block_ms = block_ms
        self._batch = batch
        self._client: redis.Redis | None = None

    # ─── lifecycle ────────────────────────────────────────────────────

    async def connect(self) -> None:
        if self._client is not None:
            return
        self._client = redis.from_url(self.url, decode_responses=True)
        await self._client.ping()
        log.info("redis bus connected url=%s", self.url)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> redis.Redis:
        if self._client is None:
            raise RuntimeError("call connect() first")
        return self._client

    # ─── publish ──────────────────────────────────────────────────────

    async def publish(self, stream: StreamName | str, event: BaseModel | dict[str, Any]) -> str:
        """Publish a single event. Returns the Redis stream id."""
        stream_name = stream.value if isinstance(stream, StreamName) else stream

        if isinstance(event, BusEnvelope):
            event.published_at = datetime.now(timezone.utc)
            payload = event.model_dump(mode="json")
        elif isinstance(event, BaseModel):
            payload = event.model_dump(mode="json")
        else:
            payload = dict(event)
            payload.setdefault("published_at", datetime.now(timezone.utc).isoformat())

        body = {"json": orjson.dumps(payload).decode("utf-8")}

        with _tracer.start_as_current_span(
            f"redis.xadd {stream_name}",
            kind=SpanKind.PRODUCER,
            attributes={
                "messaging.system": "redis_streams",
                "messaging.destination.name": stream_name,
                "messaging.operation": "publish",
            },
        ) as span:
            carrier: dict[str, str] = {}
            inject_context(carrier)
            for k, v in carrier.items():
                body[f"otel.{k}"] = v

            try:
                async for attempt in AsyncRetrying(
                    retry=retry_if_exception_type((redis.ConnectionError, redis.TimeoutError)),
                    wait=wait_exponential(multiplier=0.2, max=2.0),
                    stop=stop_after_attempt(5),
                    reraise=True,
                ):
                    with attempt:
                        msg_id = await self.client.xadd(
                            stream_name, body, maxlen=self._maxlen, approximate=True
                        )
                span.set_attribute("messaging.message.id", str(msg_id))
                return msg_id
            except Exception as exc:
                span.set_status(Status(StatusCode.ERROR, str(exc)))
                raise

    # ─── consume (consumer-group) ─────────────────────────────────────

    async def ensure_group(self, stream: StreamName | str, group: str) -> None:
        stream_name = stream.value if isinstance(stream, StreamName) else stream
        try:
            await self.client.xgroup_create(stream_name, group, id="$", mkstream=True)
            log.info("consumer-group created stream=%s group=%s", stream_name, group)
        except redis.ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def consume(
        self,
        stream: StreamName | str,
        *,
        group: str,
        consumer: str,
        from_id: str = ">",
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """Yield (msg_id, payload) tuples. Caller is responsible for `ack(msg_id)`."""
        stream_name = stream.value if isinstance(stream, StreamName) else stream
        await self.ensure_group(stream_name, group)
        while True:
            try:
                resp = await self.client.xreadgroup(
                    group,
                    consumer,
                    streams={stream_name: from_id},
                    count=self._batch,
                    block=self._block_ms,
                )
            except redis.ConnectionError as exc:
                log.warning("redis lost, reconnecting: %s", exc)
                await asyncio.sleep(1.0)
                continue
            if not resp:
                continue
            for _stream, entries in resp:
                for msg_id, fields in entries:
                    raw = fields.get("json", "{}")
                    try:
                        payload = orjson.loads(raw)
                    except orjson.JSONDecodeError as exc:
                        log.error("malformed payload msg=%s: %s", msg_id, exc)
                        await self._dead_letter(stream_name, msg_id, raw, str(exc))
                        await self.ack(stream_name, group, msg_id)
                        continue
                    payload = _with_otel_carrier(payload, fields)
                    yield msg_id, payload

    async def ack(self, stream: StreamName | str, group: str, msg_id: str) -> None:
        stream_name = stream.value if isinstance(stream, StreamName) else stream
        await self.client.xack(stream_name, group, msg_id)

    # ─── tail (no group, latest-only — used by gateway fan-out to UI) ─

    async def tail(
        self,
        stream: StreamName | str,
        *,
        from_id: str = "$",
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """Plain XREAD tail. Newest events only by default."""
        stream_name = stream.value if isinstance(stream, StreamName) else stream
        last_id = from_id
        while True:
            try:
                resp = await self.client.xread(
                    streams={stream_name: last_id},
                    count=self._batch,
                    block=self._block_ms,
                )
            except redis.ConnectionError as exc:
                log.warning("redis lost on tail, reconnecting: %s", exc)
                await asyncio.sleep(1.0)
                continue
            if not resp:
                continue
            for _stream, entries in resp:
                for msg_id, fields in entries:
                    last_id = msg_id
                    try:
                        payload = orjson.loads(fields.get("json", "{}"))
                    except orjson.JSONDecodeError:
                        continue
                    payload = _with_otel_carrier(payload, fields)
                    yield msg_id, payload

    # ─── snapshot (last N events on connect, for the UI cold-start) ──

    async def latest(
        self, stream: StreamName | str, *, count: int = 50
    ) -> list[tuple[str, dict[str, Any]]]:
        stream_name = stream.value if isinstance(stream, StreamName) else stream
        entries = await self.client.xrevrange(stream_name, count=count)
        out: list[tuple[str, dict[str, Any]]] = []
        for msg_id, fields in reversed(entries):
            try:
                payload = orjson.loads(fields.get("json", "{}"))
                out.append((msg_id, _with_otel_carrier(payload, fields)))
            except orjson.JSONDecodeError:
                continue
        return out

    # ─── dlq ─────────────────────────────────────────────────────────

    async def _dead_letter(
        self, source_stream: str, msg_id: str, raw: str, reason: str
    ) -> None:
        await self.client.xadd(
            StreamName.DLQ.value,
            {
                "json": orjson.dumps(
                    {
                        "source_stream": source_stream,
                        "source_msg_id": msg_id,
                        "raw": raw,
                        "reason": reason,
                        "dead_lettered_at": datetime.now(timezone.utc).isoformat(),
                    }
                ).decode("utf-8")
            },
            maxlen=10_000,
            approximate=True,
        )


# ─── helper: run a consumer loop with auto-ack and per-message handler ──

ConsumerFn = Callable[[str, dict[str, Any]], Awaitable[None]]


def _with_otel_carrier(payload: dict[str, Any], fields: dict[str, Any]) -> dict[str, Any]:
    carrier = {
        k[len("otel.") :]: v
        for k, v in fields.items()
        if isinstance(k, str) and k.startswith("otel.")
    }
    if not carrier:
        return payload
    payload["_otel_carrier"] = carrier
    traceparent = str(carrier.get("traceparent") or "")
    parts = traceparent.split("-")
    if not payload.get("trace_id") and len(parts) >= 4 and len(parts[1]) == 32:
        payload["trace_id"] = parts[1]
    return payload


async def run_consumer(
    bus: RedisStreamsBus,
    stream: StreamName | str,
    *,
    group: str,
    consumer: str,
    handler: ConsumerFn,
) -> None:
    stream_name = stream.value if isinstance(stream, StreamName) else stream
    async for msg_id, payload in bus.consume(stream, group=group, consumer=consumer):
        carrier = payload.pop("_otel_carrier", None) or {}
        ctx = extract_context(carrier) if carrier else None
        token = otel_context.attach(ctx) if ctx is not None else None
        try:
            with _tracer.start_as_current_span(
                f"redis.xreadgroup {stream_name}",
                kind=SpanKind.CONSUMER,
                attributes={
                    "messaging.system": "redis_streams",
                    "messaging.source.name": stream_name,
                    "messaging.operation": "process",
                    "messaging.consumer.group": group,
                    "messaging.message.id": str(msg_id),
                },
            ) as span:
                try:
                    await handler(msg_id, payload)
                    await bus.ack(stream, group, msg_id)
                except Exception as exc:  # noqa: BLE001
                    span.set_status(Status(StatusCode.ERROR, str(exc)))
                    log.exception("handler failed msg=%s: %s", msg_id, exc)
                    await bus._dead_letter(  # noqa: SLF001
                        stream_name,
                        msg_id,
                        orjson.dumps(payload).decode("utf-8"),
                        f"handler-error: {exc}",
                    )
                    await bus.ack(stream, group, msg_id)
        finally:
            if token is not None:
                otel_context.detach(token)
