from pydantic_settings import BaseSettings
from typing import List
import os


class Settings(BaseSettings):
    # API
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    API_WORKERS: int = 4
    API_RELOAD: bool = False

    # CORS
    CORS_ORIGINS: List[str] = [
        "http://localhost:5173",
        "http://localhost:4173",
        "http://localhost:80",
        "http://127.0.0.1:5173",
    ]

    # Database
    DATABASE_URL: str = "sqlite:///./data/app.db"

    # ML Models
    MODEL_PATH: str = "./models/agent_detection.keras"
    SCALER_PATH: str = "./models/scaler.pkl"
    THRESHOLD_PATH: str = "./models/threshold.pkl"
    DEFAULT_THRESHOLD: float = 0.2564

    # MLflow
    MLFLOW_TRACKING_URI: str = "http://localhost:5000"
    MLFLOW_EXPERIMENT_NAME: str = "qos_anomaly_detection"

    # Logging
    LOG_LEVEL: str = "INFO"

    # Security
    SECRET_KEY: str = "change-this-secret-key-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # Batch
    MAX_BATCH_SIZE: int = 1000

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

    @property
    def THRESHOLD(self) -> float:
        """Charge le seuil depuis le fichier pkl si disponible, sinon utilise DEFAULT_THRESHOLD"""
        if os.path.exists(self.THRESHOLD_PATH):
            import joblib
            return float(joblib.load(self.THRESHOLD_PATH))
        return self.DEFAULT_THRESHOLD


settings = Settings()
