from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from ...core.access import Principal
from ...store.repos import SessionsRepo
from ..deps import lead_required


router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.get("")
def list_sessions(
    limit: int = Query(default=100, ge=1, le=500),
    principal: Principal = Depends(lead_required),
):
    return {"items": SessionsRepo.list_active(limit=limit)}


@router.delete("/{session_id}")
def revoke_session(
    session_id: str,
    principal: Principal = Depends(lead_required),
):
    row = SessionsRepo.revoke(session_id, actor=principal.token)
    if row is None:
        raise HTTPException(status_code=404, detail="session not found")
    return {"session": row}
