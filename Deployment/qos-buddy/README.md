# QoS Buddy - Qosmic NOC Command Center

QoS Buddy is an AI-assisted network assurance platform that connects live monitoring, anomaly detection, prediction, root-cause diagnosis, RAG memory, optimization recommendations, auditability, and executive reporting into one local Docker Compose stack.

The platform is built for NOC teams, AI/network engineers, and executives who need a clear answer to three questions:

- What is happening on the network right now?
- What is likely to happen next?
- What should we do, and what business impact does it avoid?

## Current Capabilities

- Branded Keycloak login with role-based access control.
- Live host network monitoring through `monitoring\qos_buddy_collector.py`.
- Dashboard updates on a 10 second live cadence.
- Detection and prediction agents with MLflow-backed operational tracking.
- Diagnostic agent with plain-language root-cause summaries.
- ChromaDB RAG memory for incidents, live network context, reports, diagnostics, and operator lessons.
- Floating chatbot powered by local Ollama `qwen2.5:latest`.
- Optimization agent with policy gates, pending approvals, blocked actions, accepted actions, MLflow traces, and optional Jira ticketing.
- Reporting service for business-oriented PDF reports, post-mortems, KPI trends, MTTD, MTTR, service impact, and recommendations.
- Audit log for operational accountability.
- What-If simulation view for NOC and engineering workflows.

## Repository Layout

```text
qos-buddy/
  agents-bridge/      Docker adapters for existing AI agents
  bus/                Redis stream bridges and event pipeline workers
  contracts/          Shared schemas and event contracts
  gateway/            FastAPI backend, RBAC, APIs, live ingest, chatbot routing
  infra/              Keycloak realm, Postgres init, validation helpers
  rag-service/        ChromaDB-backed RAG service
  reporting-service/  Executive reporting and post-mortem service
  shell/              Next.js dashboard UI
  synthesis/          Incident synthesis, recommendations, Jira/audit integration
  docker-compose.yml  Local SSD deployment stack
```

Adjacent project folders provide the actual agent implementations and data sources:

```text
monitoring/
detection agent/
Diagnostic agent/
optimization agent/
prediction_agent/
```

## Architecture

The host-side monitoring collector writes live network samples to JSONL. The Docker `monitoring` bridge tails that file and publishes normalized events to Redis Streams. Detection, prediction, diagnostic, optimization, synthesis, reporting, RAG, gateway, and dashboard services consume and enrich those events.

Key runtime services:

- `qos-shell`: dashboard at `http://localhost:3000`
- `qos-gateway`: API and websocket gateway at `http://localhost:8080`
- `qos-keycloak`: authentication at `http://localhost:8081`
- `qos-rag`: Chroma-backed RAG API at `http://localhost:8088`
- `qos-reporting`: reporting API at `http://localhost:8089`
- `qos-jaeger`: traces at `http://localhost:16686`

Ollama runs on the host and is reached by containers through:

```text
http://host.docker.internal:11434
```

## Quick Start

From the SSD project root:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\START-HERE.ps1
```

Or from this folder:

```powershell
Copy-Item .env.example .env
.\start.ps1
```

Open:

```text
http://localhost:3000
```

## Login Users

The Keycloak realm imports these demo users on a fresh Keycloak data volume:

| User | Password | Role |
| --- | --- | --- |
| `noc-exec` | `demo` | NOC Executive |
| `noc-engineer` | `demo` | NOC Executive |
| `engineer` | `demo` | AI Engineer |
| `admin-noc` | `demo` | Site Admin |

## Configuration

Copy `.env.example` to `.env` and keep `.env` local. Do not commit real credentials.

Important variables:

```text
KEYCLOAK_ADMIN
KEYCLOAK_ADMIN_PASSWORD
POSTGRES_PASSWORD
QOS_MONITORING_MODE
QOS_JIRA_ENABLED
JIRA_URL
JIRA_EMAIL
JIRA_TOKEN
JIRA_PROJECT_KEY
JIRA_ISSUE_TYPE
```

For normal live operation, keep:

```text
QOS_MONITORING_MODE=tail
```

Use replay mode only for intentional offline backfill or demo playback.

## RAG And Vector Memory

The active stack uses ChromaDB:

- Prediction incident memory: `prediction_agent\prediction_agent\rag\chroma_db`
- Runtime RAG memory: `qos-buddy\docker-data\rag-data`
- Default incident collection: `qos_incidents`
- Live operational memory collection: `qos_live_memory`

Qdrant is not configured in the current SSD Compose stack and is not required for the active application.

## Local AI Model

Install Ollama on the host and pull the expected model:

```powershell
ollama pull qwen2.5
```

The stack expects:

```text
qwen2.5:latest
```

LLM-assisted diagnostics, chatbot answers, optimization wording, and report narratives use this local model.

## Health Check

From the SSD project root:

```powershell
.\CHECK-SSD-HEALTH.ps1
```

From this folder, useful checks are:

```powershell
docker compose ps
docker compose logs --tail 50 gateway shell rag reporting
docker compose logs --tail 50 monitoring detection-bridge diagnostic-bridge prediction-bridge optimization-bridge
```

## Rebuild Affected Services

After code changes, rebuild only the services that changed. Examples:

```powershell
docker compose up -d --build shell
docker compose up -d --build gateway
docker compose up -d --build reporting
docker compose up -d --build rag gateway shell
```

## Stop

```powershell
.\stop.ps1
```

To intentionally wipe runtime volumes:

```powershell
.\stop.ps1 -RemoveVolumes
```

## Security Notes

- Real `.env` files and Jira tokens must remain local.
- Docker runtime state lives under `qos-buddy\docker-data` and should not be pushed to Git.
- The GitHub deployment export intentionally excludes runtime databases, Chroma/MLflow state generated by containers, logs, caches, and telemetry streams.
