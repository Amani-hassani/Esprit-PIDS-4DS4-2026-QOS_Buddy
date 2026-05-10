from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import List
from datetime import datetime

from app.db.database import get_db, Prediction
from app.services.monitoring import get_system_metrics

router = APIRouter()


@router.get("/metrics/system")
async def system_metrics():
    """Métriques système (CPU, mémoire, réseau)"""
    return get_system_metrics()


@router.get("/metrics/realtime")
async def realtime_metrics(db: Session = Depends(get_db)):
    """Snapshot temps réel : dernière prédiction + métriques système"""
    last = db.query(Prediction).order_by(desc(Prediction.timestamp)).first()
    return {
        "timestamp": datetime.utcnow().isoformat(),
        "metrics": {
            "last_score": last.score if last else None,
            "last_is_anomaly": last.is_anomaly if last else None,
            **get_system_metrics()
        }
    }


@router.get("/metrics/history")
async def prediction_history(
    limit: int = Query(default=100, le=1000),
    db: Session = Depends(get_db)
):
    """Historique des prédictions enregistrées en base"""
    rows = (
        db.query(Prediction)
        .order_by(desc(Prediction.timestamp))
        .limit(limit)
        .all()
    )
    return {
        "predictions": [
            {
                "id": r.id,
                "timestamp": r.timestamp.isoformat(),
                "is_anomaly": r.is_anomaly,
                "score": r.score,
                "severity": r.severity,
                "confidence": r.confidence,
            }
            for r in rows
        ]
    }
