"""Central configuration for the QoS Prediction Agent."""

from __future__ import annotations

from pathlib import Path
import os

PROJECT_ROOT: Path = Path(__file__).resolve().parent


def _path_from_env(name: str, default: Path) -> Path:
    raw = os.getenv(name)
    return Path(raw) if raw else default

DATA_RAW_DIR: Path = PROJECT_ROOT / "data" / "raw"
DATA_INCIDENTS_DIR: Path = PROJECT_ROOT / "data" / "incidents"

MODELS_DIR: Path = PROJECT_ROOT / "models"
SAVED_MODELS_DIR: Path = MODELS_DIR / "saved"

RAG_CHROMA_DIR: Path = _path_from_env("RAG_CHROMA_DIR", PROJECT_ROOT / "rag" / "chroma_db")
MONITORING_KPI_PATH: Path = PROJECT_ROOT / "storage" / "monitoring_agent_kpis.csv"
MLFLOW_DB_PATH: Path = _path_from_env("MLFLOW_DB_PATH", PROJECT_ROOT / "storage" / "mlflow.db")
MLFLOW_ARTIFACTS_DIR: Path = _path_from_env("MLFLOW_ARTIFACTS_DIR", PROJECT_ROOT / "storage" / "mlruns")
MLFLOW_TRACKING_URI: str = os.getenv("MLFLOW_TRACKING_URI", f"sqlite:///{MLFLOW_DB_PATH.as_posix()}")
MLFLOW_UI_URL: str = os.getenv("MLFLOW_UI_URL", "http://127.0.0.1:5000")

QOS_GLOB: str = "qos_timeseries_*.csv"
INCIDENT_GLOB: str = "incidents_*.csv"

# Time series / modeling
# Label horizon: 120 steps × 30s = 60 minutes (business SLA)
# Used consistently for both binary risk labels AND time-to-event (ETA) labels
LABEL_HORIZON_STEPS: int = 120
FUTURE_WINDOW_STEPS: int = 120  # Synchronized with LABEL_HORIZON_STEPS (was 10, now 120)
LSTM_WINDOW: int = 20
PROPHET_HORIZON_PERIODS: int = LABEL_HORIZON_STEPS  # Alias for clarity (120 × 30s = 60 minutes)
SECONDS_PER_STEP: float = 30.0

# Master threshold for congestion events
CONGESTION_INDEX_THRESHOLD: float = 0.85

# Aliases for API clarity (they reference the master)
PROPHET_CAPACITY_THRESHOLD: float = CONGESTION_INDEX_THRESHOLD

# Thresholds — verified to produce evaluable labels in TimeSeriesSplit(5) test fold
LATENCY_THRESHOLD_MS        = 95.0   # rolling mean threshold
THROUGHPUT_THRESHOLD_MBPS   = 3.0     # rolling min threshold
JITTER_THRESHOLD_MS         = 20.0    # rolling mean threshold
MOS_THRESHOLD               = 3.0     # rolling min threshold
ANOMALY_SCORE_THRESHOLD     = 0.85    # rolling MAX threshold for call_drop_risk

# IMPORTANT: use n_splits=5, NOT 3
# n_splits=3 puts the last 25% (all-anomalous Apr period) as test → near-constant labels
# n_splits=5 gives a smaller, better-positioned test fold with label variance
N_SPLITS = 5

# Ensemble (XGB + LSTM only; Prophet never blended)
ENSEMBLE_XGB_WEIGHT: float = 0.55
ENSEMBLE_LSTM_WEIGHT: float = 0.45

# ═══════════════════════════════════════════════════════════════
# CLASS IMBALANCE HANDLING (NEW: Critical for production safety)
# ═══════════════════════════════════════════════════════════════
SCALE_POS_WEIGHT_CLAMP_MAX: float = 10.0      # Max allowed scale_pos_weight
SCALE_POS_WEIGHT_CLAMP_MIN: float = 0.5       # Min allowed (for reversed imbalance)
MIN_POSITIVE_SAMPLES_PER_FOLD: int = 5        # Hard minimum for fold evaluation
MIN_POSITIVE_SAMPLES_TRAINING: int = 3        # Hard minimum for model training

# ═══════════════════════════════════════════════════════════════
# LABEL AGGREGATION STRATEGY (NEW: Documented design rationale)
# ═══════════════════════════════════════════════════════════════
LABEL_AGGREGATION_STRATEGY: dict = {
    "call_drop_risk": {
        "aggregation": "rolling_max",
        "threshold": 0.85,
        "min_periods": 1,
        "rationale": "MAX captures ANY spike. Single anomaly sufficient signal.",
    },
    "latency_breach_risk": {
        "aggregation": "rolling_mean",
        "threshold": 95.0,
        "min_periods": 3,
        "rationale": "MEAN captures sustained degradation, not transient spikes.",
    },
    "throughput_risk": {
        "aggregation": "rolling_min",
        "threshold": 3.0,
        "min_periods": 3,
        "rationale": "MIN captures worst sustained degradation.",
    },
    "jitter_risk": {
        "aggregation": "rolling_mean",
        "threshold": 20.0,
        "min_periods": 3,
        "rationale": "MEAN captures sustained VoIP quality degradation.",
    },
    "congestion_risk": {
        "aggregation": "rolling_max",
        "threshold": 0.85,
        "min_periods": 1,
        "rationale": "FIXED from point_shift: Now rolling_max for consistency.",
    },
    "mos_risk": {
        "aggregation": "rolling_min",
        "threshold": 3.0,
        "min_periods": 3,
        "rationale": "MIN captures worst call quality.",
    },
}

# Targets (fixed order for matrices and saved models)
TARGET_NAMES: tuple[str, ...] = (
    "call_drop_risk",
    "latency_breach_risk",
    "throughput_risk",
    "jitter_risk",
    "congestion_risk",
    "mos_risk",
)

# ═══════════════════════════════════════════════════════════════
# XGBOOST HYPERPARAMETERS (Tuned for telecom QoS prediction)
# ═══════════════════════════════════════════════════════════════
XGB_HYPERPARAMETERS = {
    'objective': 'binary:logistic',
    'eval_metric': 'logloss',
    'use_label_encoder': False,
    'n_estimators': 500,
    'learning_rate': 0.03,
    'max_depth': 5,
    'min_child_weight': 2,
    'subsample': 0.8,
    'colsample_bytree': 0.8,
    'random_state': 42,
    'n_jobs': -1,
    # scale_pos_weight computed per-target based on class imbalance
}

# ═══════════════════════════════════════════════════════════════
# LSTM HYPERPARAMETERS (Multi-label temporal model)
# ═══════════════════════════════════════════════════════════════
LSTM_HYPERPARAMETERS = {
    'input_dim': None,  # Set dynamically based on feature count
    'hidden_units': 128,
    'n_layers': 2,
    'dropout': 0.2,
    'n_targets': len(TARGET_NAMES),  # 6 binary outputs
    'batch_size': 64,
    'epochs': 25,
    'learning_rate': 0.001,
    'loss_function': 'binary_cross_entropy',  # Per-target independent
    'optimizer': 'adam',
    'device': 'cuda',  # Falls back to 'cpu' if unavailable
}

# ═══════════════════════════════════════════════════════════════
# PROPHET FORECASTING CONFIGURATION
# ═══════════════════════════════════════════════════════════════
PROPHET_CONFIG = {
    'yearly_seasonality': False,
    'weekly_seasonality': False,
    'daily_seasonality': True,
    'interval_width': 0.95,
    'changepoint_prior_scale': 0.05,
}

# ═══════════════════════════════════════════════════════════════
# SHAP EXPLAINABILITY CONFIGURATION
# ═══════════════════════════════════════════════════════════════
SHAP_CONFIG = {
    'explainer_type': 'TreeExplainer',  # For XGBoost tree models
    'top_k_features': 5,
    'background_samples': 100,  # For SHAP value computation
}

# ═══════════════════════════════════════════════════════════════
# RAG (RETRIEVAL-AUGMENTED GENERATION) CONFIGURATION
# ═══════════════════════════════════════════════════════════════
RAG_CONFIG = {
    'embedding_model': 'sentence-transformers/all-MiniLM-L6-v2',
    'chunk_size': 500,
    'top_k_retrieval': 3,
    'similarity_threshold': 0.5,
    'persist_directory': str(RAG_CHROMA_DIR),
}

# ═══════════════════════════════════════════════════════════════
# LLM (LOCAL OLLAMA) CONFIGURATION
# ═══════════════════════════════════════════════════════════════
OLLAMA_DEFAULT_URL: str = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_DEFAULT_MODEL: str = os.getenv("OLLAMA_MODEL", os.getenv("LLM_PRIMARY", "gemma3:1b"))
LLM_CONFIG = {
    'url': OLLAMA_DEFAULT_URL,
    'model': OLLAMA_DEFAULT_MODEL,
    'timeout': 120,  # seconds
    'fallback_to_json': True,  # If Ollama unavailable
}

# ═══════════════════════════════════════════════════════════════
# PRODUCTION MONITORING & ALERTING
# ═══════════════════════════════════════════════════════════════
ALERT_CONFIG = {
    'severity_thresholds': {
        'critical': 0.80,  # prob > 0.80 = critical alert
        'high': 0.60,      # prob > 0.60 = high alert
        'medium': 0.40,    # prob > 0.40 = medium alert
        'low': 0.20,       # prob > 0.20 = low alert
    },
    'alert_timeout_minutes': 30,  # Suppress duplicate alerts within 30 min
    'max_alerts_per_node': 5,  # Max concurrent alerts per node
}

# ═══════════════════════════════════════════════════════════════
# DATA PIPELINE CONFIGURATION
# ═══════════════════════════════════════════════════════════════
DATA_PIPELINE_CONFIG = {
    'train_test_split_ratio': 0.80,
    'random_seed': 42,
    'missing_value_strategy': 'median',  # For numeric; 'mode' for categorical
    'outlier_detection': 'iqr',  # Interquartile range method
    'feature_scaling': 'minmax',  # [0, 1] range for deep learning
}

# Create required directories
SAVED_MODELS_DIR.mkdir(parents=True, exist_ok=True)
RAG_CHROMA_DIR.mkdir(parents=True, exist_ok=True)
(PROJECT_ROOT / "logs").mkdir(parents=True, exist_ok=True)
(PROJECT_ROOT / "artifacts").mkdir(parents=True, exist_ok=True)
MONITORING_KPI_PATH.parent.mkdir(parents=True, exist_ok=True)
MLFLOW_ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
