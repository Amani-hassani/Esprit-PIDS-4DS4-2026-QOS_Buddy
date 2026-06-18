# QoS Buddy Local Demo Guide

QoS Buddy is a local AI network assurance platform for monitoring, predicting, diagnosing, optimizing, and reporting on network quality of service. This guide describes the recommended demo flow for reviewers.

The dashboard is available at:

```text
http://localhost:3000
```

## What Is Included

- Live network monitoring from the host collector.
- Detection, prediction, diagnostic, optimization, and reporting services in Docker Compose.
- Keycloak login with role-based access.
- Local Ollama integration with `qwen2.5:latest`.
- ChromaDB incident and RAG memory.
- Floating network assistant chatbot.
- Executive PDF reporting with impact, recommendations, MTTD, MTTR, audit trail, and post-mortem content.
- Optional Jira ticket creation when local credentials are configured.

## Requirements

- Windows 10 or 11.
- Docker Desktop running in Linux container mode.
- PowerShell.
- Python 3.10 or newer on `PATH`.
- 16 GB RAM recommended.
- Ollama installed and running on the host.
- Local model:

```powershell
ollama pull qwen2.5
```

Internet access is required for first-time Docker image builds and model downloads.

## Start The Demo

From this `Deployment/` folder:

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

| User | Password | Role | Typical Use |
| --- | --- | --- | --- |
| `noc-exec` | `demo` | NOC Executive | Business dashboard, reports, incident overview |
| `noc-engineer` | `demo` | NOC Engineer | NOC operations, what-if, diagnostics, optimization |
| `engineer` | `demo` | AI Engineer | Model, MLflow, and technical views |
| `admin-noc` | `demo` | Site Admin | Full platform administration |

## Suggested Demo Flow

1. Open the dashboard and show live network KPIs.
2. Show detection and prediction views to explain how QoS Buddy identifies degradation.
3. Open diagnostics to show likely root causes, RAG context, and lesson capture.
4. Open optimization to show recommendations, approvals, blocked policy actions, and optional Jira escalation.
5. Open reporting to export an executive network report.
6. Open the chatbot and ask operational questions such as:
   - What is happening on the live network?
   - What incidents happened recently?
   - What actions were proposed recently?
   - What does delay variation mean?

## Local AI And Memory

The stack uses ChromaDB for incident and operational memory. Ollama runs on the host and is reached through:

```text
http://host.docker.internal:11434
```

The expected model is:

```text
qwen2.5:latest
```

No external LLM API is required for the local demo.

## Health Check

From this folder:

```powershell
.\CHECK-SSD-HEALTH.ps1
```

## Stop The Demo

From this folder:

```powershell
.\qos-buddy\stop.ps1
```

To stop and remove Docker runtime volumes intentionally:

```powershell
.\qos-buddy\stop.ps1 -RemoveVolumes
```

Only use `-RemoveVolumes` when you want to wipe local runtime state.

## Optional Jira Integration

Jira is optional. Credentials must stay local and must not be committed.

To enable Jira:

1. Copy `qos-buddy\.env.example` to `qos-buddy\.env`.
2. Set `QOS_JIRA_ENABLED=true`.
3. Fill `JIRA_URL`, `JIRA_EMAIL`, `JIRA_TOKEN`, `JIRA_PROJECT_KEY`, and `JIRA_ISSUE_TYPE`.
4. Restart affected services:

```powershell
cd .\qos-buddy
docker compose up -d --build gateway synthesis optimization shell
```

## Troubleshooting

- If the dashboard is empty, confirm the collector is running and check `qos-buddy\logs\producer.log`.
- If login fails, open Keycloak at `http://localhost:8081` and confirm the `qos-buddy` realm imported.
- If AI answers are slow, confirm Ollama is running and `qwen2.5:latest` is available.
- If ports are busy, check ports `3000`, `5432`, `6379`, `8080`, `8081`, `8088`, `8089`, `16686`, and `11434`.
- If Docker is slow, check available disk space and Docker Desktop resource settings.
