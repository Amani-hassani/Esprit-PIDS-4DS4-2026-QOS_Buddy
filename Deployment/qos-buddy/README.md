# QoS Buddy Integrated Stack

This folder contains the Docker Compose application that connects the QoS Buddy agents into one local network operations platform.

The stack is designed for a local demo environment. It runs the dashboard, gateway, authentication, event bus, RAG memory, reporting service, and bridges to the monitoring, detection, prediction, diagnostic, and optimization agents.

## Capabilities

- Role-based dashboard for NOC, engineering, executive, and admin views.
- Live monitoring from the host collector.
- Anomaly detection and QoS risk prediction.
- Root-cause diagnostics with model evidence.
- Policy-aware optimization recommendations and approvals.
- ChromaDB-backed incident and operational memory.
- Local Ollama integration for assistant, explanation, and reporting features.
- Executive and operational reporting.
- Audit, tracing, and troubleshooting surfaces.

## Layout

```text
qos-buddy/
|-- agents-bridge/       Docker adapters for the individual AI agents
|-- bus/                 Redis stream bridges and event pipeline workers
|-- contracts/           Shared event contracts and schemas
|-- gateway/             FastAPI gateway, RBAC, APIs, chatbot routing
|-- infra/               Keycloak realm, Postgres init, validation helpers
|-- rag-service/         ChromaDB-backed RAG service
|-- reporting-service/   Report and post-mortem service
|-- shell/               Next.js dashboard
|-- synthesis/           Incident synthesis and recommendation narratives
|-- docker-compose.yml   Local deployment stack
|-- start.ps1            Windows launcher for this folder
`-- stop.ps1             Windows shutdown helper
```

Adjacent folders under `Deployment/` contain the individual agent implementations and packaged artifacts.

## Requirements

- Windows 10 or 11.
- Docker Desktop running in Linux container mode.
- PowerShell.
- Python 3.10 or newer.
- Ollama running on the host.
- Local model:

```powershell
ollama pull qwen2.5
```

## Start

Recommended path from `Deployment/`:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\START-HERE.ps1
```

Alternative path from this folder:

```powershell
Copy-Item .env.example .env
.\start.ps1
```

Open:

```text
http://localhost:3000
```

## Local Services

| Service | URL |
| --- | --- |
| Dashboard | `http://localhost:3000` |
| Gateway API | `http://localhost:8080` |
| Keycloak | `http://localhost:8081` |
| RAG Service | `http://localhost:8088` |
| Reporting Service | `http://localhost:8089` |
| Jaeger | `http://localhost:16686` |

## Demo Users

| User | Password | Role |
| --- | --- | --- |
| `noc-exec` | `demo` | NOC Executive |
| `noc-engineer` | `demo` | NOC Engineer |
| `engineer` | `demo` | AI Engineer |
| `admin-noc` | `demo` | Site Admin |

These users are for local demo review only.

## Configuration

Copy `.env.example` to `.env` for local overrides. Keep real values local.

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

## Health Checks

From `Deployment/`:

```powershell
.\CHECK-SSD-HEALTH.ps1
```

From this folder:

```powershell
docker compose ps
docker compose logs --tail 50 gateway shell rag reporting
docker compose logs --tail 50 monitoring detection-bridge diagnostic-bridge prediction-bridge optimization-bridge
```

## Stop

```powershell
.\stop.ps1
```

To intentionally wipe runtime state:

```powershell
.\stop.ps1 -RemoveVolumes
```

## Security Notes

- Do not commit real `.env` files.
- Do not commit Jira tokens or other private credentials.
- Docker runtime data under `docker-data/` should stay local.
- Demo users and placeholder credentials exist only for the local evaluation environment.
