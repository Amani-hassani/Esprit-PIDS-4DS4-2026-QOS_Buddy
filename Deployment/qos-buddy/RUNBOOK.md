# QoS Buddy Runbook

This runbook describes how to operate the SSD copy of QoS Buddy from `E:\PI-Qos Buddy`.

## 1. Prerequisites

- Docker Desktop is installed and running in Linux container mode.
- Python 3.10 or newer is available on PATH.
- Ollama is installed and running on the host.
- The local model is available:

```powershell
ollama pull qwen2.5
```

## 2. Prepare Local Environment

From the SSD project root:

```powershell
cd .\qos-buddy
Copy-Item .env.example .env
```

Edit `.env` only on the local machine. Never commit `.env`.

For normal live operation:

```text
QOS_MONITORING_MODE=tail
```

## 3. Start The Full Platform

Recommended start command from the SSD project root:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\START-HERE.ps1
```

This starts:

- The host monitoring producer from `monitoring\qos_buddy_collector.py`.
- The Docker Compose stack in `qos-buddy`.

Open the dashboard:

```text
http://localhost:3000
```

## 4. Start Pieces Manually

Start only the host monitoring producer:

```powershell
cd E:\PI-Qos Buddy\qos-buddy
.\start.ps1 -NoDocker
```

Start only Docker:

```powershell
cd E:\PI-Qos Buddy\qos-buddy
.\start.ps1 -NoProducer
```

Start Docker Compose directly:

```powershell
cd E:\PI-Qos Buddy\qos-buddy
docker compose up -d --build
```

## 5. Login

Use the branded Keycloak login page from the dashboard.

| User | Password | Role | Use |
| --- | --- | --- | --- |
| `noc-exec` | `demo` | NOC Executive | Executive overview and reports |
| `noc-engineer` | `demo` | NOC Executive | NOC workflows and What-If |
| `engineer` | `demo` | AI Engineer | Model and technical views |
| `admin-noc` | `demo` | Site Admin | Full administration |

## 6. Service URLs

| Service | URL |
| --- | --- |
| Dashboard | `http://localhost:3000` |
| Gateway API | `http://localhost:8080` |
| Keycloak | `http://localhost:8081` |
| RAG service | `http://localhost:8088` |
| Reporting service | `http://localhost:8089` |
| Jaeger tracing | `http://localhost:16686` |
| Ollama host API | `http://localhost:11434` |

## 7. Validate Health

From the SSD project root:

```powershell
.\CHECK-SSD-HEALTH.ps1
```

Expected checks:

- Docker Compose services are up.
- Prediction health reports models ready.
- ChromaDB includes the `qos_incidents` collection.
- Optimization MLflow reports runs/traces/artifacts.
- Recent bridge logs show normal event flow.

## 8. Day-To-Day Operations

Show running containers:

```powershell
cd E:\PI-Qos Buddy\qos-buddy
docker compose ps
```

Tail dashboard and gateway logs:

```powershell
docker compose logs -f shell gateway
```

Tail pipeline logs:

```powershell
docker compose logs -f monitoring detection-bridge diagnostic-bridge prediction-bridge optimization-bridge
```

Restart one service:

```powershell
docker compose restart gateway
```

Rebuild one service after code changes:

```powershell
docker compose up -d --build gateway
```

Stop everything:

```powershell
.\stop.ps1
```

Stop and intentionally remove runtime volumes:

```powershell
.\stop.ps1 -RemoveVolumes
```

## 9. Live Monitoring

The live collector runs on the host because it reads host network/system signals. The producer log is:

```text
qos-buddy\logs\producer.log
```

The Docker `monitoring` service tails:

```text
monitoring\network_stream.jsonl
```

If dashboard KPIs stop changing:

1. Check that the producer process is running.
2. Tail `qos-buddy\logs\producer.log`.
3. Check `docker compose logs --tail 50 monitoring gateway`.
4. Restart only the producer or monitoring bridge if needed.

## 10. RAG And Chatbot

The active vector store is ChromaDB. Qdrant is not required by this stack.

The chatbot can answer about:

- Live network state.
- Recent incidents and alerts.
- Diagnostics and likely causes.
- Optimization actions.
- Reports and post-mortem lessons.
- Basic explanations of network metrics.

The chatbot should stay scoped to QoS Buddy and network operations.

## 11. Jira

Jira is optional and disabled by default.

To enable it:

1. Set `QOS_JIRA_ENABLED=true` in `.env`.
2. Fill `JIRA_URL`, `JIRA_EMAIL`, `JIRA_TOKEN`, `JIRA_PROJECT_KEY`, and `JIRA_ISSUE_TYPE`.
3. Restart only affected services:

```powershell
docker compose up -d --build gateway synthesis optimization shell
```

Never commit Jira tokens.

## 12. Common Issues

If login fails:

- Confirm `qos-keycloak` is running.
- Open `http://localhost:8081`.
- Confirm the `qos-buddy` realm exists.
- If the realm was changed badly during testing, stop with `-RemoveVolumes` only if wiping local Keycloak state is acceptable.

If AI answers are slow:

- Confirm Ollama is running.
- Confirm `ollama list` shows `qwen2.5:latest`.
- Check `docker compose logs --tail 50 rag reporting diagnostic-bridge synthesis`.

If prediction is unhealthy:

- Run `.\CHECK-SSD-HEALTH.ps1`.
- Check `docker compose logs --tail 80 prediction prediction-bridge`.
- Confirm prediction models exist under `prediction_agent\prediction_agent\models\saved`.

If the PC system drive is low on space:

- Keep the project under the SSD path.
- Do not move Docker runtime folders into the system drive.
- Avoid committing or copying `docker-data`, logs, build caches, JSONL streams, or MLflow/Chroma runtime state into Git.
