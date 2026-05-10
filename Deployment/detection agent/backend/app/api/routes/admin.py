from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Dict, Any
import mlflow

from app.core.config import settings
from app.core.model_loader import get_model_manager
from app.services.monitoring import get_system_metrics

router = APIRouter()

class ThresholdUpdate(BaseModel):
    threshold: float

@router.get("/models")
async def list_models():
    """Liste tous les modèles disponibles dans MLflow"""
    mlflow.set_tracking_uri(settings.MLFLOW_TRACKING_URI)
    client = mlflow.tracking.MlflowClient()
    
    experiment = client.get_experiment_by_name(settings.MLFLOW_EXPERIMENT_NAME)
    if not experiment:
        return {"models": []}
    
    runs = client.search_runs(experiment.experiment_id)
    models = []
    for run in runs:
        models.append({
            "run_id": run.info.run_id,
            "status": run.info.status,
            "start_time": run.info.start_time,
            "metrics": run.data.metrics,
            "params": run.data.params
        })
    
    return {"models": models}

@router.put("/threshold")
async def update_threshold(update: ThresholdUpdate):
    """Met à jour le seuil de détection"""
    if update.threshold <= 0 or update.threshold > 1:
        raise HTTPException(status_code=400, detail="Threshold must be between 0 and 1")
    
    model_manager = get_model_manager()
    old_threshold = model_manager.threshold
    model_manager.update_threshold(update.threshold)
    
    # Log dans MLflow
    with mlflow.start_run(run_name="threshold_update"):
        mlflow.log_param("old_threshold", old_threshold)
        mlflow.log_param("new_threshold", update.threshold)
    
    return {"old_threshold": old_threshold, "new_threshold": update.threshold}

@router.get("/metrics/system")
async def system_metrics():
    """Métriques système et performance"""
    return get_system_metrics()

@router.post("/reload-model")
async def reload_model():
    """Recharge le modèle ML (après mise à jour)"""
    model_manager = get_model_manager()
    model_manager.reload_model()
    return {"status": "reloaded", "threshold": model_manager.threshold}