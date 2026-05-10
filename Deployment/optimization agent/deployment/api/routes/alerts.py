from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from ...core.access import Principal
from ...store.repos import AlertsRepo
from ..deps import engineer_required, viewer_required
from ..events import get_bus


router = APIRouter(prefix="/api/alerts", tags=["alerts"])


@router.get("")
def list_alerts(
    unacknowledged_only: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=500),
    principal: Principal = Depends(viewer_required),
):
    return {
        "items": AlertsRepo.list_recent(
            limit=limit,
            unacknowledged_only=unacknowledged_only,
        )
    }


@router.post("/{alert_id}/acknowledge")
def acknowledge(
    alert_id: str,
    principal: Principal = Depends(engineer_required),
):
    updated = AlertsRepo.acknowledge(alert_id, principal.token)
    if not updated:
        raise HTTPException(status_code=404, detail="alert not found")
    bus = get_bus()
    bus.publish(
        "alerts",
        {"alert_id": alert_id, "acknowledged": True, "actor": principal.role},
    )
    return {"alert": updated}
