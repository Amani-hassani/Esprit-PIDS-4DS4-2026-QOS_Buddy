# QoS Buddy Runbook

Run these commands from:

```powershell
cd C:\Users\amani\OneDrive\Desktop\PI-V1
```

## Run the platform on port 8001

```powershell
python -m uvicorn deployment.api.app:create_app --factory --host 127.0.0.1 --port 8001
```

Open:

```text
http://127.0.0.1:8001
```

Use the dev tokens:

```text
viewer-dev-token
engineer-dev-token
lead-dev-token
```

## Run MLflow UI

```powershell
python scripts\launch_mlflow_ui.py --port 5000
```

This script points MLflow at the same tracking DB and artifact root used by the app, including the recovered store if the original local DB needed recovery.

Open:

```text
http://127.0.0.1:5000
```

## Test the platform

Backend:

```powershell
python -m pytest -q
```

Frontend:

```powershell
cd frontend
npm run check
npm run build
cd ..
python scripts\verify_frontend_build.py
```

Quick API smoke test:

```powershell
$h = @{Authorization='Bearer viewer-dev-token'}
Invoke-RestMethod http://127.0.0.1:8001/api/ping
Invoke-RestMethod http://127.0.0.1:8001/api/ops/drift?window=60 -Headers $h
Invoke-RestMethod http://127.0.0.1:8001/api/ops/mlops -Headers $h
Invoke-RestMethod http://127.0.0.1:8001/api/tickets/provider-health -Headers $h
```

Jira probe:

```powershell
$h = @{Authorization='Bearer engineer-dev-token'}
Invoke-RestMethod -Method Post http://127.0.0.1:8001/api/tickets/probe -Headers $h
```

Push near-live cases that create Jira tickets:

```powershell
python testing_tools\push_near_live.py --base-url http://127.0.0.1:8001 --ticket-pack --count 3 --interval-s 0 --approve-pending --list-tickets
```

Push human-intervention cases, including actions that are rejected and automatically ticketed:

```powershell
python testing_tools\push_near_live.py --base-url http://127.0.0.1:8001 --human-pack --count 6 --interval-s 0 --approve-pending --list-tickets
```

Push the full 50-case KPI snapshot + root-cause contract suite:

```powershell
python testing_tools\push_near_live.py --base-url http://127.0.0.1:8001 --case-pack --count 50 --interval-s 0 --approve-pending --list-tickets
```

Push every near-live scenario without auto-approval:

```powershell
python testing_tools\push_near_live.py --base-url http://127.0.0.1:8001 --count 50
```
