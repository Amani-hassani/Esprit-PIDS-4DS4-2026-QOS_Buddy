# Pipeline Monitoring UI

This optional UI helps inspect the monitoring pipeline while preserving the existing JSONL event formats. It provides a FastAPI backend and a React frontend for event summaries, action views, raw logs, and pipeline status.

## Layout

```text
pipeline_ui/
|-- backend/       FastAPI application and services
|-- frontend/      React application
|-- run_backend.bat
|-- run_frontend.bat
`-- README.md
```

## Requirements

- Python 3.10 or newer.
- Node.js 18 or newer.
- Existing JSONL files from the main monitoring workflow:
  - `network_stream.jsonl`
  - `monitoring_events.jsonl`
  - `workflow_actions.jsonl`

## Backend

From `pipeline_ui/backend`:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

## Frontend

From `pipeline_ui/frontend`:

```powershell
npm install
Copy-Item .env.example .env
npm run dev
```

Open:

```text
http://127.0.0.1:5173
```

## API Endpoints

- `GET /api/summary`
- `GET /api/events`
- `GET /api/events/{event_id}`
- `GET /api/actions`
- `GET /api/actions/comparison`
- `GET /api/logs/raw`
- `GET /api/pipeline/status`

## Reliability Notes

- Invalid JSONL lines are ignored instead of crashing the UI.
- Missing files return empty responses.
- The frontend polls every two seconds.
- The UI does not change the source event format.
