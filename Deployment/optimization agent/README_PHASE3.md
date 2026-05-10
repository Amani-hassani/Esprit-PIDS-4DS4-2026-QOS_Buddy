# QoS Buddy Phase 3 Deployment

QoS Buddy is a local-first NOC surface for:

- QoS snapshot inspection and topology views
- root-cause driven action selection
- policy-gated execution and approvals
- local LLM reasoning through an Ollama-compatible endpoint
- audit, ticketing, and MLflow traceability

## Backend Setup

Install the backend in a Python 3.11+ environment from the repository root:

```powershell
python -m pip install -e .[dev]
```

Copy `.env.example` to `.env` if you need to override defaults.

Set the runtime mode with `QOS_APP_MODE`:

- `demo`: local-first demo behavior
- `dev`: local development behavior
- `prod`: hardened defaults with no built-in bearer tokens or default browser origins

Run the API:

```powershell
python -m uvicorn deployment.main:app --host 127.0.0.1 --port 8001
```

Key API routes:

- `GET /api/ping`
- `GET /api/snapshot`
- `POST /api/agent/decide`
- `GET /api/decisions`
- `GET /api/ops/health`

## Frontend

Run the Svelte frontend from `frontend/`:

```powershell
npm install
npm run dev
```

The frontend dev server runs on `http://localhost:5173` and proxies `/api` to `http://localhost:8001`.
If you open the built static bundle from a separate local server on port `8000`, the frontend now falls back to `http://127.0.0.1:8001` automatically for API and SSE traffic.

Build the static frontend bundle with:

```powershell
npm run build
```

The build output is written to `deployment/static/app` and is mounted automatically by the FastAPI app when present.
The backend only mounts that bundle when `deployment/static/app/build-meta.json` matches the current `frontend/` source tree.

Browser access is controlled by `QOS_CORS_ALLOW_ORIGINS`, which defaults to the local frontend dev origins:

- `http://localhost:5173`
- `http://127.0.0.1:5173`

Streaming routes also support an HTTP-only session cookie for same-origin browser use:

- `QOS_SESSION_COOKIE_NAME`
- `QOS_SESSION_COOKIE_SECURE`
- `QOS_SESSION_TTL_S`

The frontend now establishes that cookie through `POST /api/session` after token validation, so SSE traffic does not need bearer tokens in the URL during normal use. Browser cookies carry revocable opaque session IDs instead of raw bearer tokens.

Mode-sensitive defaults:

- `demo` / `dev`: built-in local bearer tokens enabled unless overridden
- `demo` / `dev`: local frontend dev origins enabled by default
- `demo` / `dev`: bundled sample telemetry may be used when live monitoring data is absent
- `prod`: no default bearer tokens
- `prod`: no default CORS origins
- `prod`: secure session cookie enabled by default
- `prod`: bundled sample telemetry fallback is disabled; live monitoring snapshots are required for runtime views

## Local LLM

- Provider: Ollama-compatible local HTTP endpoint
- Default model: `qwen2.5:3b`
- No hosted API keys are required
- Main settings: `QOS_OLLAMA_URL`, `QOS_OLLAMA_TAGS_URL`, `QOS_LLM_MODEL`, `QOS_LLM_TIMEOUT_S`

If the model is unavailable, the app falls back to deterministic reasoning text and still records the decision path.

## Runtime State

Mutable local state is kept outside the repository under `~/.codex/memories/pi-v1/`:

- SQLite audit store: `store/qos_buddy.db`
- MLflow backend DB: `mlflow.db`
- MLflow artifacts: `mlartifacts/`

This keeps the working tree clean while preserving local history.

## Agent Runtime

Autonomous decisioning is disabled by default.

Enable it explicitly with:

- `QOS_AGENT_AUTOSTART=true`
- `QOS_AGENT_STARTUP_RUN=true`
- optional `QOS_AGENT_INTERVAL_S`
- optional `QOS_AGENT_STARTUP_CELL_ID`

Without those flags, the server starts in passive mode and only makes decisions when an operator or test calls `POST /api/agent/decide`.

## Preflight

Run a readiness check before release or deployment:

```powershell
python -m deployment.preflight
```

The API also exposes `GET /api/ops/preflight`.
Preflight reports:

- app mode
- frontend bundle freshness
- store and MLflow path writability
- authentication bootstrap status
- live telemetry availability
- Jira provider status
- MLflow backend readiness

## MLOps

Every `POST /api/agent/decide` decision attempts to log to MLflow under the `qos_phase3_deployment` experiment.

MLflow initialization is lazy. The API no longer initializes MLflow during process startup; it is configured on first use by decision logging, tracing, or the ops endpoints.

Stored decision context includes:

- root cause
- selected action
- gate decision
- validator outcomes
- model availability
- hybrid score and confidence
- execution health deltas when available

## Policy Gate

The deterministic validators are:

- `risk_threshold`
- `impact_radius`
- `rollback_available`
- `change_window`
- `not_repeat_action`
- `resource_limits`

`resource_limits` is still a Phase 3 stub until live network capacity state is wired in. AI reasoning does not bypass the deterministic gate.

## Release Checklist

- Set `QOS_APP_MODE` explicitly for the target environment.
- Run `python -m deployment.preflight` and resolve every `error` check.
- Run `npm run validate` from `frontend/` so the static bundle is rebuilt and verified.
- Confirm the frontend bundle is fresh before serving `deployment/static/app`.
- Confirm the intended telemetry source is present for the target mode.
- Confirm Jira settings if external ticketing is required.
- Verify passive vs autonomous agent runtime flags before startup.
