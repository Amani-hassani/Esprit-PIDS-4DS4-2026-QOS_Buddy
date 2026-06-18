# Prediction Agent

The Prediction Agent forecasts QoS degradation and service breach risk. It combines feature engineering, XGBoost classifiers, an LSTM temporal model, capacity forecasting, explainability, and incident memory.

## Role In QoS Buddy

The agent receives monitoring windows, estimates future risk across several QoS targets, and returns probabilities, severity, time-to-risk indicators, and explanatory context. In the integrated stack, it runs behind the prediction bridge in `Deployment/qos-buddy`.

## Main Capabilities

- Risk classification for latency, throughput, jitter, congestion, call drop, and MOS degradation.
- Temporal modeling with an LSTM over recent QoS windows.
- Ensemble fusion between snapshot and temporal models.
- Capacity and time-to-breach estimation.
- SHAP-based feature explanations for tree models.
- Incident retrieval through ChromaDB.
- Optional local LLM explanations through Ollama.
- FastAPI endpoints for live inference and dashboard summaries.

## Project Layout

```text
prediction_agent/
|-- main.py                  Training entrypoint
|-- config.py                Central model and threshold configuration
|-- data_pipeline/           Loading, preprocessing, labels, and features
|-- models/                  XGBoost, LSTM, ETA, Prophet, and ensemble code
|-- models/saved/            Packaged trained artifacts for the demo
|-- agent/                   High-level inference interface
|-- backend/                 FastAPI service layer
|-- frontend/                SvelteKit dashboard used during development
|-- rag/                     Incident memory integration
|-- scripts/                 Training, evaluation, and ingestion helpers
|-- tests/                   Smoke, API, lifecycle, and regression tests
`-- requirements.txt
```

## Local Development

Create an environment and install dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Train or refresh local models:

```powershell
python main.py
```

Evaluate models:

```powershell
python scripts/evaluate_models.py --last-15pct
```

Run the backend:

```powershell
python -m uvicorn backend.api_enhanced:app --reload --port 8000
```

Run the frontend:

```powershell
cd frontend
npm install
npm run dev
```

## API Highlights

| Endpoint | Purpose |
| --- | --- |
| `GET /health` | Service health |
| `GET /schema/qos` | Required telemetry schema |
| `POST /predict` | Batch prediction |
| `POST /monitoring/predict` | Monitoring integration alias |
| `GET /predictions` | Recent predictions |
| `GET /dashboard/summary` | Dashboard aggregate payload |
| `POST /monitoring/incidents/sync` | Incident memory sync |

## Artifacts

The `models/saved/` directory contains trained artifacts used by the local demo. They are committed intentionally so reviewers can run the integrated stack without retraining the prediction models.

## Tests

```powershell
pytest -q
```

The test suite includes smoke tests, API checks, storage tests, monitoring lifecycle tests, and regression coverage for known modeling issues.

## Notes

- Real runtime state such as MLflow databases, logs, and local ChromaDB data should not be committed.
- The integrated Docker stack is the recommended path for full-system review.
- The local development path is useful when working on the prediction service in isolation.
