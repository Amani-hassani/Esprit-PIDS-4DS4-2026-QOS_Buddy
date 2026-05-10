import joblib
import numpy as np
from tensorflow import keras
from app.core.config import settings


class ModelManager:
    """Gestionnaire singleton du modèle ML"""

    def __init__(self):
        self.model = None
        self.scaler = None
        self.threshold: float = settings.DEFAULT_THRESHOLD
        self._model_path: str = ""
        self._scaler_path: str = ""

    def load_model(self, model_path: str, scaler_path: str, threshold: float):
        self._model_path = model_path
        self._scaler_path = scaler_path
        self.threshold = threshold
        self.model = keras.models.load_model(model_path)
        self.scaler = joblib.load(scaler_path)

    def reload_model(self):
        """Recharge le modèle depuis les chemins originaux"""
        if not self._model_path:
            raise RuntimeError("Modèle non chargé initialement")
        self.model = keras.models.load_model(self._model_path)
        self.scaler = joblib.load(self._scaler_path)

    def update_threshold(self, new_threshold: float):
        self.threshold = new_threshold


# Instance globale (singleton)
_model_manager: ModelManager | None = None


def get_model_manager() -> ModelManager:
    global _model_manager
    if _model_manager is None:
        raise RuntimeError("ModelManager non initialisé. Vérifiez le lifespan de l'application.")
    return _model_manager


def init_model_manager() -> ModelManager:
    global _model_manager
    _model_manager = ModelManager()
    return _model_manager
