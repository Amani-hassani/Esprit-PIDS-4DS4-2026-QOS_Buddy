from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import mlflow
import os
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from fastapi import Depends

from app.api.routes import inference, metrics, admin
from app.core.config import settings
from app.core.model_loader import init_model_manager, get_model_manager
from app.db.database import init_db, get_db, Prediction


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gestion du cycle de vie de l'application"""
    print("🚀 Démarrage de QoS Buddy Backend...")

    # Initialisation de la base de données
    init_db()

    # Initialisation et chargement du modèle ML
    model_manager = init_model_manager()
    model_manager.load_model(
        model_path=settings.MODEL_PATH,
        scaler_path=settings.SCALER_PATH,
        threshold=settings.THRESHOLD
    )

    # Configuration MLflow
    mlflow.set_tracking_uri(settings.MLFLOW_TRACKING_URI)

    print(f"✅ Modèle chargé. Seuil: {settings.THRESHOLD}")

    yield

    print("🛑 Arrêt de QoS Buddy Backend...")


# Création de l'application
app = FastAPI(
    title="QoS Buddy API",
    description="API pour la détection d'anomalies réseau",
    version="1.0.0",
    lifespan=lifespan
)

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Inclusion des routes
app.include_router(inference.router, prefix="/api/v1", tags=["Inference"])
app.include_router(metrics.router, prefix="/api/v1", tags=["Metrics"])
# FIX: ajout du préfixe /admin manquant
app.include_router(admin.router, prefix="/api/v1/admin", tags=["Admin"])


@app.get("/api/v1/health")
async def health_check():
    return {"status": "healthy", "threshold": settings.THRESHOLD}


@app.get("/api/detection/model-info")
async def model_info(db: Session = Depends(get_db)):
    manager = get_model_manager()
    model_mtime = None
    if os.path.exists(settings.MODEL_PATH):
        model_mtime = datetime.utcfromtimestamp(os.path.getmtime(settings.MODEL_PATH)).date().isoformat()

    features_used = 0
    scaler = getattr(manager, "scaler", None)
    if scaler is not None and getattr(scaler, "n_features_in_", None) is not None:
        features_used = int(scaler.n_features_in_)
    elif getattr(manager.model, "input_shape", None):
        shape = manager.model.input_shape
        if isinstance(shape, (list, tuple)) and len(shape) > 1 and shape[-1] is not None:
            features_used = int(shape[-1])

    since = datetime.utcnow() - timedelta(hours=1)
    recent = db.query(Prediction).filter(Prediction.timestamp >= since).all()
    alerts_last_hour = sum(1 for row in recent if row.is_anomaly)
    avg_confidence = sum(float(row.confidence or 0.0) for row in recent) / len(recent) if recent else 0.0
    false_positive_candidates = sum(
        1
        for row in recent
        if row.is_anomaly and str(row.severity or "").upper() in {"N/A", "LIGHT"}
    )
    false_positive_rate = (
        false_positive_candidates / alerts_last_hour if alerts_last_hour else 0.0
    )

    return {
        "model_type": "Behavioral anomaly detector",
        "last_trained": model_mtime,
        "features_used": features_used,
        "threshold": float(manager.threshold),
        "recent_accuracy": round(max(0.0, min(1.0, avg_confidence / 100.0)), 3),
        "alerts_last_hour": alerts_last_hour,
        "false_positive_rate": round(max(0.0, min(1.0, false_positive_rate)), 3),
    }


@app.get("/")
async def root():
    return {
        "service": "QoS Buddy API",
        "version": "1.0.0",
        "docs": "/docs",
        "redoc": "/redoc"
    }
