# QoS Prediction Agent

Production telecom risk prediction stack: load QoS CSV data, engineer 6 binary labels over a forward-looking horizon, train XGBoost (per-target) + multi-label LSTM, predict with ensemble fusion (0.55 XGB + 0.45 LSTM), forecast capacity ETA via Prophet, explain predictions with SHAP, retrieve similar incidents from ChromaDB, and generate NOC alerts via Ollama.

## Quick start

**Install & setup** (Python 3.10+)
```bash
pip install -r requirements.txt
```

**Data placement**
- QoS: `data/raw/qos_timeseries_*.csv`
- Incidents (optional): `data/incidents/incidents_*.csv`

**Train models**
```bash
python main.py
# or
python scripts/train_all.py
```

**Evaluate models**
```bash
python scripts/evaluate_models.py [--last-15pct] [--max-rows 500]
```

**Ingest incidents into ChromaDB (optional)**
```bash
python scripts/ingest_incidents.py [--replace]
```

**Launch Streamlit UI**
```bash
streamlit run app/streamlit_app.py
```

## Architecture overview

| Component | What it does |
|-----------|--------------|
| **Labels** | 6 binary targets (call_drop, latency, throughput, jitter, congestion, mos) computed per node_id over 120-step horizon |
| **Features** | Schema columns + engineered metrics (lags, rolling stats) with leakage prevention |
| **XGBoost** | 6 per-target classifiers, TimeSeriesSplit(5), scale_pos_weight + isotonic calibration |
| **LSTM** | Multi-target RNN, window=20 steps, MinMaxScaler fit on train only |
| **Ensemble** | Inference fusion: 0.55×XGB + 0.45×LSTM (probability-based) |
| **Prophet** | Capacity exhaustion ETA (separate from risk classification) |
| **SHAP** | Feature importance per model and target |
| **RAG** | ChromaDB incident retrieval + Ollama alert generation |

## Model explanation (1-minute pitch)

1. **XGBoost** = snapshot risk (instant detection via current features)
2. **LSTM** = temporal risk (trend detection over recent history)  
3. **Ensemble** = combined view (weighted fusion of both signals)
4. **SHAP** = why the risk is high (which features drive the prediction)
5. **RAG + LLM** = operationalize (retrieve similar incidents → generate NOC alert)

## Severity scale

Based on max(probability - threshold):

- **normal**: margin < -0.15
- **watch**: -0.15 ≤ margin < -0.05
- **warning**: -0.05 ≤ margin < 0.05
- **high**: 0.05 ≤ margin < 0.15
- **critical**: margin ≥ 0.15

## Key configuration (config.py)

**Paths**: `DATA_RAW_DIR`, `DATA_INCIDENTS_DIR`, `SAVED_MODELS_DIR`, `RAG_CHROMA_DIR`

**Horizons**: `FUTURE_WINDOW_STEPS=120`, `LSTM_WINDOW=20`, `PROPHET_HORIZON_PERIODS=60`

**Thresholds**: `LATENCY_THRESHOLD_MS`, `THROUGHPUT_THRESHOLD_MBPS`, `JITTER_THRESHOLD_MS`, `MOS_THRESHOLD`, `CONGESTION_THRESHOLD`

**Model weights**: `ENSEMBLE_XGB_WEIGHT=0.55`, `ENSEMBLE_LSTM_WEIGHT=0.45`

**LLM**: `OLLAMA_MODEL` (env var or config)

## Inference output (PredictionResult)

- `risk_probs`: dict of 6 probabilities
- `capacity_exhaustion_eta_min`: minutes until congestion (Prophet)
- `severity`: normal/watch/warning/high/critical
- `shap_features`: per-target feature importance
- `retrieved_incidents`: similar past incidents from ChromaDB
- `explanation`: NOC-ready alert text
- `eta_debug_status`: ok/no_crossing/prophet_error

## Ollama setup

```bash
ollama pull llama3  # or your preferred model
export OLLAMA_MODEL=llama3
# Ensure ollama serve is running on localhost:11434
```

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