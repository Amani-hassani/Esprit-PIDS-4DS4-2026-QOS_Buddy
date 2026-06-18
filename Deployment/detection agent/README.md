# Detection Agent

The Detection Agent identifies anomalous network behavior from QoS telemetry. It is packaged as a FastAPI backend with trained model artifacts and a Svelte frontend used during development.

## Role In QoS Buddy

The agent receives monitoring metrics, evaluates whether current behavior is abnormal, and returns anomaly status, anomaly type, and confidence values. The integrated Docker stack calls this service through the detection bridge in `Deployment/qos-buddy`.

## Main Components

```text
detection agent/
|-- backend/       FastAPI service, inference code, Dockerfile, trained models
|-- frontend/      SvelteKit dashboard used for agent-level inspection
|-- scripts/       Deployment, backup, health, and update helpers
|-- nginx/         Nginx configuration for packaged deployment
`-- docker-compose.yml
```

## Local Development

Backend dependencies are listed in:

```text
backend/requirements.txt
```

The integrated demo normally starts this agent through:

```powershell
cd ..\qos-buddy
docker compose up -d --build detection detection-bridge
```

## Artifacts

The backend uses the packaged model files under `backend/models/`. These are committed intentionally so the local demo can run without retraining.

## Notes

- Real runtime secrets should be placed in a local `.env` file only.
- `.env.example` documents the expected local variables.
- This agent is part of the wider QoS Buddy workflow and is usually reviewed together with the monitoring, prediction, diagnostic, and optimization agents.
