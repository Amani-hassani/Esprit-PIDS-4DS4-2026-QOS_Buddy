# 🎨 Complete Modern Stack Deployment Guide

## Modern Technology Stack

### Frontend: SvelteKit 5 + Vite + TypeScript

**Why SvelteKit 5?**
- Svelte 5: Latest reactive compiler (true fine-grained reactivity)
- Vite: Lightning-fast build tool (<100ms refresh)
- TypeScript: Full type safety for component development
- Static Adapter: Generate optimized static HTML for Netlify/Vercel
- ESM-first: Modern JavaScript module system

**Features**:
- Server-side rendering (SSR) capability
- Static pre-rendering for performance
- Built-in routing and layouts
- TypeScript support throughout
- HMR (Hot Module Replacement) for instant feedback

### Backend: Python FastAPI + Uvicorn + Pydantic

**Why FastAPI?**
- Auto-generated OpenAPI/Swagger documentation
- Async support with Python async/await
- Pydantic validation (automatic input validation)
- Dependency injection system
- 3x faster than Flask for async workloads

### Data & Experimentation

**MLflow**: Model experiment tracking
- Track parameters, metrics, artifacts
- Model registry for versioning
- REST API for runs/experiments
- Web UI for visualization

**SQLite**: Application data store
- Zero dependencies, embedded database
- Perfect for small/medium-scale apps
- ACID compliance, reliable
- File-based: easy backup/deployment

**Pandas**: Data manipulation
- KPI/telemetry shaping
- Aggregation and filtering
- Time-series operations

---

## 📦 Project Structure

```
prediction_agent/
├── frontend/                          # SvelteKit 5 app
│   ├── src/
│   │   ├── routes/                   # Page routes (auto-routed)
│   │   │   ├── +page.svelte          # Home page
│   │   │   ├── dashboard/
│   │   │   │   ├── +page.svelte      # Dashboard page
│   │   │   │   └── +server.ts        # Load data server-side
│   │   │   ├── alerts/+page.svelte   # Alerts page
│   │   │   ├── mlflow/+page.svelte   # MLflow experiments page
│   │   │   └── api/[route]/+server.ts # API proxy endpoints
│   │   ├── components/               # Reusable components
│   │   │   ├── RiskHeatmap.svelte    # Risk visualization
│   │   │   ├── AlertPanel.svelte     # Alerts display
│   │   │   ├── MetricsCard.svelte    # KPI cards
│   │   │   └── Chart.svelte          # Chart wrapper
│   │   ├── stores/                   # Svelte stores (state)
│   │   │   ├── predictions.ts        # Prediction store
│   │   │   ├── alerts.ts             # Alert store
│   │   │   └── metrics.ts            # Metrics store
│   │   ├── lib/                      # Utilities
│   │   │   ├── api.ts                # API client
│   │   │   └── utils.ts              # Helper functions
│   │   ├── app.html                  # HTML shell
│   │   └── app.css                   # Global styles
│   ├── package.json                  # Dependencies
│   ├── svelte.config.js              # SvelteKit config
│   ├── vite.config.ts                # Vite config
│   ├── tsconfig.json                 # TypeScript config
│   ├── dockerfile                    # Container config
│   └── .env.example                  # Environment template
│
├── backend/                           # Enhanced FastAPI
│   ├── api_enhanced.py               # Main FastAPI app
│   ├── mlflow_integration/
│   │   ├── __init__.py
│   │   └── tracker.py                # MLflow tracker class
│   ├── database/
│   │   ├── __init__.py
│   │   └── app_store.py              # SQLite app store
│   └── __init__.py
│
├── docker-compose.yml                # Full stack orchestration
├── backend.dockerfile                # Backend container
│
├── config.py                         # Production config
├── main.py                           # Training pipeline
├── requirements.txt                  # Python dependencies
│
├── models/
│   └── saved/                        # Trained model artifacts
├── rag/
│   └── chroma_db/                    # Vector store
├── logs/                             # Application logs
├── mlflow-data/                      # MLflow experiments
├── mlflow.db                         # MLflow SQLite backend
└── app_store.db                      # Application database
```

---

## 🚀 Quick Start

### Option 1: Docker Compose (Recommended)

```bash
# Clone/prepare the project
cd prediction_agent

# Build all services
docker-compose build

# Start all services
docker-compose up -d

# Check status
docker-compose ps

# View logs
docker-compose logs -f backend
docker-compose logs -f frontend

# Access services:
# Frontend: http://localhost:5173
# Backend API: http://localhost:8000
# Swagger Docs: http://localhost:8000/docs
# MLflow UI: http://localhost:5000
# Ollama: http://localhost:11434
```

### Option 2: Local Development

#### Backend Setup
```bash
# Install Python dependencies
pip install -r requirements.txt

# Initialize database and MLflow
python -c "from backend.database.app_store import initialize_store; from backend.mlflow_integration.tracker import initialize_tracker; initialize_store(); initialize_tracker()"

# Start FastAPI backend
python -m uvicorn backend.api_enhanced:app --reload --host 0.0.0.0 --port 8000

# In another terminal, start MLflow
mlflow ui --backend-store-uri sqlite:///mlflow.db
```

#### Frontend Setup
```bash
# Install Node dependencies
cd frontend
npm install

# Start dev server (with hot reload)
npm run dev

# Access at http://localhost:5173
```

---

## 📊 Frontend Pages & Components

### Pages

1. **Dashboard** (`/dashboard`)
   - Real-time risk heatmap (6 targets × nodes)
   - KPI metrics cards (ROC-AUC, AP, latency)
   - Alert summary (active, acknowledged, resolved)
   - Latest predictions table

2. **Alerts** (`/alerts`)
   - Unacknowledged alerts list
   - Severity filtering (CRITICAL, HIGH, MEDIUM, LOW)
   - One-click acknowledge
   - Alert timeline chart

3. **MLflow Experiments** (`/mlflow`)
   - Recent runs table
   - Best run highlight
   - Metrics comparison
   - Parameter analysis

4. **API Proxy** (`/api/*`)
   - Server-side API calls (CORS-free)
   - Data pre-processing
   - Caching layer

### Components

- **RiskHeatmap**: Colored grid showing risk levels per node/target
- **AlertPanel**: Scrollable alerts with action buttons
- **MetricsCard**: Individual KPI display with trend indicators
- **Chart**: Wrapper for Chart.js with Svelte reactivity
- **Navigation**: Header with theme toggle, user menu

---

## 🔌 Backend API Endpoints

### Predictions
- `POST /predict` - Single prediction with storage
- `POST /batch-predict` - Multiple predictions
- `GET /predictions` - Historical predictions (paginated)

### Monitoring
- `GET /health` - System health check
- `GET /alerts` - Active alerts (with filters)
- `POST /alerts/{id}/acknowledge` - Mark alert as seen
- `GET /kpi-summary` - KPI telemetry summary (24h, 7d, 30d)

### MLflow Integration
- `GET /mlflow/runs` - Recent training runs
- `GET /mlflow/best-run` - Best model by metric
- `GET /mlflow/compare-runs` - Compare multiple runs

### Telemetry
- `POST /telemetry` - Record KPI metric
- `GET /telemetry-history` - Historical telemetry

---

## 🔐 Security & Performance

### Security
- CORS headers configured
- Rate limiting on API endpoints
- Input validation via Pydantic
- SQLite with parameterized queries (SQL injection prevention)
- Environment variable secrets (.env.local not in git)

### Performance
- Frontend: Static pre-rendering with Vite
- Backend: Async/await for concurrent requests
- Caching: HTTP caching headers on static assets
- Database: Indexed queries (node_id, timestamp, severity)
- API: Response pagination and filtering

---

## 📈 Monitoring & Debugging

### MLflow Dashboard
```
http://localhost:5000
```
- View all experiment runs
- Compare metrics/parameters
- Download artifacts
- Register models

### FastAPI Swagger Docs
```
http://localhost:8000/docs
```
- Interactive API testing
- Request/response examples
- Try it out directly

### Logs
```bash
# Backend logs
tail -f logs/qos_prediction_agent.log
tail -f logs/errors.log

# Docker logs
docker-compose logs -f backend
docker-compose logs -f frontend
```

### Database Query
```bash
# Access SQLite directly
sqlite3 app_store.db
sqlite> SELECT * FROM predictions LIMIT 10;
sqlite> SELECT severity, COUNT(*) FROM alerts GROUP BY severity;
```

---

## 🛠️ Development Workflow

### Adding a New Page
1. Create `frontend/src/routes/mypage/+page.svelte`
2. Import API client: `import { api } from '$api'`
3. Load data in `+page.server.ts`:
```typescript
export async function load() {
  const data = await api.get('/predictions');
  return { predictions: data };
}
```
4. Use in component:
```svelte
<script>
  export let data;
</script>

<h1>My Page</h1>
{#each data.predictions as pred}
  <p>{pred.node_id}: {pred.severity}</p>
{/each}
```

### Adding a New Backend Endpoint
1. Add to `backend/api_enhanced.py`:
```python
@app.get("/my-endpoint")
async def my_endpoint(param: str = Query(...)) -> Dict[str, any]:
    """Endpoint description."""
    store = get_store()
    data = store.query_something(param)
    return {"result": data}
```
2. Call from frontend:
```typescript
const response = await fetch('/api/my-endpoint?param=value');
const data = await response.json();
```

---

## 📦 Environment Variables

### Backend (.env)
```
OLLAMA_URL=http://ollama:11434
OLLAMA_MODEL=gemma3:1b
LOG_LEVEL=INFO
MLFLOW_TRACKING_URI=sqlite:///mlflow.db
DATABASE_PATH=app_store.db
```

### Frontend (.env.local)
```
VITE_API_URL=http://localhost:8000
VITE_APP_NAME=QoS Prediction Agent
VITE_API_TIMEOUT=30000
```

---

## 🚢 Deployment

### Docker Registry Push
```bash
# Build with registry prefix
docker-compose build --push

# Or manually
docker build -t myregistry.azurecr.io/qos-backend backend.dockerfile
docker push myregistry.azurecr.io/qos-backend
```

### Kubernetes Deployment
```bash
# Create namespace
kubectl create namespace qos-prediction

# Apply configmap
kubectl create configmap api-config \
  --from-literal=OLLAMA_URL=http://ollama:11434 \
  -n qos-prediction

# Deploy via helm/kubectl
kubectl apply -f kubernetes/deployment.yaml -n qos-prediction
```

### Cloud Deployment
- **Frontend**: Deploy to Netlify/Vercel (static hosting)
- **Backend**: Deploy to Cloud Run/AppEngine (FastAPI)
- **Database**: SQLite → PostgreSQL (for multi-instance)
- **MLflow**: Managed MLflow (Databricks)

---

## 📊 Performance Benchmarks

| Component | Metric | Target |
|-----------|--------|--------|
| **Frontend Build** | Build time | < 5s |
| **Frontend Load** | Page load | < 1s (gzipped) |
| **API Prediction** | Latency | < 100ms |
| **API Batch** | Throughput | > 100 req/s |
| **Database Query** | Latency | < 10ms |
| **Dashboard Refresh** | Interval | 5-30s |

---

## 🎯 Next Steps

1. **Customize Frontend**:
   - Add your company logo
   - Customize colors (CSS variables)
   - Add custom KPI cards
   - Integrate with existing dashboards

2. **Extend Backend**:
   - Add more API endpoints
   - Integrate with external systems
   - Add authentication (JWT, OAuth)
   - Implement caching (Redis)

3. **Scale**:
   - Replace SQLite with PostgreSQL
   - Add Kafka for event streaming
   - Implement microservices
   - Add horizontal scaling

4. **Monitor**:
   - Set up Prometheus metrics
   - Add Grafana dashboards
   - Configure alerting
   - Track SLOs

---

## 📞 Support

- **API Docs**: http://localhost:8000/docs
- **MLflow UI**: http://localhost:5000
- **Frontend Dev Server**: http://localhost:5173
- **Logs**: Check `logs/` directory

---

**Status**: ✅ **Ready for Deployment**  
**Version**: 2.0.0 (Modern Stack)  
**Last Updated**: 2026-04-26

🎉 **Modern full-stack deployment ready!**
