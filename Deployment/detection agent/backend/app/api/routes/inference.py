from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import List, Dict, Any
from sqlalchemy.orm import Session
import pandas as pd
import mlflow

from app.core.model_loader import get_model_manager
from app.services.inference_service import InferenceService
from app.db.database import get_db, Prediction

router = APIRouter()


class DetectionRequest(BaseModel):
    data: List[Dict[str, Any]] = Field(..., description="Données réseau à analyser")


class DetectionResponse(BaseModel):
    results: List[Dict[str, Any]]
    summary: Dict[str, Any]


@router.post("/detect", response_model=DetectionResponse)
async def detect_anomalies(
    request: DetectionRequest,
    db: Session = Depends(get_db)
):
    """Détecte les anomalies dans un batch de données réseau"""
    try:
        df = pd.DataFrame(request.data)
        inference_service = InferenceService()
        results = inference_service.analyze(df)

        # Persistance en base
        for r in results:
            db.add(Prediction(
                is_anomaly=r["is_anomaly"],
                score=r["score"],
                severity=r["severity"],
                confidence=r["confidence"],
            ))
        db.commit()

        # Log MLflow
        with mlflow.start_run(run_name="inference_batch", nested=True):
            mlflow.log_param("batch_size", len(request.data))
            mlflow.log_metric("anomaly_count", sum(r["is_anomaly"] for r in results))

        summary = {
            "total": len(results),
            "anomalies": sum(r["is_anomaly"] for r in results),
            "normals": sum(not r["is_anomaly"] for r in results),
            "avg_score": sum(r["score"] for r in results) / len(results)
        }

        return DetectionResponse(results=results, summary=summary)

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/detect/single")
async def detect_single(
    data: Dict[str, Any],
    db: Session = Depends(get_db)
):
    """Détection pour un seul échantillon"""
    try:
        df = pd.DataFrame([data])
        inference_service = InferenceService()
        result = inference_service.analyze(df)[0]

        # Persistance en base
        db.add(Prediction(
            is_anomaly=result["is_anomaly"],
            score=result["score"],
            severity=result["severity"],
            confidence=result["confidence"],
        ))
        db.commit()

        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
