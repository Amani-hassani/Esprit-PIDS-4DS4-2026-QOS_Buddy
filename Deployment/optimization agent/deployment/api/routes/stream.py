from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from ...core.access import Principal, resolve_principal, resolve_principal_from_cookie, session_cookie_name
from ...data import timeseries
from ...telemetry_cache import telemetry_snapshot_payload
from ..deps import viewer_required
from ..events import CHANNELS, get_bus


router = APIRouter(prefix="/api/stream", tags=["stream"])


def _sse(data: dict, event: str | None = None, id_: int | None = None) -> str:
    chunks: list[str] = []
    if event:
        chunks.append(f"event: {event}")
    if id_ is not None:
        chunks.append(f"id: {id_}")
    chunks.append(f"data: {json.dumps(data, default=str)}")
    return "\n".join(chunks) + "\n\n"


async def _bus_stream(request: Request, channel: str) -> AsyncIterator[bytes]:
    bus = get_bus()
    queue = await bus.subscribe(channel)
    try:
        yield _sse({"channel": channel, "ok": True}, event="hello").encode("utf-8")
        while True:
            if await request.is_disconnected():
                break
            try:
                event = await asyncio.wait_for(queue.get(), timeout=15.0)
            except asyncio.TimeoutError:
                yield _sse({"ts": None}, event="ping").encode("utf-8")
                continue
            yield _sse(event.payload, event=event.channel, id_=event.id).encode("utf-8")
    finally:
        await bus.unsubscribe(channel, queue)


def _require_viewer_for_stream(request: Request, token: str | None) -> Principal:
    """Prefer the HTTP-only session cookie for browser EventSource clients."""
    cookie_token = request.cookies.get(session_cookie_name())
    principal = resolve_principal_from_cookie(cookie_token)
    if principal is not None:
        return principal
    authorization = f"Bearer {token}" if token else None
    principal = resolve_principal(authorization)
    if principal is None:
        raise HTTPException(status_code=401, detail="stream session missing or invalid")
    return principal


@router.get("/events")
async def events(
    request: Request,
    channel: str = Query(..., description="one of: " + ", ".join(CHANNELS)),
    token: str | None = Query(default=None, description="legacy bearer token fallback"),
):
    _require_viewer_for_stream(request, token)
    if channel not in CHANNELS:
        raise HTTPException(status_code=400, detail=f"unknown channel {channel}")
    return StreamingResponse(_bus_stream(request, channel), media_type="text/event-stream")


@router.get("/telemetry")
async def telemetry(
    request: Request,
    cell_id: str | None = Query(default=None),
    interval_s: float = Query(default=3.0, ge=0.5, le=30.0),
    limit: int = Query(default=60, ge=10, le=500),
    token: str | None = Query(default=None, description="legacy bearer token fallback"),
):
    _require_viewer_for_stream(request, token)

    async def _gen() -> AsyncIterator[bytes]:
        seq = 0
        # Initial burst with the current tail of the timeseries so subscribers can seed charts.
        first = timeseries(cell_id, limit=limit)
        yield _sse({"cell_id": cell_id, "points": first, "initial": True}, event="telemetry", id_=seq).encode("utf-8")
        while True:
            if await request.is_disconnected():
                break
            seq += 1
            snap = telemetry_snapshot_payload(cell_id)
            yield _sse({"cell_id": cell_id, "snapshot": snap}, event="telemetry", id_=seq).encode("utf-8")
            try:
                await asyncio.sleep(interval_s)
            except asyncio.CancelledError:
                break

    return StreamingResponse(_gen(), media_type="text/event-stream")
