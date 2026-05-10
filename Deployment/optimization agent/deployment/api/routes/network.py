from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from ...core.access import (
    Principal,
    clear_session_cookie_kwargs,
    set_session_cookie_kwargs,
)
from ...data import (
    dataset_summary,
    fleet_health,
    root_cause_feed,
    timeseries,
)
from ...telemetry_cache import telemetry_snapshot_payload
from ...tools import ToolContext, run_tool
from ...store.repos import SessionsRepo
from .._json import json_safe
from ..deps import viewer_required


router = APIRouter(prefix="/api", tags=["network"])


def _tool_success_or_503(payload: dict) -> dict:
    error = payload.get("error")
    if error:
        raise HTTPException(status_code=503, detail=str(error))
    return payload


@router.get("/snapshot")
def snapshot(
    cell_id: str | None = Query(default=None),
    principal: Principal = Depends(viewer_required),
):
    return json_safe(telemetry_snapshot_payload(cell_id))


@router.get("/kpis")
def kpis(
    cell_id: str | None = Query(default=None),
    principal: Principal = Depends(viewer_required),
):
    ctx = ToolContext(decision_id=None, principal_token=principal.token, principal_role=principal.role)
    return json_safe(_tool_success_or_503(run_tool("read_kpis", {"cell_id": cell_id}, ctx)))


@router.get("/timeseries")
def ts(
    cell_id: str | None = Query(default=None),
    limit: int = Query(default=160, ge=10, le=1000),
    principal: Principal = Depends(viewer_required),
):
    return {"points": json_safe(timeseries(cell_id, limit=limit))}


@router.get("/topology")
def topology(
    focus: str | None = Query(default=None),
    principal: Principal = Depends(viewer_required),
):
    ctx = ToolContext(decision_id=None, principal_token=principal.token, principal_role=principal.role)
    return json_safe(_tool_success_or_503(run_tool("query_topology", {"focus_node_id": focus}, ctx)))


@router.get("/fleet")
def fleet(principal: Principal = Depends(viewer_required)):
    return json_safe(fleet_health())


@router.get("/root-causes")
def root_causes(
    limit: int = Query(default=80, ge=1, le=500),
    principal: Principal = Depends(viewer_required),
):
    return {"items": json_safe(root_cause_feed(limit=limit))}


@router.get("/incidents")
def incidents(
    cell_id: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=200),
    principal: Principal = Depends(viewer_required),
):
    ctx = ToolContext(decision_id=None, principal_token=principal.token, principal_role=principal.role)
    return json_safe(_tool_success_or_503(run_tool("fetch_incidents", {"cell_id": cell_id, "limit": limit}, ctx)))


@router.get("/dataset")
def dataset(principal: Principal = Depends(viewer_required)):
    return json_safe(dataset_summary())


@router.get("/me")
def me(principal: Principal = Depends(viewer_required)):
    return {"token": principal.token, "role": principal.role}


@router.post("/session")
def create_session(response: Response, principal: Principal = Depends(viewer_required)):
    session = SessionsRepo.create(principal_token=principal.token, principal_role=principal.role)
    response.set_cookie(**set_session_cookie_kwargs(str(session["id"])))
    return {"ok": True, "role": principal.role, "session_id": session["id"], "expires_at": session["expires_at"]}


@router.delete("/session")
def clear_session(request: Request, response: Response):
    session_id = request.cookies.get(clear_session_cookie_kwargs()["key"])
    if session_id:
        SessionsRepo.revoke(session_id, actor="session-owner")
    response.delete_cookie(**clear_session_cookie_kwargs())
    return {"ok": True}
