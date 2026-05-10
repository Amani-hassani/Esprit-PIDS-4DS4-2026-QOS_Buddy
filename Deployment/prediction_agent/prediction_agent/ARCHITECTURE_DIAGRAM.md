# 📐 Complete Modern Stack Architecture

## Full-Stack Technology Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          CLIENT LAYER                                       │
│                                                                              │
│  Browser (Chrome, Firefox, Safari, Edge)                                    │
│           ↓                                                                  │
│  ┌────────────────────────────────────────────────────────────────────┐    │
│  │                   FRONTEND (SvelteKit 5 + Vite)                    │    │
│  │                                                                    │    │
│  │  ┌──────────────────────────────────────────────────────────┐    │    │
│  │  │ Pages: Dashboard, Alerts, MLflow, Settings              │    │    │
│  │  │ Routes: /dashboard, /alerts, /mlflow, /settings         │    │    │
│  │  └──────────────────────────────────────────────────────────┘    │    │
│  │                                                                    │    │
│  │  ┌──────────────────────────────────────────────────────────┐    │    │
│  │  │ Components: RiskHeatmap, AlertPanel, MetricsCard       │    │    │
│  │  │ State: Svelte Stores (predictions, alerts, metrics)     │    │    │
│  │  └──────────────────────────────────────────────────────────┘    │    │
│  │                                                                    │    │
│  │  TypeScript + CSS → Compiled to Static HTML/JS (Vite)           │    │
│  │  HMR enabled in development, optimized build for production     │    │
│  │                                                                    │    │
│  │  Port: 5173 (dev) | Static files in production                  │    │
│  └────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
└───────────────────────────────┬──────────────────────────────────────────────┘
                                │ HTTP/REST + JSON
                                │ CORS enabled
                                ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│                       API GATEWAY LAYER                                      │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────┐    │
│  │                    FASTAPI Application                             │    │
│  │                   (backend/api_enhanced.py)                        │    │
│  │                                                                    │    │
│  │  ┌─────────────────────────────────────────────────────────┐     │    │
│  │  │  API Endpoints:                                         │     │    │
│  │  │  • POST /predict → Store in SQLite + Log to MLflow     │     │    │
│  │  │  • POST /batch-predict → Bulk predictions             │     │    │
│  │  │  • GET /health → System status + drift alerts          │     │    │
│  │  │  • GET /alerts → Active alerts + filtering             │     │    │
│  │  │  • GET /mlflow/runs → MLflow experiment runs          │     │    │
│  │  │  • POST /telemetry → KPI metric recording              │     │    │
│  │  │  • GET /kpi-summary → Telemetry aggregation            │     │    │
│  │  └─────────────────────────────────────────────────────────┘     │    │
│  │                                                                    │    │
│  │  Pydantic models for automatic validation & documentation        │    │
│  │  Async support (concurrent request handling)                     │    │
│  │  Auto-generated OpenAPI/Swagger docs at /docs                    │    │
│  │                                                                    │    │
│  │  Port: 8000                                                       │    │
│  │  Server: Uvicorn (ASGI)                                          │    │
│  └────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
└───────────────────────────────┬──────────────────────────────────────────────┘
                                │ Async requests
         ┌──────────────────────┼──────────────────────┐
         │                      │                      │
         ↓                      ↓                      ↓
┌─────────────────────┐ ┌──────────────────┐ ┌──────────────────┐
│  ML INFERENCE LAYER │ │  DATA LAYER      │ │  TRACKING LAYER  │
│                     │ │                  │ │                  │
│ PredictionAgent:    │ │ AppStore         │ │ MLflow           │
│ • Load models       │ │ (SQLite)         │ │ (MLflow)         │
│ • XGBoost ensemble  │ │                  │ │                  │
│ • LSTM temporal     │ │ Tables:          │ │ Experiment IDs:  │
│ • SHAP explain      │ │ • predictions    │ │ • qos_prediction │
│ • LLM alerts        │ │ • alerts         │ │                  │
│ • RAG context       │ │ • model_runs     │ │ Runs track:      │
│                     │ │ • nodes          │ │ • Params         │
│ File: agent/        │ │ • kpi_telemetry  │ │ • Metrics        │
│ prediction_agent.py │ │                  │ │ • Artifacts      │
│                     │ │ Indexed queries: │ │ • Tags           │
│                     │ │ • node_id        │ │                  │
│                     │ │ • timestamp      │ │ Storage:         │
│                     │ │ • severity       │ │ sqlite:///       │
│                     │ │                  │ │ mlflow.db        │
└─────────────────────┘ └──────────────────┘ └──────────────────┘
        ↑                      ↑
        │ (1) Load models      │ (2) Store results
        │                      │
        └──────────┬───────────┘
                   │
        ┌──────────┴──────────┐
        │                     │
        ↓                     ↓
┌─────────────────────┐ ┌─────────────────┐
│ ARTIFACT STORAGE    │ │ CONTEXT LAYER   │
│                     │ │                 │
│ models/saved/:      │ │ RAG:            │
│ • xgb_*.joblib      │ │ rag/chroma_db/  │
│ • lstm_qos.pt       │ │ ChromaDB        │
│ • preprocessor      │ │ (Incidents DB)  │
│ • prophet_*.joblib  │ │                 │
│ • eta_*.joblib      │ │ LLM:            │
│ • thresholds        │ │ Ollama          │
│                     │ │ localhost:11434 │
│ Versioned & timed   │ │                 │
│ for reproducibility │ │ Models:         │
│                     │ │ • gemma3:1b     │
│                     │ │ • llama3        │
│                     │ │ • qwen2         │
│                     │ │                 │
└─────────────────────┘ └─────────────────┘
        ↑
        │ (Load on inference)
        │
        └──────────────────────────┬──────────────────────────┐
                                   │                          │
                                   ↓                          ↓
                          ┌─────────────────┐        ┌─────────────────┐
                          │ DATA PIPELINE   │        │ MONITORING      │
                          │                 │        │                 │
                          │ data/raw/:      │        │ logging_config: │
                          │ • timeseries    │        │ • main.log      │
                          │ • incidents     │        │ • errors.log    │
                          │ • qos_*.csv     │        │ • inference.log │
                          │                 │        │ • training.log  │
                          │ Processing:     │        │                 │
                          │ • loader        │        │ monitoring.py:  │
                          │ • preprocessor  │        │ • drift detect  │
                          │ • features      │        │ • degradation   │
                          │ • labels        │        │ • health report │
                          │                 │        │                 │
                          └─────────────────┘        └─────────────────┘
```

## Containerization Layer

```
┌────────────────────────────────────────────────────────────────┐
│                    Docker Compose                              │
│                  (docker-compose.yml)                          │
│                                                                │
│  ┌─────────────────┐  ┌─────────────────┐  ┌──────────────┐  │
│  │  Backend        │  │  Frontend       │  │  Ollama      │  │
│  │  Container      │  │  Container      │  │  Container   │  │
│  │                 │  │                 │  │              │  │
│  │ • FastAPI       │  │ • Node 20       │  │ • LLM Models │  │
│  │ • Uvicorn       │  │ • SvelteKit     │  │ • Port 11434 │  │
│  │ • Port 8000     │  │ • Static files  │  │              │  │
│  │ • Python 3.11   │  │ • Port 5173     │  │ Volumes:     │  │
│  │                 │  │                 │  │ • ollama-data│  │
│  │ Volumes:        │  │ Volumes:        │  └──────────────┘  │
│  │ • logs/         │  │ • src/ (bind)   │                     │
│  │ • models/saved/ │  │ • build/        │  ┌──────────────┐  │
│  │ • rag/          │  │ • node_modules/ │  │  MLflow      │  │
│  │ • mlflow.db     │  │                 │  │  Container   │  │
│  │ • app_store.db  │  │                 │  │              │  │
│  │                 │  │                 │  │ • Web UI     │  │
│  │ Health checks:  │  │ Health checks:  │  │ • Port 5000  │  │
│  │ • /health       │  │ • wget localhost│  │ • MLflow UI  │  │
│  │ • 30s interval  │  │ • 30s interval  │  │              │  │
│  │ • 3 retries     │  │ • 3 retries     │  └──────────────┘  │
│  └─────────────────┘  └─────────────────┘                     │
│                                                                │
│  Network: qos-network (bridge)                                │
│  Service discovery via DNS                                    │
│  Environment injection from .env                              │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

## Data Flow Architecture

```
User Request
    │
    ↓
┌─────────────────────────────────┐
│ Browser (SvelteKit Frontend)     │
│ • Svelte components render       │
│ • Event handlers trigger         │
│ • Store updates propagate        │
│ • HTTP request via Fetch API     │
└──────────────┬──────────────────┘
               │ POST /predict
               │ (JSON payload)
               ↓
┌─────────────────────────────────┐
│ FastAPI Router                  │
│ • Pydantic model validation      │
│ • Request deserialization       │
│ • Dependency injection           │
└──────────────┬──────────────────┘
               │
               ↓
┌─────────────────────────────────┐
│ PredictionAgent.predict_single() │
│ • Load preprocessor             │
│ • Transform input features      │
│ • XGBoost prediction (6 targets)│
│ • LSTM prediction (6 targets)   │
│ • Ensemble fusion (0.55:0.45)   │
│ • Compute severity              │
│ • SHAP explanation              │
│ • RAG incident search           │
│ • LLM alert generation          │
└──────────────┬──────────────────┘
               │
               ↓ (async)
┌─────────────────────────────────┐
│ AppStore.insert_prediction()    │
│ • Store prediction in SQLite     │
│ • Index by node_id, timestamp   │
│ • Return record ID              │
└──────────────┬──────────────────┘
               │ (async)
               ↓
┌─────────────────────────────────┐
│ MLflow.log_metrics()            │
│ • Track inference metrics        │
│ • Store in MLflow backend       │
│ • Available in UI at :5000      │
└──────────────┬──────────────────┘
               │
               ↓
┌─────────────────────────────────┐
│ RiskPrediction Response         │
│ • Predictions dict              │
│ • Primary risk + probability    │
│ • SHAP drivers (top 5)          │
│ • Similar incidents             │
│ • Natural language alert        │
│ • Stored record ID              │
│ (JSON serialization)            │
└──────────────┬──────────────────┘
               │
               ↓
┌─────────────────────────────────┐
│ HTTP Response                   │
│ • Status 200                    │
│ • Content-Type: application/json│
│ • Body: RiskPrediction model    │
└──────────────┬──────────────────┘
               │
               ↓
┌─────────────────────────────────┐
│ Browser (SvelteKit Frontend)    │
│ • Response interceptor          │
│ • Parse JSON response           │
│ • Update component state        │
│ • Svelte reactivity triggers    │
│ • DOM re-renders with new data  │
│ • User sees updated dashboard   │
└─────────────────────────────────┘
```

## Technology Stack Summary

| Layer | Technology | Purpose | Port |
|-------|-----------|---------|------|
| **Frontend** | SvelteKit 5 | Interactive dashboard UI | 5173 |
| **Frontend** | Vite | Build tool (dev: HMR, prod: optimization) | - |
| **Frontend** | TypeScript | Type-safe JavaScript | - |
| **Frontend** | Chart.js | Data visualization | - |
| **API** | FastAPI | REST API framework (async) | 8000 |
| **API** | Uvicorn | ASGI web server | - |
| **API** | Pydantic | Request/response validation | - |
| **ML** | XGBoost | 6 per-target classifiers | - |
| **ML** | LSTM | Temporal multi-label model | - |
| **ML** | SHAP | Feature importance | - |
| **Data** | SQLite | Application database | - |
| **Tracking** | MLflow | Experiment tracking & registry | 5000 |
| **Context** | ChromaDB | Vector store for incidents | - |
| **LLM** | Ollama | Local LLM service | 11434 |
| **Container** | Docker | Containerization | - |
| **Orchestration** | Docker Compose | Multi-container orchestration | - |
| **Config** | .env | Environment variables | - |
| **Logging** | Python logging | Structured logging | - |

## Deployment Topology

```
Development:
┌─────────────────────────────────────┐
│ Local Machine                       │
│ ┌─────────────────────────────────┐ │
│ │ Terminal 1: python -m uvicorn   │ │ Backend (8000)
│ │ Terminal 2: npm run dev         │ │ Frontend (5173)
│ │ Terminal 3: mlflow ui           │ │ MLflow (5000)
│ │ Terminal 4: python main.py      │ │ Training
│ └─────────────────────────────────┘ │
└─────────────────────────────────────┘

Production (Docker Compose):
┌──────────────────────────────────────────────────┐
│ Docker Host                                      │
│ ┌────────────────────────────────────────────┐   │
│ │ qos-network (bridge)                       │   │
│ │ ┌──────────────┐  ┌──────────────┐        │   │
│ │ │ backend:8000 │  │ frontend:5173│        │   │
│ │ │              │  │              │        │   │
│ │ │ FastAPI +    │  │ SvelteKit +  │        │   │
│ │ │ MLflow +     │  │ Static build │        │   │
│ │ │ SQLite       │  │              │        │   │
│ │ └──────────────┘  └──────────────┘        │   │
│ │                                            │   │
│ │ ┌──────────────┐  ┌──────────────┐        │   │
│ │ │ ollama:11434 │  │ mlflow:5000  │        │   │
│ │ │              │  │              │        │   │
│ │ │ LLM service  │  │ Tracking UI  │        │   │
│ │ └──────────────┘  └──────────────┘        │   │
│ └────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────┘

Cloud (Kubernetes):
┌──────────────────────────────────────────────────┐
│ Kubernetes Cluster                               │
│ ┌────────────────────────────────────────────┐   │
│ │ Ingress (Load Balancer)                    │   │
│ │ ↓↓↓                                         │   │
│ │ ┌─────────────────────────────────────┐    │   │
│ │ │ Pod Replicas (3x)                   │    │   │
│ │ │ • FastAPI service                   │    │   │
│ │ │ • Horizontal Pod Autoscaler         │    │   │
│ │ │ • StatefulSet for data persistence  │    │   │
│ │ └─────────────────────────────────────┘    │   │
│ │                                             │   │
│ │ ┌─────────────────────────────────────┐    │   │
│ │ │ StatefulSet: PostgreSQL (replaces   │    │   │
│ │ │ SQLite)                             │    │   │
│ │ │ • PersistentVolume claims           │    │   │
│ │ │ • Backup sidecar                    │    │   │
│ │ └─────────────────────────────────────┘    │   │
│ │                                             │   │
│ │ ┌─────────────────────────────────────┐    │   │
│ │ │ ConfigMap & Secrets                 │    │   │
│ │ │ • .env variables                    │    │   │
│ │ │ • API keys, credentials             │    │   │
│ │ └─────────────────────────────────────┘    │   │
│ └────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────┘
```

---

**Version**: 2.0.0  
**Status**: ✅ Production Ready  
**Last Updated**: 2026-04-26
