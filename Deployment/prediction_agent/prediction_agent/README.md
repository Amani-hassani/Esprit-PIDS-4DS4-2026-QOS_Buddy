# 🚀 QoS AI Prediction Agent

**Production-grade telecom risk prediction stack** with ensemble ML, capacity forecasting, explainability, and LLM-powered alerting.

---

## ⚡ Quick Start (Local Development)

### 1. Install Dependencies
```bash
python -m venv .venv
.venv\Scripts\activate  # Windows
# or: source .venv/bin/activate  # macOS/Linux

pip install -r requirements.txt
```

### 2. Prepare Data
Place QoS timeseries CSVs in `data/raw/`:
```
data/raw/qos_timeseries_*.csv
```

### 3. Train Models
```bash
python main.py
```

Trains 6 XGBoost classifiers, 1 LSTM multi-label model, Prophet ETA, and builds ensemble.

### 4. Evaluate
```bash
python scripts/evaluate_models.py --last-15pct
```

### 5. Run Live Dashboard

**Terminal 1 - Backend API:**
```bash
.venv\Scripts\activate
python -m uvicorn backend.api_enhanced:app --reload --port 8000
```

**Terminal 2 - MLflow Tracking:**
```bash
.venv\Scripts\activate
mlflow ui --backend-store-uri sqlite:///mlflow.db --workers 1
```

**Terminal 3 - Frontend:**
```bash
cd frontend
npm install
npm run dev
```

**Access:**
- Dashboard: http://127.0.0.1:5173
- API Docs: http://localhost:8000/docs
- MLflow UI: http://localhost:5000

---

## 🏗️ Architecture

### Core ML Pipeline

| Layer | Technology | Purpose |
|-------|------------|---------|
| **Label Engineering** | Python | 6 binary targets over 120-step (60-min) horizon |
| **Feature Engineering** | Pandas + NumPy | Temporal lags, rolling stats, anomaly scores |
| **Risk Classification** | XGBoost (6×) | Per-target binary classifiers with calibration |
| **Temporal Modeling** | LSTM | Multi-label RNN (20-step window) |
| **Ensemble Fusion** | Custom | 55% XGBoost + 45% LSTM (probability-weighted) |
| **Capacity Forecasting** | Prophet | Time-to-congestion ETA with uncertainty |
| **Explainability** | SHAP | Feature importance per model & target |
| **RAG** | ChromaDB + Ollama | Similar incident retrieval + LLM alert generation |

### Stack

- **Backend**: FastAPI + Uvicorn + Pydantic
- **Frontend**: SvelteKit dashboard
- **Storage**: SQLite (`storage/predictions.db`, `mlflow.db`)
- **Tracking**: MLflow with local backend
- **Deployment**: Docker Compose (optional)

---

## 📊 Model Details

### 1. XGBoost (Snapshot Risk)
- 6 per-target binary classifiers
- TimeSeriesSplit(5) for temporal validation
- Scale_pos_weight balancing + isotonic calibration
- Each model: ~300-500 trees, depth=5-7

### 2. LSTM (Temporal Risk)
- Multi-label RNN: 2 layers (128 → 64 units)
- Input window: 20 timesteps (10 minutes)
- Dropout=0.2, Adam optimizer
- Detects trends over recent history

### 3. Ensemble (Combined Risk)
- Fusion: 0.55×P(XGB) + 0.45×P(LSTM)
- Output: 6 risk probabilities (0-1)
- Per-prediction confidence via ensemble variance

### 4. Prophet (Capacity ETA)
- Forecasts congestion_index 120 periods ahead
- Detects threshold-crossing timeline
- Returns: minutes to exhaustion or ∞

### 5. SHAP (Why the Risk)
- TreeExplainer for XGBoost models
- LSTM explainability via attention/gradient
- Top features per prediction and target

### 6. RAG (Incident Context)
- ChromaDB vector store (incident descriptions)
- Semantic similarity search
- Ollama LLM generates NOC-ready explanations

---

## 📋 Severity Levels

Based on max(probability - threshold):

```
🟢 NORMAL   : margin < -0.15     (no action)
🔵 WATCH    : -0.15 ≤ margin < -0.05   (monitor)
🟡 WARNING  : -0.05 ≤ margin < 0.05    (investigate)
🟠 HIGH     : 0.05 ≤ margin < 0.15     (escalate)
🔴 CRITICAL : margin ≥ 0.15             (immediate action)
```

---

## 🔧 Configuration (config.py)

**Key Parameters:**
```python
LABEL_HORIZON_STEPS = 120           # 60 minutes @ 30s/step
LSTM_WINDOW = 20                    # 10 minutes of history
PROPHET_HORIZON_PERIODS = 120       # Forecast window

LATENCY_THRESHOLD_MS = 95.0
THROUGHPUT_THRESHOLD_MBPS = 3.0
JITTER_THRESHOLD_MS = 20.0
MOS_THRESHOLD = 3.0
CONGESTION_INDEX_THRESHOLD = 0.85

ENSEMBLE_XGB_WEIGHT = 0.55
ENSEMBLE_LSTM_WEIGHT = 0.45

N_SPLITS = 5                        # TimeSeriesSplit for validation
SCALE_POS_WEIGHT_CLAMP_MAX = 10.0   # Imbalance handling
```

---

## 📁 Project Structure

```
prediction_agent/
├── main.py                      # End-to-end training pipeline
├── config.py                    # Central configuration
├── requirements.txt             # Python dependencies
│
├── data_pipeline/
│   ├── loader.py               # QoS CSV loading
│   ├── preprocessor.py         # Imputation, scaling
│   ├── label_engineer.py       # 6-target label generation
│   └── features.py             # Temporal feature engineering
│
├── models/
│   ├── xgb_trainer.py          # 6× XGBoost classifiers
│   ├── lstm_trainer.py         # Multi-label LSTM
│   ├── prophet_forecaster.py   # ETA forecasting
│   ├── eta_trainer.py          # Alternative ETA (legacy)
│   └── ensemble.py             # Inference fusion
│
├── agent/
│   ├── prediction_agent.py     # High-level inference API
│   └── result.py               # PredictionResult dataclass
│
├── evaluation/
│   └── evaluator.py            # Metrics: AUC, F1, confusion matrix
│
├── explainability/
│   └── shap_explainer.py       # SHAP feature importance
│
├── rag/
│   └── incident_store.py       # ChromaDB + incident retrieval
│
├── llm/
│   ├── explainer.py            # Ollama LLM integration
│   └── prompts/                # System prompts
│
├── storage/
│   └── results_store.py        # Results persistence
│
├── backend/
│   ├── api_enhanced.py         # FastAPI REST endpoints
│   └── service.py              # Monitoring integration + autonomous ops
│
├── frontend/
│   ├── build/                  # Built static files
│   ├── src/routes/+page.svelte # Home page
│   └── package.json            # Node dependencies
│
├── scripts/
│   ├── train_all.py            # Alternative training entry
│   ├── evaluate_models.py      # Holdout evaluation
│   └── ingest_incidents.py     # ChromaDB population
│
├── tests/
│   ├── test_smoke.py           # Integration tests
│   ├── test_storage.py         # Database tests
│   └── conftest.py             # Pytest fixtures
│
├── docker-compose.yml          # Full stack orchestration
├── backend.dockerfile          # Python service
├── setup.sh / setup.bat        # Automated setup
│
└── [Documentation]
    ├── ARCHITECTURE_DIAGRAM.md # Data flow diagrams
    └── MODERN_STACK_DEPLOYMENT.md # Deployment guide
```

---

## 🚀 API Endpoints (FastAPI)

**Predictions:**
```
POST /predict                    # Monitoring-agent batch prediction
POST /monitoring/predict         # Monitoring-agent alias
GET /predictions?limit=25        # Recent predictions
```

**Autonomous Ops:**
```
POST /monitoring/incidents/sync  # ChromaDB incident sync
POST /ops/autonomous/run-once    # Full autonomous cycle
```

**System:**
```
GET /health                     # Full system status
GET /schema/qos                # Required telemetry schema
GET /dashboard/summary         # Dashboard aggregate payload
GET /ops/status                # Control-plane status
```

**MLflow:**
```
GET /mlflow/runs               # Recent experiments
GET /mlflow/best-run          # Best model by metric
```

---

## 🐳 Production Deployment (Docker)

```bash
docker-compose build
docker-compose up -d
```

Services:
- **backend** (FastAPI): :8000
- **frontend** (Static): :5173
- **mlflow**: :5000
- **ollama** (LLM): :11434

---

## 🤖 LLM Integration (Ollama)

```bash
# Pull a model
ollama pull llama3

# Ensure service is running
ollama serve
```

Then set in environment or config:
```python
OLLAMA_MODEL = "llama3"
```

---

## 📊 Example Prediction Output

```json
{
  "node_id": "zone_A_node_15",
  "timestamp": "2025-04-26T14:32:00Z",
  "risk_probs": {
    "call_drop": 0.12,
    "latency_risk": 0.45,
    "throughput_risk": 0.08,
    "jitter_risk": 0.22,
    "congestion_risk": 0.78,
    "mos_risk": 0.35
  },
  "capacity_exhaustion_eta_min": 45.0,
  "severity": "HIGH",
  "shap_features": {
    "congestion_risk": [
      {"feature": "congestion_index", "importance": 0.42},
      {"feature": "bandwidth_usage_pct", "importance": 0.28}
    ]
  },
  "retrieved_incidents": [
    "Network congestion incident on 2025-04-20 resolved in 30 min",
    "Similar pattern detected: backup link activation recommended"
  ],
  "explanation": "HIGH RISK: Congestion predicted in 45 minutes. Current bandwidth at 87% capacity. Recommend activating backup link and monitoring call quality.",
  "eta_debug_status": "ok"
}
```

---

## 🧪 Testing

```bash
# Run all tests
pytest tests/ -v

# Specific test
pytest tests/test_smoke.py::test_inference

# With coverage
pytest tests/ --cov=. --cov-report=html
```

---

## 📝 Model Training Workflow

1. **Data Loading** → Load QoS CSVs from `data/raw/`
2. **Preprocessing** → Imputation, scaling (fit on train only)
3. **Feature Engineering** → Lags, rolling stats, anomaly scores
4. **Label Building** → 6 binary targets over 120-step horizon
5. **Model Training** → XGBoost (per-target) + LSTM (all targets) + Prophet + ETA models
6. **Validation** → TimeSeriesSplit(5) evaluation
7. **Calibration** → Isotonic regression on XGBoost
8. **MLflow Tracking** → Log params, metrics, models
9. **Evaluation** → AUC, AP, F1 per target
10. **Save Artifacts** → Models to `models/saved/`

---

## 🔗 Quick Links

- [API Documentation](http://localhost:8000/docs) - Interactive Swagger UI
- [MLflow Dashboard](http://localhost:5000) - Experiment tracking
- [Live Dashboard](http://127.0.0.1:5173) - Real-time predictions
- [Architecture Diagram](ARCHITECTURE_DIAGRAM.md) - System design
- [Deployment Guide](MODERN_STACK_DEPLOYMENT.md) - Production setup

---

## 📞 Troubleshooting

**Backend won't start:**
```bash
lsof -i :8000  # Check port 8000
kill -9 <PID>
```

**MLflow multiprocessing issue (Windows):**
```bash
mlflow ui --backend-store-uri sqlite:///mlflow.db --workers 1
```

**No models found:**
```bash
python main.py  # Train first
```

**LLM not responding:**
```bash
ollama serve  # Start Ollama
# Wait 3-5 seconds for initialization
```

---

## 📄 License & Credits

Built with: XGBoost, LightGBM, PyTorch (LSTM), Prophet, SHAP, ChromaDB, FastAPI, SvelteKit, MLflow.

---

**Last updated**: April 26, 2026 | **Version**: 2.0 (Production-ready)

## Important notes

- **Label leakage prevention**: anomaly_flag, anomaly_type, anomaly_score excluded from inputs
- **Feature alignment**: XGB and LSTM use identical feature sets (resolve_feature_columns)
- **Time series integrity**: TimeSeriesSplit (no shuffle), MinMaxScaler fit on train only
- **Probability bounds**: outputs clipped to [0,1]; NaN/Inf feature values imputed

## Tests

```bash
pytest -q  # Run all tests
```

Includes smoke tests (imports), unit tests (modeling phase fixes), and integration tests.
