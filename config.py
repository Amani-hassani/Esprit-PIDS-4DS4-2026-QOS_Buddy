"""Central configuration for the QoS Prediction Agent."""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT: Path = Path(__file__).resolve().parent

DATA_RAW_DIR: Path = PROJECT_ROOT / "data" / "raw"
DATA_INCIDENTS_DIR: Path = PROJECT_ROOT / "data" / "incidents"

MODELS_DIR: Path = PROJECT_ROOT / "models"
SAVED_MODELS_DIR: Path = MODELS_DIR / "saved"

RAG_CHROMA_DIR: Path = PROJECT_ROOT / "rag" / "chroma_db"

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

# LLM
OLLAMA_DEFAULT_URL: str = "http://localhost:11434"
OLLAMA_DEFAULT_MODEL: str = "gemma3:1b"


SAVED_MODELS_DIR.mkdir(parents=True, exist_ok=True)
RAG_CHROMA_DIR.mkdir(parents=True, exist_ok=True)
