# Runbook

This runbook describes the local demo path for reviewers and team members.

## Requirements

- Windows 10 or 11.
- Docker Desktop running in Linux container mode.
- PowerShell.
- Python 3.10 or newer.
- Ollama installed and running on the host.
- Local model:

```powershell
ollama pull qwen2.5
```

## Start

Run from the `Deployment/` folder:

```powershell
cd Deployment
Set-ExecutionPolicy -Scope Process Bypass
.\START-HERE.ps1
```

The launcher starts the host-side monitoring producer and then starts the Docker Compose stack in `Deployment/qos-buddy`.

Open:

```text
http://localhost:3000
```

## Stop

Run from `Deployment/`:

```powershell
.\qos-buddy\stop.ps1
```

To intentionally remove local runtime volumes:

```powershell
.\qos-buddy\stop.ps1 -RemoveVolumes
```

Only use `-RemoveVolumes` when you want to wipe local runtime state.

## Health Check

Run from `Deployment/`:

```powershell
.\CHECK-SSD-HEALTH.ps1
```

Useful Docker checks from `Deployment/qos-buddy`:

```powershell
docker compose ps
docker compose logs --tail 50 gateway shell rag reporting
docker compose logs --tail 50 monitoring detection-bridge diagnostic-bridge prediction-bridge optimization-bridge
```

## Common Ports

| Port | Service |
| --- | --- |
| `3000` | Dashboard |
| `5432` | PostgreSQL |
| `6379` | Redis |
| `8080` | Gateway API |
| `8081` | Keycloak |
| `8088` | RAG service |
| `8089` | Reporting service |
| `11434` | Host Ollama |
| `16686` | Jaeger |

## Troubleshooting

- If the dashboard is empty, confirm the monitoring producer is running and check `Deployment/qos-buddy/logs/producer.log`.
- If login fails, open Keycloak at `http://localhost:8081` and confirm the `qos-buddy` realm imported.
- If AI features are slow or unavailable, confirm Ollama is running and `qwen2.5:latest` is available.
- If ports are busy, stop the conflicting local service or change the relevant Docker Compose mapping.
- If Docker builds fail, confirm Docker Desktop is running and has enough disk space.
- If router metrics are unavailable, the collector can still run with host and Wi-Fi metrics.

