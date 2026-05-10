from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from ..core.settings import get_settings
from ..data import DataUnavailableError
from ..llmops.prompts import register_all as register_prompts
from ..release import frontend_build_status
from .events import get_bus
from .routes import agent, alerts, approvals, audit, integrations, network, ops, review, sessions, stream, tickets, what_if
from .watchers import start_agent_runtime, start_sla_watcher


logger = logging.getLogger("qos_buddy.api")


def _lifespan():
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Register prompts eagerly so the registry endpoint is never empty.
        try:
            register_prompts()
        except Exception:
            logger.exception("prompt registry warm-up failed; continuing")
        bus = get_bus()
        sla_handle = start_sla_watcher(bus)
        agent_handle = start_agent_runtime(bus)
        app.state.sla_watcher = sla_handle
        app.state.agent_runtime = agent_handle
        try:
            yield
        finally:
            for handle in (agent_handle, sla_handle):
                if handle is None:
                    continue
                handle.cancel()
                try:
                    await handle.task
                except BaseException:
                    pass

    return lifespan


def create_app() -> FastAPI:
    settings = get_settings()
    # Register prompts eagerly so the registry endpoint is never empty, even in the TestClient-free
    # path used by the httpx/ASGITransport-based harness.
    try:
        register_prompts()
    except Exception:
        logger.exception("prompt registry warm-up failed; continuing")

    app = FastAPI(
        title="QoS Buddy NOC",
        version="3.0.0",
        description="Agentic RC diagnosis + policy-gated action pipeline with local-Qwen reasoning.",
        lifespan=_lifespan(),
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.api.cors_allowed_origins) or [],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(network.router)
    app.include_router(agent.router)
    app.include_router(audit.router)
    app.include_router(approvals.router)
    app.include_router(alerts.router)
    app.include_router(ops.router)
    app.include_router(review.router)
    app.include_router(sessions.router)
    app.include_router(stream.router)
    app.include_router(integrations.router)
    app.include_router(tickets.router)
    app.include_router(what_if.router)

    @app.exception_handler(DataUnavailableError)
    async def data_unavailable_handler(_request, exc: DataUnavailableError) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    @app.get("/api/ping")
    def ping() -> JSONResponse:
        return JSONResponse({"ok": True, "service": "qos_buddy", "version": app.version})

    _mount_frontend(app, settings.paths.frontend_build)
    return app


def _mount_frontend(app: FastAPI, build_dir: Path) -> None:
    """Mount the built SvelteKit output only when it matches the current frontend source."""
    status = frontend_build_status(build_dir=build_dir)
    if not status.build_exists or not status.index_exists:
        logger.info("frontend build %s not present - serving API only", build_dir)
        return
    if not status.ok:
        logger.warning("frontend build at %s is not mountable: %s", build_dir, status.detail)
        return
    app.mount("/", StaticFiles(directory=str(build_dir), html=True), name="frontend")
