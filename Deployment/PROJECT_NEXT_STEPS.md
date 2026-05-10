# QoS Buddy SSD Project Checklist

Active project path:

```powershell
E:\PI-Qos Buddy
```

## Daily Start / Stop

Start:

```powershell
cd "E:\PI-Qos Buddy"
.\START-HERE.ps1
```

Stop without deleting data:

```powershell
cd "E:\PI-Qos Buddy\qos-buddy"
.\stop.ps1
```

Stop and wipe Docker volumes only when you intentionally want a clean reset:

```powershell
.\stop.ps1 -RemoveVolumes
```

## Fast Health Checks

One-command SSD health check:

```powershell
cd "E:\PI-Qos Buddy"
.\CHECK-SSD-HEALTH.ps1
```

Remove generated caches/runtime markers:

```powershell
cd "E:\PI-Qos Buddy"
.\CLEAN-GENERATED.ps1
```

```powershell
cd "E:\PI-Qos Buddy\qos-buddy"
docker compose ps
docker compose logs --tail 80 detection-bridge diagnostic-bridge prediction-bridge optimization-bridge
```

Prediction health:

```powershell
docker exec qos-prediction python -c "import urllib.request,json; print(json.dumps(json.load(urllib.request.urlopen('http://localhost:8000/api/health/full')), indent=2))"
```

Optimization MLflow:

```powershell
docker exec qos-optimization python -c "import urllib.request,json; req=urllib.request.Request('http://localhost:8000/api/ops/mlops', headers={'Authorization':'Bearer viewer-dev-token'}); print(json.dumps(json.load(urllib.request.urlopen(req)), indent=2))"
```

## Agent Flow

The services stay running, but work is event-driven:

1. Monitoring tails host/network metrics and publishes raw events to Redis.
2. Detection scores raw metrics and emits anomaly alerts.
3. Diagnostic reacts to alerts and produces root-cause contracts.
4. Prediction buffers metric windows and periodically forecasts future risk.
5. Optimization reacts to monitoring snapshots and diagnosis contracts, chooses/policy-gates actions, and logs decisions to MLflow.
6. Synthesis/reporting/dashboard aggregate the live state for the operator.

## Memory Stores

MLflow:

- Optimization is actively logging decision runs, metrics, traces, and JSON artifacts such as `decision_context.json` and `policy_decision.json`.
- Prediction MLflow is configured at `/app/mlflow-data/mlflow.db`; it may show zero runs until the prediction service emits a forecast/logged run.
- `CHECK-SSD-HEALTH.ps1` reports both MLflow metadata and artifact file counts.

ChromaDB:

- Used by prediction for incident similarity/RAG.
- Collection: `qos_incidents`.
- Expected count in this package: about `301`.

Inspect:

```powershell
docker exec qos-prediction python -c "import chromadb,json; c=chromadb.PersistentClient(path='/app/rag/chroma_db'); col=c.get_collection('qos_incidents'); print(col.count()); print(json.dumps(col.peek(5), default=str)[:2000])"
```

Qdrant:

- Removed from the active SSD compose stack after code inspection showed no runtime writers or readers.
- The old Docker volume/export can remain as backup data; do not delete volumes unless intentionally cleaning Docker state.

## Portable Artifacts

Docker images:

```text
E:\PI-Qos Buddy\docker-export\qos-buddy-images.tar
```

Docker volume backups:

```text
E:\PI-Qos Buddy\docker-export\volumes
```

Restore/load notes:

```text
E:\PI-Qos Buddy\SSD_RESTORE_NOTES.md
```

Restore helper script:

```powershell
cd "E:\PI-Qos Buddy"
.\RESTORE-DOCKER-ASSETS.ps1
```

By default, existing Docker volumes are skipped. Use `-OverwriteVolumes` only when you intentionally want to replace volume contents from the SSD backups.

## Next Engineering Work

1. Add local test dependencies or run tests inside dedicated test containers.
2. Keep Qdrant out of the active stack unless a real code path is added for it.
3. Optionally expose MLflow UI for prediction and optimization in a documented way.
