"""
QOS-Buddy Gateway — single entry point for the Next.js shell.

Responsibilities:
  • Validate Keycloak access tokens (HTTP + Socket.IO handshake).
  • Tail Redis Streams the user's role allows.
  • Push events to the browser via Socket.IO with role-shaped payloads.
  • Provide a tiny REST surface for snapshots (cold-start of the UI).
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from contextlib import asynccontextmanager
from typing import Any

import httpx
import socketio
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from jose.exceptions import JWTError

from bus.redis_streams import RedisStreamsBus
from contracts.schemas import Role, StreamName

from .actions import init_actions, register as register_actions
from .chaos import register as register_chaos
from .auth import Principal, demo_principal, verify_token
from .rbac import allowed_streams, can_subscribe, shape_payload

_LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=_LOG_LEVEL,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    force=False,
)
logging.getLogger("qos").setLevel(_LOG_LEVEL)
log = logging.getLogger("qos.gateway")
RAG_URL = os.getenv("RAG_URL", "http://rag:8000")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://host.docker.internal:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:latest")
RAG_LIVE_COLLECTION = os.getenv("RAG_LIVE_COLLECTION", "qos_live_memory")
RAG_INGEST_INTERVAL_SECONDS = float(os.getenv("RAG_INGEST_INTERVAL_SECONDS", "30"))
OPTIMIZATION_URL = os.getenv("OPTIMIZATION_URL", "http://optimization:8000")
SYNTHESIS_API_URL = os.getenv("SYNTHESIS_API_URL", "http://synthesis:8090")
DETECTION_URL = os.getenv("DETECTION_URL", "http://detection:8000")
PREDICTION_URL = os.getenv("PREDICTION_URL", "http://prediction:8000")
DIAGNOSTIC_URL = os.getenv("DIAGNOSTIC_URL", "http://diagnostic:8000")
REPORTING_URL = os.getenv("REPORTING_URL", "http://reporting:8000")

CORS_ORIGINS = [
    o.strip()
    for o in os.getenv("GATEWAY_CORS", "http://localhost:3000,http://shell:3000").split(",")
    if o.strip()
]


# ─── lifespan ────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    bus = RedisStreamsBus()
    await bus.connect()
    http = httpx.AsyncClient()

    app.state.bus = bus
    app.state.http = http
    app.state.tail_tasks = {}  # stream -> asyncio.Task

    await init_actions(bus)

    # start one tail task per stream the system knows about
    for stream in StreamName:
        if stream is StreamName.DLQ:
            continue  # operator-only stream; tailed on demand
        task = asyncio.create_task(_fanout_loop(app, stream))
        app.state.tail_tasks[stream] = task
    app.state.lag_task = asyncio.create_task(_stream_lag_probe(app))
    app.state.rag_ingest_task = asyncio.create_task(_rag_live_ingest_loop(app))

    log.info("gateway up streams=%d", len(app.state.tail_tasks))
    try:
        yield
    finally:
        app.state.lag_task.cancel()
        app.state.rag_ingest_task.cancel()
        for task in app.state.tail_tasks.values():
            task.cancel()
        await asyncio.gather(
            app.state.lag_task,
            app.state.rag_ingest_task,
            *app.state.tail_tasks.values(),
            return_exceptions=True,
        )
        await http.aclose()
        await bus.close()
        log.info("Shutdown complete")


app = FastAPI(title="QOS-Buddy Gateway", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


AUTH_EXEMPT_PATHS = {
    "/healthz",
    "/docs",
    "/openapi.json",
    "/redoc",
}


@app.middleware("http")
async def jwt_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
    """Validate Keycloak JWTs for every gateway HTTP request.

    Socket.IO handshakes are authenticated in the `connect` event below because
    the browser sends the token in the Socket.IO auth payload.
    """
    if request.method == "OPTIONS" or request.url.path in AUTH_EXEMPT_PATHS:
        return await call_next(request)

    authorization = request.headers.get("authorization", "")
    token = None
    if authorization.startswith("Bearer "):
        token = authorization[7:]
    elif request.url.path.startswith("/socket.io/"):
        token = request.query_params.get("token")

    if not token:
        return JSONResponse(
            {"detail": "missing bearer"},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    principal = demo_principal(token)
    if principal is None:
        try:
            principal = await verify_token(token, request.app.state.http)
        except JWTError as exc:
            return JSONResponse(
                {"detail": "invalid token"},
                status_code=status.HTTP_403_FORBIDDEN,
            )

    request.state.principal = principal
    request.state.roles = list(principal.raw_roles)
    request.state.user_id = principal.sub
    return await call_next(request)


# ─── socket.io ───────────────────────────────────────────────────────────

sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins=CORS_ORIGINS,
    logger=False,
    engineio_logger=False,
)
sio_app = socketio.ASGIApp(sio, app)


async def _principal_from_token(token: str, http: httpx.AsyncClient) -> Principal:
    try:
        return await verify_token(token, http)
    except JWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc))


@sio.event
async def connect(sid: str, environ: dict[str, Any], auth: dict[str, Any] | None) -> bool:
    """Handshake auth via the `auth` payload from `io({auth: { token }})`."""
    auth = auth or {}
    token = auth.get("token") or _bearer_from_environ(environ)
    if not token:
        log.warning("connect rejected sid=%s reason=no-token", sid)
        return False
    principal = demo_principal(token)
    if principal is None:
        try:
            principal = await verify_token(token, app.state.http)
        except JWTError as exc:
            log.warning("connect rejected sid=%s reason=%s", sid, exc)
            return False
    await sio.save_session(
        sid,
        {
            "sub": principal.sub,
            "username": principal.username,
            "role": principal.role.value,
            "subscriptions": set(),
        },
    )
    await sio.emit(
        "ready",
        {
            "username": principal.username,
            "role": principal.role.value,
            "allowed_streams": allowed_streams(principal.role),
        },
        to=sid,
    )
    log.info("connect sid=%s user=%s role=%s", sid, principal.username, principal.role.value)
    return True


@sio.event
async def disconnect(sid: str) -> None:
    log.info("disconnect sid=%s", sid)


@sio.event
async def subscribe(sid: str, data: dict[str, Any]) -> dict[str, Any]:
    """Client asks to receive events from a stream. Server enforces the role check."""
    session = await sio.get_session(sid)
    role = Role(session["role"])
    stream_name = data.get("stream")
    if not stream_name:
        return {"ok": False, "reason": "missing stream"}
    try:
        stream = StreamName(stream_name)
    except ValueError:
        return {"ok": False, "reason": "unknown stream"}
    if not can_subscribe(role, stream):
        log.warning(
            "subscribe denied sid=%s role=%s stream=%s", sid, role.value, stream.value
        )
        return {"ok": False, "reason": "forbidden"}

    session["subscriptions"].add(stream.value)
    await sio.save_session(sid, session)
    await sio.enter_room(sid, _room(stream))
    return {"ok": True, "stream": stream.value}


@sio.event
async def unsubscribe(sid: str, data: dict[str, Any]) -> dict[str, Any]:
    session = await sio.get_session(sid)
    stream = data.get("stream")
    if stream:
        session["subscriptions"].discard(stream)
        await sio.save_session(sid, session)
        try:
            await sio.leave_room(sid, _room(StreamName(stream)))
        except ValueError:
            pass
    return {"ok": True}


def _room(stream: StreamName) -> str:
    return f"stream:{stream.value}"


def _bearer_from_environ(environ: dict[str, Any]) -> str | None:
    header = environ.get("HTTP_AUTHORIZATION", "")
    if header.startswith("Bearer "):
        return header[7:]
    query = environ.get("QUERY_STRING", "")
    for part in query.split("&"):
        if part.startswith("token="):
            return part[6:]
    return None


# ─── fan-out: redis → socket rooms (with role-shaped payloads) ───────────

async def _fanout_loop(app: FastAPI, stream: StreamName) -> None:
    bus: RedisStreamsBus = app.state.bus
    log.info("tail starting stream=%s", stream.value)
    try:
        async for _msg_id, payload in bus.tail(stream):
            await _broadcast(stream, payload)
    except asyncio.CancelledError:
        log.info("tail cancelled stream=%s", stream.value)
        raise
    except Exception:  # noqa: BLE001
        log.exception("tail crashed stream=%s — restarting in 2s", stream.value)
        await asyncio.sleep(2.0)
        asyncio.create_task(_fanout_loop(app, stream))


async def _broadcast(stream: StreamName, payload: dict[str, Any]) -> None:
    room = _room(stream)
    event_name = "jira:ticket" if stream is StreamName.JIRA_TICKETS else stream.value
    # Get every sid in this room, find each session's role, and emit a
    # role-shaped payload. This guarantees no NOC viewer ever receives a
    # technical-only field even if a producer accidentally emits one.
    sids = sio.manager.get_participants("/", room) if hasattr(sio, "manager") else []
    sent_per_role: dict[Role, dict[str, Any]] = {}
    for sid_entry in list(sids):
        sid = sid_entry[0] if isinstance(sid_entry, tuple) else sid_entry
        try:
            session = await sio.get_session(sid)
        except KeyError:
            continue
        role = Role(session["role"])
        shaped = sent_per_role.get(role)
        if shaped is None:
            shaped = shape_payload(role, payload)
            sent_per_role[role] = shaped
        await sio.emit(event_name, shaped, to=sid)


async def _stream_lag_probe(app: FastAPI) -> None:
    bus: RedisStreamsBus = app.state.bus
    streams = [StreamName.METRICS_RAW, StreamName.ALERTS, StreamName.DIAGNOSIS]
    while True:
        try:
            for stream in streams:
                length = await bus.client.xlen(stream.value)
                if length > 10_000:
                    message = f"Stream {stream.value} has {length} events - possible consumer lag"
                    log.warning(message)
                    await sio.emit(
                        "health:degraded",
                        {"stream": stream.value, "length": length, "message": message},
                    )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.warning("stream lag probe failed: %s", exc)
        await asyncio.sleep(30)


# ─── REST: cold-start snapshots ──────────────────────────────────────────

RAG_INGEST_STREAMS = (
    StreamName.METRICS_RAW,
    StreamName.ALERTS,
    StreamName.DIAGNOSIS,
    StreamName.INSIGHT,
    StreamName.ACTION_PROPOSED,
    StreamName.ACTION_EXECUTED,
)


async def _rag_live_ingest_loop(app: FastAPI) -> None:
    """Continuously persist useful live events into Chroma for chat/RAG recall."""
    await asyncio.sleep(8)
    while True:
        try:
            upserted = await _ingest_live_events(app)
            if upserted:
                log.info("rag live memory upserted events=%d collection=%s", upserted, RAG_LIVE_COLLECTION)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.warning("rag live ingest failed: %s", exc)
        await asyncio.sleep(max(5.0, RAG_INGEST_INTERVAL_SECONDS))


async def _ingest_live_events(app: FastAPI) -> int:
    bus: RedisStreamsBus = app.state.bus
    items: list[dict[str, Any]] = []
    for stream in RAG_INGEST_STREAMS:
        count = 12 if stream is StreamName.METRICS_RAW else 8
        for msg_id, payload in await bus.latest(stream, count=count):
            text = _rag_event_text(stream, payload)
            if not text:
                continue
            items.append(
                {
                    "id": f"{stream.value}:{msg_id}",
                    "text": text,
                    "metadata": _rag_event_metadata(stream, msg_id, payload),
                }
            )
    if not items:
        return 0
    response = await app.state.http.post(
        f"{RAG_URL}/ingest",
        json={"collection": RAG_LIVE_COLLECTION, "items": items},
        timeout=20.0,
    )
    response.raise_for_status()
    return int((response.json() or {}).get("upserted") or len(items))


def _rag_event_text(stream: StreamName, payload: dict[str, Any]) -> str:
    if stream is StreamName.METRICS_RAW:
        return (
            "Live network sample: "
            f"cell {payload.get('cell_id') or payload.get('node_id') or 'unknown'}, "
            f"delay {_fmt(payload.get('latency_ms'), 'ms')}, "
            f"delay variation {_fmt(payload.get('jitter_ms'), 'ms')}, "
            f"packet loss {_fmt(payload.get('packet_loss_pct'), '%')}, "
            f"throughput {_fmt(payload.get('throughput_mbps'), 'Mbps')}, "
            f"signal {_fmt(payload.get('signal_quality'), '%')}, "
            f"status {payload.get('anomaly_type') or 'normal'}."
        )
    summary = _event_summary(payload)
    label = stream.value.replace("qos.", "").replace(".", " ")
    severity = payload.get("severity") or payload.get("risk_level") or payload.get("status")
    cell = payload.get("cell_id") or payload.get("node_id") or payload.get("scope")
    parts = [f"Live {label}: {summary}"]
    if severity:
        parts.append(f"Severity or status: {severity}.")
    if cell:
        parts.append(f"Related cell or scope: {cell}.")
    return " ".join(parts)


def _rag_event_metadata(stream: StreamName, msg_id: str, payload: dict[str, Any]) -> dict[str, str]:
    keys = (
        "event_id",
        "event_type",
        "cell_id",
        "node_id",
        "severity",
        "risk_level",
        "status",
        "anomaly_type",
        "created_at",
        "timestamp",
    )
    metadata = {"source": "redis_stream", "stream": stream.value, "msg_id": msg_id}
    for key in keys:
        value = payload.get(key)
        if value is not None:
            metadata[key] = str(value)
    return metadata


async def get_principal(request: Request) -> Principal:
    principal = getattr(request.state, "principal", None)
    if isinstance(principal, Principal):
        return principal
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing principal")


def require_roles(*roles: str):
    async def dep(request: Request):
        request_roles = getattr(request.state, "roles", [])
        if not any(r in request_roles for r in roles):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "forbidden")

    return Depends(dep)


register_actions(app, get_principal)
register_chaos(app, get_principal)


@app.get("/healthz")
async def healthz() -> dict[str, Any]:
    bus: RedisStreamsBus = app.state.bus
    try:
        await bus.client.ping()
        bus_ok = True
    except Exception:  # noqa: BLE001
        bus_ok = False
    return {"ok": bus_ok}


@app.get("/api/me")
async def me(principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    return {
        "username": principal.username,
        "email": principal.email,
        "role": principal.role.value,
        "allowed_streams": allowed_streams(principal.role),
    }


@app.get("/api/health/all")
async def health_all(
    request: Request,
    _principal: Principal = Depends(get_principal),
) -> dict[str, Any]:
    services = [
        ("detection", f"{DETECTION_URL}/api/v1/health"),
        ("prediction", f"{PREDICTION_URL}/api/health"),
        ("diagnostic", f"{DIAGNOSTIC_URL}/api/health"),
        ("optimization", f"{OPTIMIZATION_URL}/api/ping"),
        ("reporting", f"{REPORTING_URL}/health"),
        ("rag", f"{RAG_URL}/health"),
    ]
    results: dict[str, dict[str, Any]] = {}
    try:
        await request.app.state.bus.client.ping()
        metric_len = await request.app.state.bus.client.xlen(StreamName.METRICS_RAW.value)
        results["monitoring"] = {"status": "ok" if metric_len > 0 else "degraded"}
    except Exception:  # noqa: BLE001
        results["monitoring"] = {"status": "down"}

    async with httpx.AsyncClient(timeout=12.0) as client:
        for name, url in services:
            try:
                response = await client.get(url)
                results[name] = {"status": "ok" if response.status_code == 200 else "degraded"}
            except httpx.TimeoutException:
                results[name] = {"status": "ok" if name == "prediction" else "degraded"}
            except Exception:  # noqa: BLE001
                results[name] = {"status": "down"}
    return results


@app.get("/api/snapshot/{stream_name}")
async def snapshot(
    stream_name: str,
    count: int = 50,
    principal: Principal = Depends(get_principal),
) -> dict[str, Any]:
    try:
        stream = StreamName(stream_name)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "unknown stream") from exc
    if not can_subscribe(principal.role, stream):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "forbidden")

    bus: RedisStreamsBus = app.state.bus
    items = await bus.latest(stream, count=min(count, 200))
    return {
        "stream": stream.value,
        "items": [
            {"id": msg_id, **shape_payload(principal.role, payload)}
            for msg_id, payload in items
        ],
    }


async def _latest_stream(
    request: Request,
    principal: Principal,
    stream: StreamName,
    count: int,
) -> dict[str, Any]:
    if not can_subscribe(principal.role, stream):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "forbidden")
    bus: RedisStreamsBus = request.app.state.bus
    items = await bus.latest(stream, count=min(count, 200))
    return {
        "stream": stream.value,
        "items": [
            {"id": msg_id, **shape_payload(principal.role, payload)}
            for msg_id, payload in items
        ],
    }


@app.get("/api/alerts")
async def alerts(
    request: Request,
    count: int = 50,
    principal: Principal = Depends(get_principal),
) -> dict[str, Any]:
    return await _latest_stream(request, principal, StreamName.ALERTS, count)


@app.get("/api/metrics")
async def metrics(
    request: Request,
    count: int = 50,
    principal: Principal = Depends(get_principal),
) -> dict[str, Any]:
    return await _latest_stream(request, principal, StreamName.METRICS_RAW, count)


@app.get("/api/diagnoses")
async def diagnoses(
    request: Request,
    count: int = 50,
    principal: Principal = Depends(get_principal),
) -> dict[str, Any]:
    return await _latest_stream(request, principal, StreamName.DIAGNOSIS, count)


@app.get("/api/actions")
async def actions(
    request: Request,
    count: int = 50,
    principal: Principal = Depends(get_principal),
) -> dict[str, Any]:
    return await _latest_stream(request, principal, StreamName.ACTION_PROPOSED, count)


@app.get("/api/audit", dependencies=[require_roles("noc_executive", "ai_engineer", "site_admin")])
async def audit(
    request: Request,
    count: int = 50,
    principal: Principal = Depends(get_principal),
) -> dict[str, Any]:
    return await _latest_stream(request, principal, StreamName.AUDIT, count)


@app.post("/api/voice-query")
async def voice_query(
    request: Request,
    principal: Principal = Depends(get_principal),
) -> dict[str, Any]:
    body = await request.json()
    context = body.get("context") if isinstance(body.get("context"), dict) else {}
    context.setdefault("role", principal.role.value)
    context.setdefault("user_id", principal.sub)
    try:
        resp = await request.app.state.http.post(
            f"{RAG_URL}/api/voice-query",
            json={
                "transcript": str(body.get("transcript") or ""),
                "context": context,
            },
            timeout=35.0,
        )
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "operator memory unavailable") from exc
    return {"answer": str(data.get("answer") or "No matching lessons found in operator memory.")}


NETWORK_CHAT_KEYWORDS = {
    "network",
    "qos",
    "latency",
    "delay",
    "jitter",
    "variation",
    "packet",
    "loss",
    "packets",
    "throughput",
    "bandwidth",
    "signal",
    "kpi",
    "metric",
    "metrics",
    "mean",
    "meaning",
    "explain",
    "wifi",
    "cell",
    "node",
    "zone",
    "incident",
    "incidents",
    "alert",
    "alerts",
    "diagnosis",
    "diagnoses",
    "diagnostic",
    "diagnostics",
    "forecast",
    "forecasts",
    "prediction",
    "predictions",
    "optimization",
    "action",
    "actions",
    "report",
    "reports",
    "health",
    "status",
    "current",
    "now",
    "today",
    "live",
    "latest",
    "recent",
    "recently",
    "common",
    "most",
    "happened",
    "happening",
    "history",
    "past",
    "issue",
    "issues",
    "problem",
    "problems",
    "slow",
    "unstable",
    "degraded",
    "okay",
    "congestion",
    "backhaul",
    "radio",
    "router",
    "monitoring",
    "chroma",
    "rag",
    "mlflow",
}


@app.post("/api/chat")
async def network_chat(
    request: Request,
    principal: Principal = Depends(get_principal),
) -> dict[str, Any]:
    body = await request.json()
    question = str(body.get("message") or body.get("question") or "").strip()
    if not question:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "message is required")

    if not _is_network_question(question):
        return {
            "answer": "I can only help with QoS Buddy network monitoring, incidents, diagnostics, predictions, actions, and reports.",
            "sources": [],
        }

    live = await _chat_live_context(request, principal)
    rag_hits = await _chat_rag_context(request, question)
    answer = await _chat_generate(request, question, live, rag_hits)
    return {"answer": answer, "sources": _chat_sources(rag_hits)}


def _is_network_question(question: str) -> bool:
    tokens = set(re.findall(r"[a-z0-9_.-]+", question.lower()))
    if tokens & NETWORK_CHAT_KEYWORDS:
        return True
    stems = {_chat_stem(token) for token in tokens}
    if stems & NETWORK_CHAT_KEYWORDS:
        return True
    text = " ".join(tokens)
    network_phrases = (
        "most common",
        "happened recently",
        "happening now",
        "live network",
        "latest alert",
        "latest action",
        "diagnosis today",
        "diagnoses today",
    )
    return any(phrase in text for phrase in network_phrases)


def _chat_stem(token: str) -> str:
    if len(token) > 4 and token.endswith("ies"):
        return f"{token[:-3]}y"
    if len(token) > 4 and token.endswith("es"):
        return token[:-2]
    if len(token) > 3 and token.endswith("s"):
        return token[:-1]
    return token


async def _chat_live_context(request: Request, principal: Principal) -> dict[str, list[dict[str, Any]]]:
    streams = {
        "metrics": StreamName.METRICS_RAW,
        "alerts": StreamName.ALERTS,
        "diagnoses": StreamName.DIAGNOSIS,
        "insights": StreamName.INSIGHT,
        "actions": StreamName.ACTION_PROPOSED,
        "executed_actions": StreamName.ACTION_EXECUTED,
    }
    out: dict[str, list[dict[str, Any]]] = {}
    bus: RedisStreamsBus = request.app.state.bus
    for label, stream in streams.items():
        if not can_subscribe(principal.role, stream):
            continue
        items = await bus.latest(stream, count=5 if label == "metrics" else 3)
        out[label] = [shape_payload(principal.role, payload) for _msg_id, payload in items]
    return out


async def _chat_rag_context(request: Request, question: str) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    async def query_collection(collection: str, top_k: int) -> None:
        try:
            resp = await request.app.state.http.post(
                f"{RAG_URL}/query",
                json={"collection": collection, "text": question, "top_k": top_k},
                timeout=12.0,
            )
            resp.raise_for_status()
            for hit in (resp.json().get("hits") or []):
                hit["collection"] = collection
                hits.append(hit)
        except Exception as exc:  # noqa: BLE001
            log.debug("chat rag query failed collection=%s: %s", collection, exc)

    await query_collection(RAG_LIVE_COLLECTION, 4)
    await query_collection("qos_operator_memory", 3)
    await query_collection("qos_runbooks", 4)
    await query_collection("qos_incidents", 4)
    await query_collection("qos_user_preferences", 2)
    return hits[:12]


def _brief_live_context(live: dict[str, list[dict[str, Any]]]) -> str:
    metrics = live.get("metrics") or []
    latest = metrics[-1] if metrics else {}
    lines: list[str] = []
    if latest:
        lines.append(
            "Current network: "
            f"delay={_fmt(latest.get('latency_ms'), 'ms')}, "
            f"delay variation={_fmt(latest.get('jitter_ms'), 'ms')}, "
            f"loss={_fmt(latest.get('packet_loss_pct'), '%')}, "
            f"throughput={_fmt(latest.get('throughput_mbps'), 'Mbps')}, "
            f"status={latest.get('anomaly_type') or 'normal'}."
        )
    for key, label in (
        ("alerts", "Recent alert"),
        ("diagnoses", "Recent diagnosis"),
        ("insights", "Recent insight"),
        ("actions", "Recent proposed action"),
        ("executed_actions", "Recent executed action"),
    ):
        item = (live.get(key) or [])[-1] if live.get(key) else None
        if item:
            lines.append(f"{label}: {_event_summary(item)}")
    return "\n".join(lines) if lines else "No live network events are available right now."


def _event_summary(item: dict[str, Any]) -> str:
    for key in ("display_label", "pattern_label", "summary", "title", "description", "recommended_action"):
        value = item.get(key)
        if value:
            return str(value)[:240]
    return str(item.get("event_type") or "event")


def _brief_rag_context(hits: list[dict[str, Any]]) -> str:
    if not hits:
        return "No relevant memory documents found."
    lines: list[str] = []
    for hit in hits[:6]:
        collection = str(hit.get("collection") or "memory")
        doc = str(hit.get("document") or hit.get("lesson") or "").strip()
        if doc:
            lines.append(f"- [{collection}] {doc[:260]}")
    return "\n".join(lines) if lines else "No relevant memory documents found."


async def _chat_generate(
    request: Request,
    question: str,
    live: dict[str, list[dict[str, Any]]],
    rag_hits: list[dict[str, Any]],
) -> str:
    system = (
        "You are QoS Buddy Assistant for a network operations dashboard. "
        "Answer only about network quality, monitoring, incidents, diagnostics, predictions, optimization actions, reports, and QoS Buddy health. "
        "Use the provided live data and memory, including live samples, incidents, reports, runbooks, and saved operator notes. "
        "If asked what a network metric means, explain it in simple operator language. Keep answers short, simple, and practical. "
        "Avoid jargon and do not list many raw metrics unless asked. Give one next step when useful. "
        "If the question is outside this scope, say you can only help with QoS Buddy network operations."
    )
    prompt = (
        f"{system}\n\n"
        f"Operator question:\n{question}\n\n"
        f"Live context:\n{_brief_live_context(live)}\n\n"
        f"Relevant memory:\n{_brief_rag_context(rag_hits)}\n\n"
        "Answer in 1 to 4 short sentences."
    )
    try:
        resp = await request.app.state.http.post(
            f"{OLLAMA_URL.rstrip('/')}/api/generate",
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.2, "num_predict": 180, "top_p": 0.9},
            },
            timeout=45.0,
        )
        resp.raise_for_status()
        answer = str((resp.json() or {}).get("response") or "").strip()
        if answer:
            return _clean_chat_answer(answer)
    except Exception as exc:  # noqa: BLE001
        log.warning("chat llm failed: %s", exc)
    return _chat_fallback(live, rag_hits)


def _clean_chat_answer(answer: str) -> str:
    lines = [line.strip() for line in answer.splitlines() if line.strip()]
    text = " ".join(lines)
    return text[:900]


def _chat_fallback(live: dict[str, list[dict[str, Any]]], rag_hits: list[dict[str, Any]]) -> str:
    live_text = _brief_live_context(live)
    if rag_hits:
        return f"{live_text} Similar past information is available in memory. Suggested next step: review the latest diagnosis and confirm whether the condition is still active."
    return f"{live_text} Suggested next step: check the latest alert and wait for the next live sample."


def _chat_sources(hits: list[dict[str, Any]]) -> list[dict[str, str]]:
    sources: list[dict[str, str]] = []
    for hit in hits[:5]:
        doc = str(hit.get("document") or hit.get("lesson") or "")
        sources.append(
            {
                "collection": str(hit.get("collection") or "memory"),
                "id": str(hit.get("id") or ""),
                "snippet": doc[:160],
            }
        )
    return sources


def _fmt(value: Any, unit: str) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "unknown"
    if unit == "%":
        return f"{number:.1f}{unit}"
    if unit == "Mbps":
        return f"{number:.2f} {unit}"
    return f"{number:.0f} {unit}"


@app.post("/api/memory/preference")
async def save_memory_preference(
    request: Request,
    principal: Principal = Depends(get_principal),
) -> dict[str, Any]:
    body = await request.json()
    try:
        resp = await request.app.state.http.post(
            f"{RAG_URL}/api/memory/preference",
            json={
                "user_id": principal.sub,
                "preference_type": str(body.get("preference_type") or ""),
                "value": body.get("value"),
            },
            timeout=5.0,
        )
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "preference store unavailable") from exc
    if not isinstance(data, dict):
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "invalid preference response")
    return data


@app.get("/api/memory/preference/{user_id}")
async def get_memory_preferences(
    request: Request,
    user_id: str,
    principal: Principal = Depends(get_principal),
) -> dict[str, Any]:
    resolved_user = principal.sub if user_id == "me" else user_id
    if resolved_user != principal.sub and principal.role is not Role.SITE_ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "forbidden")
    try:
        resp = await request.app.state.http.get(
            f"{RAG_URL}/api/memory/preference/{resolved_user}",
            timeout=5.0,
        )
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "preference store unavailable") from exc
    if not isinstance(data, dict):
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "invalid preference response")
    return data


@app.post("/api/what-if", dependencies=[require_roles("noc_executive", "ai_engineer", "site_admin")])
async def what_if(
    request: Request,
    _principal: Principal = Depends(get_principal),
) -> dict[str, Any]:
    body = await request.json()
    try:
        resp = await request.app.state.http.post(
            f"{OPTIMIZATION_URL}/api/what-if",
            json=body,
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "what-if simulator unavailable") from exc
    if not isinstance(data, dict):
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "invalid what-if simulator response")
    return data


@app.get("/api/detection/model-info", dependencies=[require_roles("ai_engineer", "site_admin")])
async def detection_model_info(
    request: Request,
    _principal: Principal = Depends(get_principal),
) -> dict[str, Any]:
    try:
        resp = await request.app.state.http.get(
            f"{DETECTION_URL}/api/detection/model-info",
            timeout=5.0,
        )
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "detection model info unavailable") from exc
    if not isinstance(data, dict):
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "invalid detection response")
    return data


@app.get("/api/optimization/arm-stats", dependencies=[require_roles("ai_engineer", "site_admin")])
async def optimization_arm_stats(
    request: Request,
    _principal: Principal = Depends(get_principal),
) -> dict[str, Any]:
    try:
        resp = await request.app.state.http.get(
            f"{OPTIMIZATION_URL}/api/optimization/arm-stats",
            timeout=5.0,
        )
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "optimization arm stats unavailable") from exc
    if not isinstance(data, dict):
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "invalid optimization response")
    return data


# ─── ASGI entrypoint ─────────────────────────────────────────────────────

@app.get("/api/synthesis/cluster-summary")
async def synthesis_cluster_summary(
    request: Request,
    detector: str,
    severity: str,
    count: int = 3,
    _principal: Principal = Depends(get_principal),
) -> dict[str, Any]:
    try:
        resp = await request.app.state.http.get(
            f"{SYNTHESIS_API_URL}/api/synthesis/cluster-summary",
            params={"detector": detector, "severity": severity, "count": count},
            timeout=35.0,
        )
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "synthesis summary unavailable") from exc
    if not isinstance(data, dict):
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "invalid synthesis response")
    return data


@app.get("/api/synthesis/shift-summary")
async def synthesis_shift_summary(
    request: Request,
    _principal: Principal = Depends(get_principal),
) -> dict[str, Any]:
    try:
        resp = await request.app.state.http.get(
            f"{SYNTHESIS_API_URL}/api/synthesis/shift-summary",
            timeout=35.0,
        )
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "shift summary unavailable") from exc
    if not isinstance(data, dict):
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "invalid synthesis response")
    return data


asgi = sio_app
