# QoS Buddy Portable Demo Package

QoS Buddy is a live AI network assurance platform for monitoring, predicting, diagnosing, optimizing, and reporting on network quality of service. This SSD package is designed to run locally on a Windows laptop with Docker Desktop and a local Ollama model, then be moved to another compatible machine when needed.

The dashboard is available at:

```text
http://localhost:3000
```

## What Is Included

- Live network monitoring from the host collector every 10 seconds.
- Detection, prediction, diagnostic, optimization, and reporting services in Docker Compose.
- Keycloak login with role-based access.
- Local Ollama integration with `qwen2.5:latest`.
- ChromaDB incident and RAG memory.
- Floating network assistant chatbot.
- Executive PDF reporting with explanations, recommendations, MTTD, MTTR, business impact, KPI trends, audit trail, and post-mortem content.
- Optional Jira ticket creation when local credentials are configured.

## Requirements

- Windows 10/11.
- Docker Desktop running in Linux container mode.
- PowerShell.
- Python 3.10 or newer on PATH.
- 16 GB RAM recommended.
- Ollama installed and running on the host machine.
- Local model available:

```powershell
ollama pull qwen2.5
```

Internet access is required for the first Docker image build and model downloads.

## Start The Demo

From the SSD project root:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\START-HERE.ps1
```

The launcher starts the host-side monitoring producer from `monitoring\qos_buddy_collector.py`, then starts the Docker Compose stack under `qos-buddy`.

Open:

```text
http://localhost:3000
```

## Login

QoS Buddy uses Keycloak. The default demo users are imported into the local Keycloak realm on first start:

| User | Password | Role | Typical Use |
| --- | --- | --- | --- |
| `noc-exec` | `demo` | NOC Executive | Business dashboard, reports, incident overview |
| `noc-engineer` | `demo` | NOC Executive | NOC operations, What-If, diagnostics, optimization |
| `engineer` | `demo` | AI Engineer | Model, MLflow, and technical views |
| `admin-noc` | `demo` | Site Admin | Full platform administration |

## Main Demo Flow

1. Open the dashboard and show live network KPIs changing every 10 seconds.
2. Show detection and prediction to explain how QoS Buddy identifies degradation before it becomes a user-facing problem.
3. Open diagnostics to show likely root causes, RAG context, and the AI lesson/post-mortem flow.
4. Open optimization to show recommendations, pending approvals, blocked policy actions, and optional Jira escalation.
5. Open reporting to export an executive network report with impact, recommendations, MTTD, MTTR, audit log, post-mortem, and KPI trends.
6. Open the floating chatbot and ask simple operational questions such as:
   - What is happening on the live network?
   - What incidents happened recently?
   - What actions were proposed recently?
   - What does delay variation mean?

## RAG And AI Memory

QoS Buddy uses ChromaDB for prediction incident memory and RAG context. The main incident collection is `qos_incidents`. The stack also ingests live operational information so the chatbot and reports can answer questions about recent incidents, diagnostics, actions, and network status.

Qdrant is not required by the current SSD Compose stack. It was previously evaluated, but the active platform uses ChromaDB.

## Local LLM

All LLM-assisted features are configured to use local Ollama through:

```text
http://host.docker.internal:11434
```

The expected model is:

```text
qwen2.5:latest
```

No external LLM API is required for the current local demo.

## Health Check

From the SSD project root:

```powershell
.\CHECK-SSD-HEALTH.ps1
```

This checks the Docker Compose stack, prediction health, ChromaDB incident memory, MLflow status, optimization traces/artifacts, and recent bridge logs.

## Stop The Demo

From the SSD project root:

```powershell
.\qos-buddy\stop.ps1
```

To stop and remove Docker runtime volumes intentionally:

```powershell
.\qos-buddy\stop.ps1 -RemoveVolumes
```

Only use `-RemoveVolumes` when you want to wipe local runtime state.

## Jira

Jira is optional. Credentials must stay local and must not be committed to Git.

To enable Jira on a local machine:

1. Copy `qos-buddy\.env.example` to `qos-buddy\.env`.
2. Set `QOS_JIRA_ENABLED=true`.
3. Fill `JIRA_URL`, `JIRA_EMAIL`, `JIRA_TOKEN`, `JIRA_PROJECT_KEY`, and `JIRA_ISSUE_TYPE`.
4. Restart only the affected services:

```powershell
cd .\qos-buddy
docker compose up -d --build gateway synthesis optimization shell
```

## Troubleshooting

- If the dashboard is empty, confirm the collector is running and check `qos-buddy\logs\producer.log`.
- If login fails, open Keycloak at `http://localhost:8081` and confirm the `qos-buddy` realm imported.
- If AI answers are slow, confirm Ollama is running and `qwen2.5:latest` is available.
- If ports are busy, check ports `3000`, `5432`, `6379`, `8080`, `8081`, `8088`, `8089`, `16686`, and `11434`.
- If Docker feels slow, check free space on the system drive and the SSD. Runtime QoS Buddy data should remain under `qos-buddy\docker-data` on the SSD.
