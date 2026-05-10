# QoS Buddy Diagnostic Agent Deployment

This deployment serves the 8-root-cause Diagnostic Agent with:

- Context fusion for separate Monitoring, Detection, and Prediction Agent events.
- Data quality gate with trust score and confidence penalty.
- Feature builder for the 104 leak-safe diagnostic features.
- Sequence builder for 10-sample temporal windows.
- Memory-guided GRU Autoencoder exported to NumPy for latent embeddings and reconstruction evidence.
- Native FAISS `IndexFlatL2` for latent-space root-cause prototype retrieval.
- Random Forest for root-cause probabilities.
- Radio vs transport discriminator for macro diagnostic scope.
- Multi-branch fusion for final ranked root causes and confidence.
- Dynamic ingestion endpoints for Monitoring, Prediction, and Detection agents.
- Optimization Agent handoff via queued outbox and optional HTTP push.
- LLM-backed explanation layer for causal-chain and feature-contribution narratives.
- A dark operations dashboard matching the provided QoS Buddy UI direction.

## Mandatory FAISS

The production service imports `faiss` at startup. If native FAISS is not installed, the API fails fast. There is no production fallback in `deploy/app`.

Native FAISS is generally not available for this Windows Python environment. Use the Linux Docker deployment.

## Run

From the repository root:

```powershell
docker compose -f deploy/docker-compose.yml up --build
```

Then open:

```text
http://localhost:8000
```

## Test

With the container running:

```powershell
python deploy/tests/smoke_test.py http://127.0.0.1:8000
```

The smoke test verifies:

- API health.
- Native FAISS backend.
- 8 root causes.
- Live dashboard payload.
- Incident detail payload.
- 5 FAISS prototype neighbors.
- Dynamic live-event ingestion.
- Separate detection/prediction/monitoring context fusion.
- Data quality gate output.
- Autoencoder reconstruction evidence.
- Fusion output.
- Optimization handoff queueing.
- LLM explanation field presence.

## API

- `GET /api/health`
- `GET /api/dashboard`
- `GET /api/incidents`
- `GET /api/incidents/{incident_id}`
- `GET /api/model-health`
- `POST /api/predict`
- `POST /api/ingest`
- `POST /api/open/diagnose`
- `POST /api/monitoring-agent/events`
- `POST /api/detection-agent/events`
- `POST /api/prediction-agent/events`
- `POST /api/prediction-detection/events`
- `POST /api/incidents/{incident_id}/send-to-optimization`
- `GET /api/optimization/outbox`
- `POST /api/optimization/outbox/{handoff_id}/ack`

## Dynamic Agent Input Contract

Monitoring, Prediction, and Detection agents can send one combined event:

```json
{
  "event_id": "evt-001",
  "monitoring": {
    "timestamp": "2026-04-28T18:20:00Z",
    "node_id": "N1",
    "cell_id": "CELL_001",
    "latency_ms": 310,
    "jitter_ms": 78,
    "packet_loss_pct": 1.2,
    "throughput_mbps": 1.4,
    "bandwidth_util_pct": 91,
    "queue_length": 188,
    "sinr_db": 15,
    "cqi": 9,
    "bler_proxy_pct": 2.2
  },
  "detection": {
    "anomaly_detected": true,
    "anomaly_type": "capacity_latency_smoke",
    "anomaly_score": 0.91
  },
  "prediction": {
    "horizon_minutes": 15,
    "sla_risk": 0.84,
    "confidence": 0.88
  }
}
```

The response is the full Diagnostic Agent output and is also added to the live dashboard.

Agents can also send separate events with the same `event_id`. Detection and prediction events are buffered in context fusion until monitoring data arrives:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/detection-agent/events -Method Post -ContentType application/json -Body '{"event_id":"evt-001","detection":{"anomaly_detected":true,"anomaly_score":0.91}}'
Invoke-RestMethod http://127.0.0.1:8000/api/prediction-agent/events -Method Post -ContentType application/json -Body '{"event_id":"evt-001","prediction":{"root_cause":"RC_PACKET_LOSS","confidence":0.72}}'
Invoke-RestMethod http://127.0.0.1:8000/api/monitoring-agent/events -Method Post -ContentType application/json -Body '{"event_id":"evt-001","monitoring":{"latency_ms":180,"jitter_ms":42,"packet_loss_pct":6.8,"throughput_mbps":4.6,"bandwidth_util_pct":63,"queue_length":71,"sinr_db":8,"cqi":5,"bler_proxy_pct":11.2}}'
```

The final response includes `protocol_pipeline`, `data_quality`, `autoencoder_evidence`, `radio_transport_discriminator`, and `fusion`.

## LLM Configuration

The explanation layer supports any OpenAI-compatible `/v1/chat/completions` API:

```powershell
$env:QOS_LLM_API_KEY="..."
$env:QOS_LLM_BASE_URL="https://api.openai.com/v1"
$env:QOS_LLM_MODEL="gpt-4.1-mini"
```

If `QOS_LLM_REQUIRED=true`, startup fails without a working LLM key. If it is false, the service remains testable and returns a model-grounded fallback explanation from fused model evidence, RF contributions, evidence fields, reconstruction evidence, and FAISS neighbors.

## Optimization Handoff

Every ingested diagnosis creates an optimization handoff in `/api/optimization/outbox`.

To push directly to an Optimization Agent:

```powershell
$env:OPTIMIZATION_AGENT_URL="http://optimization-agent:9000/api/actions"
$env:AUTO_SEND_TO_OPTIMIZATION="true"
```

## Artifacts

The Docker image copies `outputs_8rc` into `/app/outputs_8rc`.

Required artifacts:

- `random_forest_8rc.joblib`
- `label_encoder_8rc.joblib`
- `gru_autoencoder_numpy_8rc.npz`
- `sequence_imputer_8rc.joblib`
- `sequence_scaler_8rc.joblib`
- `sequence_windows_8rc.npz`
- `prototype_latent_scaler_8rc.joblib`
- `prototype_vectors_8rc.npz`
- `root_cause_contracts_8rc.json`
- `feature_columns_8rc.json`
- `benchmark_8rc_engineered.csv`

At startup, the service builds and writes:

- `faiss_prototype_index_8rc.faiss`
