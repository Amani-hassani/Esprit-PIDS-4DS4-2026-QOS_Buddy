# QOS-Buddy Portable Demo

## Requirements

- Windows 10/11
- Docker Desktop running with Linux containers
- Python 3.10 or newer on PATH
- 16 GB RAM recommended
- Local Ollama running on the computer with `qwen2.5:latest` installed
- Internet on first run so Docker can pull base images

## Start

Open PowerShell in this folder and run:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\START-HERE.ps1
```

Then open:

```text
http://localhost:3000
```

The first run can take a while because Docker builds the local services. LLM calls use your computer's local Ollama at `localhost:11434`.

## Stop

```powershell
.\qos-buddy\stop.ps1
```

To wipe Docker volumes too:

```powershell
.\qos-buddy\stop.ps1 -RemoveVolumes
```

## Jira

This package ships with Jira disabled and no credentials. To use Jira on the target machine, edit `qos-buddy\.env`, set `QOS_JIRA_ENABLED=true`, and add that machine's Jira URL/email/token/project.

## Troubleshooting

- If Docker says ports are in use, stop anything using ports 3000, 8080, 8081, 8088, 8089, 5432, or 6379.
- If the dashboard is empty after first start, wait 60-90 seconds and hard-refresh the browser.
- Logs are available with `docker compose logs -f gateway shell monitoring` from the `qos-buddy` folder.
