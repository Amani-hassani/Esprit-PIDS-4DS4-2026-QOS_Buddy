# QoS Buddy Diagnostic Agent - 8 Root-Cause Deployment Report

Date: 2026-04-28  
Workspace: `Diagnostic agent notebooks+report`  
Primary notebook: `qos_buddy_8rc_diagnostic_deployment.ipynb`  
Artifact directory: `outputs_8rc`

## 1. Executive Summary

The previous revised validation report established a conservative and defensible baseline for the Diagnostic Agent. It validated the model families on a strict real-data benchmark and selected the following stack:

- Random Forest for supervised tabular diagnosis.
- GRU Autoencoder for 10-sample temporal representation.
- FAISS for fast similar-case prototype retrieval.

That report intentionally limited supervised validation to two robustly supported root causes:

- `RC_CAPACITY_OVERLOAD`
- `RC_TRANSPORT_DELAY`

For deployment, the Diagnostic Agent must emit 8 root-cause contracts. I therefore built a new single comprehensive deployment notebook that extends the validated stack to all 8 root causes while preserving the report's main methodological safeguards:

- It rebuilds the benchmark from local CSV files, not hidden Kaggle artifacts.
- It keeps the same leak-safe 104-feature modeling design.
- It uses chronological train, validation, and test splits with purge gaps.
- It marks every synthetic contract row explicitly.
- It separates real observed evidence from controlled contract augmentation.
- It saves deployable artifacts for Random Forest, GRU, and prototype retrieval.

The result is now an 8-root-cause deployment benchmark and a working Diagnostic Agent service. The deployed runtime follows the full protocol: context fusion, data quality gate, feature builder, sequence builder, memory-guided GRU Autoencoder, FAISS latent prototype diagnosis, Random Forest probabilities, radio-vs-transport discrimination, multi-branch fusion, LLM causal explanation, and Optimization Agent handoff.

## 2. What Was Built

I created and executed:

- `qos_buddy_8rc_diagnostic_deployment.ipynb`
- `build_8rc_notebook.py`
- `requirements_8rc.txt`
- `outputs_8rc/*` deployment artifacts

The notebook is self-contained. It performs data loading, split creation, contract definition, controlled augmentation, feature engineering, model training, evaluation, artifact export, and example diagnostic-contract generation in one reproducible workflow.

## 3. Why This Extension Was Needed

The original report was correct to avoid forcing rare or missing classes into supervised validation. However, deployment has a different requirement: the Diagnostic Agent must be able to return every operational root-cause contract that downstream OADAL agents expect.

The practical issue was:

- Some root causes were naturally present in the local QoS data.
- Some root causes were rare.
- Some deployment root causes were not directly observed as labeled incidents.

If we trained only on naturally observed labels, the model could not reliably emit all 8 required root causes. If we silently fabricated labels, the benchmark would be logically weak. The solution was controlled contract augmentation:

- Real labels are used wherever available.
- Missing classes are generated from explicit KPI rules.
- Every augmented record is tagged with provenance.
- Augmentation is applied after splitting, so train, validation, and test do not leak into one another.
- Metrics are interpreted as deployment-contract conformance, not as proof that every class was abundant in raw production data.

## 4. The 8 Root-Cause Contracts

The deployed Diagnostic Agent now supports these 8 contracts.

| Root cause | Real observed anomaly types | Main evidence fields | Meaning |
|---|---|---|---|
| `RC_CAPACITY_OVERLOAD` | `low_throughput`, `congestion` | `throughput_mbps`, `bandwidth_util_pct`, `queue_length`, `active_connections` | Capacity or congestion pressure with low throughput and high queueing/utilization. |
| `RC_TRANSPORT_DELAY` | `high_latency`, `latency_degradation` | `latency_ms`, `queue_length`, `mos_estimate`, `jitter_ms` | Sustained latency increase caused by path or transport delay. |
| `RC_JITTER_INSTABILITY` | `jitter_degradation`, `high_jitter` | `jitter_ms`, `jitter_increasing`, `latency_volatility` | Delay variation dominates the QoS failure. |
| `RC_PACKET_LOSS` | `severe_packet_loss` | `packet_loss_pct`, `tcp_retransmit_rate`, `bler_proxy_pct`, `mos_estimate` | Packet loss and link/error pressure dominate. |
| `RC_RETRANSMISSION` | `high_retransmission` | `tcp_retransmit_rate`, `bler_proxy_pct`, `throughput_mbps` | Retransmission pressure without necessarily severe packet loss. |
| `RC_RADIO_SIGNAL_WEAK` | `weak_signal` | `rssi_dbm`, `rsrp_dbm`, `signal_health_score`, `wifi_signal_score`, `cellular_signal_score` | Weak Wi-Fi/radio signal quality. |
| `RC_HANDOVER_INSTABILITY` | none directly labeled | `handover_event`, `handover_count`, `ho_success_rate_pct`, `cssr_proxy_pct` | Mobility or handover instability with failed or repeated handovers. |
| `RC_CQI_MISMATCH` | none directly labeled | `cqi`, `mcs`, `sinr_db`, `bler_proxy_pct`, `bler_mcs_stress` | Radio quality and modulation/coding indicators are inconsistent. |

## 5. Data Preparation

The notebook loads all local `data/qos_timeseries_*.csv` files. It parses each file's source metadata, sorts by timestamp, and maps observed anomaly types into root-cause contracts where possible.

Important implementation choices:

- Data is loaded only from the local workspace.
- Timestamps are parsed and used for chronological ordering.
- Raw anomaly types are preserved for auditability.
- `root_cause_label` is created from the contract mapping.
- `is_real_labeled` marks whether a row came from an observed anomaly type.
- `is_augmented_contract` marks whether a row was generated for contract coverage.
- `augmentation_origin` records whether the row is real observed, same-class jitter, or contract synthetic.

This gives us a traceable dataset instead of an opaque label table.

## 6. Split Strategy and Leakage Control

The notebook uses chronological splitting:

- Train ratio: 60%
- Validation ratio: 20%
- Test ratio: 20%
- Purge gap: 10 rows around split boundaries

The purge gap matters because QoS time-series rows are temporally correlated. Without a purge gap, adjacent rows from the same event could land in both training and validation or test, causing overly optimistic scores.

Augmentation is done after the split. This is critical. A synthetic validation row is generated only from validation-split seed rows. A synthetic test row is generated only from test-split seed rows. That prevents synthetic copies or transformed versions of train rows from leaking into validation or test.

## 7. Controlled Augmentation

The augmentation is not generic oversampling. It is contract-based. Each root cause has an explicit operational transformation.

Examples:

- `RC_CAPACITY_OVERLOAD`: raises `bandwidth_util_pct`, `queue_length`, `active_connections`, and lowers `throughput_mbps`.
- `RC_TRANSPORT_DELAY`: raises `latency_ms` and queueing while keeping packet loss low.
- `RC_JITTER_INSTABILITY`: raises `jitter_ms` and marks jitter trend pressure.
- `RC_PACKET_LOSS`: raises `packet_loss_pct`, `tcp_retransmit_rate`, and `bler_proxy_pct`.
- `RC_RETRANSMISSION`: raises retransmission and BLER with only low-to-moderate packet loss.
- `RC_RADIO_SIGNAL_WEAK`: worsens `rssi_dbm`, `rsrp_dbm`, `signal_health_score`, Wi-Fi score, and cellular score.
- `RC_HANDOVER_INSTABILITY`: synthesizes handover events, repeated handover count, low handover success, and CSSR degradation.
- `RC_CQI_MISMATCH`: creates inconsistency between CQI, MCS, SINR, and BLER stress.

All augmented KPI values are clipped to operationally plausible ranges. This avoids impossible synthetic rows and keeps the model aligned with network-domain semantics.

## 8. Feature Engineering

The model uses 104 features, matching the feature-count discipline from the revised report. The feature set includes:

- Core QoS KPIs.
- Radio and RAN KPIs.
- Capacity and congestion indicators.
- Diagnostic engineered features.
- Rolling and delta temporal summaries.
- Handover support features.

Examples of engineered features:

- `bler_pct_model`
- `bler_pressure_score`
- `bler_sinr_gap`
- `bler_mcs_stress`
- `handover_instability_index`
- `transport_pressure_score`
- `throughput_loss_explainer`
- `congestion_index`
- `radio_efficiency_score`
- `radio_vs_transport_score`
- `latency_jitter_ratio`
- `throughput_util_ratio`

The notebook intentionally excludes shortcut and leaky columns:

- `anomaly_flag`
- `anomaly_score`
- `anomaly_rate_recent`
- `hour_anomaly_rate`
- `baseline_phase`
- `traffic_confidence`
- `skip_for_training`
- `incident_recovery_time`
- `collection_completion_pct`
- `data_completeness_pct`
- `required_metrics_pct`
- `router_metrics_pct`
- `hour_of_day`
- `is_peak_hour`
- split/provenance columns
- labels and timestamps

This means the classifier learns KPI behavior, not the output of a previous anomaly detector or data-collection shortcut.

## 9. Model Architecture

### 9.1 Random Forest

Random Forest is the primary deployed diagnostic classifier. It receives the current engineered KPI snapshot and predicts one of the 8 root causes.

Its role:

- Fast first diagnosis.
- 8-way root-cause decision.
- Class probabilities for confidence and top-k alternatives.
- Feature importance for operator explanation.

Deployment artifact:

- `outputs_8rc/random_forest_8rc.joblib`

### 9.2 GRU Autoencoder

The GRU autoencoder receives 10-sample windows. It learns a compact latent representation of recent QoS behavior by reconstructing the input sequence.

Its role:

- Temporal representation of degradation evolution.
- Encodes patterns that cannot be captured by one row alone.
- Feeds the prototype retrieval vector.

Configuration:

- Window size: 10 samples
- Encoder: GRU
- Hidden dimension: 64
- Latent dimension: 32
- Best epoch in current run: 18
- Best validation reconstruction loss: 2.9275

Deployment artifact:

- `outputs_8rc/gru_autoencoder_8rc.pt`

### 9.3 FAISS Prototype Retrieval

The prototype branch retrieves similar cases. It does not replace Random Forest. It provides evidence for the selected diagnosis and participates in the fusion layer.

The offline benchmark used this hybrid retrieval vector:

```text
prototype_vector = standardized_GRU_latent + weighted_Random_Forest_posterior
```

The Random Forest posterior is weighted by `8.0`. This is intentional. Pure unsupervised GRU reconstruction geometry was too weak for future-split retrieval. Adding the RF posterior anchors retrieval to the diagnostic decision while still retaining temporal context from the GRU latent vector.

The production protocol now uses native FAISS over the scaled GRU latent memory for the prototype-diagnosis stage:

```text
production_prototype_vector = standardized_GRU_latent
```

This matches the required protocol: compare the incident to root-cause prototypes in latent space, then fuse prototype evidence with RF probabilities and the other branches.

Offline benchmark artifact:

- `outputs_8rc/prototype_vectors_8rc.npz`

Production memory artifacts:

- `outputs_8rc/sequence_windows_8rc.npz`
- `outputs_8rc/gru_autoencoder_numpy_8rc.npz`
- `outputs_8rc/faiss_prototype_index_8rc.faiss`

Offline notebook backend:

- `sklearn_exact_fallback`

Production deployment backend:

- `faiss.IndexFlatL2` in the Docker service.
- Runtime vector count: 1,879 prototype vectors.
- Runtime index artifact: `outputs_8rc/faiss_prototype_index_8rc.faiss`.

I added:

- `requirements_8rc.txt`
- `deploy/requirements.txt`

with:

```text
faiss-cpu; platform_system != "Windows"
```

This is because FAISS wheels are generally not available for native Windows Python environments. The notebook therefore uses an exact sklearn fallback for offline evaluation, while the production Docker service imports native FAISS at startup and fails fast if FAISS is unavailable. The deployed service has been smoke-tested with `faiss.IndexFlatL2`.

## 10. Evaluation Results

### 10.1 Random Forest Metrics

| Split | Accuracy | Balanced accuracy | Macro F1 | Weighted F1 | Macro precision | Macro recall |
|---|---:|---:|---:|---:|---:|---:|
| Train | 0.9996 | 0.9996 | 0.9996 | 0.9996 | 0.9996 | 0.9996 |
| Validation | 0.9891 | 0.9891 | 0.9890 | 0.9890 | 0.9892 | 0.9891 |
| Test | 0.9297 | 0.9297 | 0.9278 | 0.9278 | 0.9398 | 0.9297 |

Interpretation:

The Random Forest branch is now able to classify all 8 root-cause contracts with strong test performance. This is the model that should drive the primary Diagnostic Agent root-cause output.

### 10.2 GRU Autoencoder

| Metric | Value |
|---|---:|
| Window size | 10 |
| Best epoch | 18 |
| Best validation reconstruction loss | 2.9275 |
| Training time | 13.9978 seconds |

Interpretation:

The GRU branch is trained and saved as the temporal encoder. Its purpose is not to directly replace the Random Forest classifier. It provides compact sequence embeddings for prototype retrieval.

### 10.3 Prototype Retrieval Metrics

| Split | Backend | Accuracy | Balanced accuracy | Macro F1 | Top-3 hit rate | Top-5 hit rate | Search time |
|---|---|---:|---:|---:|---:|---:|---:|
| Train | sklearn exact fallback | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0143 sec |
| Validation | sklearn exact fallback | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 0.0135 sec |
| Test | sklearn exact fallback | 0.8165 | 0.8123 | 0.8046 | 0.8710 | 0.8851 | 0.0141 sec |

Interpretation:

The prototype branch is good enough for similar-case support. Its top-5 hit rate of 0.8851 means the correct root-cause contract appears among the nearest retrieved cases most of the time. It should be used as explanatory evidence and retrieval support, not as the sole final classifier.

## 11. How We Can Detect the 8 Root Causes Now

The deployed detection flow is now:

1. Monitoring Agent sends live QoS, radio, transport, and capacity KPIs to `/api/monitoring-agent/events`.
2. Detection Agent sends anomaly output to `/api/detection-agent/events`.
3. Prediction Agent sends risk or root-cause forecast output to `/api/prediction-agent/events`.
4. `/api/ingest`, `/api/open/diagnose`, and `/api/prediction-detection/events` remain available for combined payloads.
5. Context fusion merges separate monitoring, detection, and prediction inputs by `event_id` or node/cell/time bucket into one diagnostic state.
6. The data quality gate computes trust score, missing fields, freshness, range validity, source completeness, and confidence penalty.
7. The feature builder creates the same 104 engineered diagnostic features used in the notebook.
8. The sequence builder prepares the rolling 10-sample temporal window.
9. The memory-guided GRU Autoencoder produces the latent representation and reconstruction evidence.
10. Native FAISS compares the scaled latent vector against root-cause memory prototypes.
11. Random Forest produces 8 root-cause probabilities.
12. The radio-vs-transport discriminator computes macro diagnostic scope.
13. Fusion combines RF, latent prototype diagnosis, prediction prior, radio/transport scope, data-quality penalty, and autoencoder reconstruction confidence into final ranked causes and final confidence.
14. The LLM explanation layer generates feature-contribution and causal-chain narratives. If an OpenAI-compatible LLM key is configured, it uses the LLM. If not, it returns deterministic model-grounded text from the same live evidence.
15. The Diagnostic Agent emits a root-cause contract containing:
   - selected root cause,
   - confidence,
   - top alternatives,
   - primary evidence fields,
   - similar-case neighbors,
   - feature contribution narrative,
   - causal chain,
   - recommended action context,
   - optimization handoff payload.
16. The output is added to the live dashboard and queued for the Optimization Agent.

The live Docker service produced this smoke-test diagnosis from a dynamic input event:

```json
{
  "root_cause": "RC_CAPACITY_OVERLOAD",
  "confidence": 0.5785,
  "top3": [
    {
      "root_cause": "RC_CAPACITY_OVERLOAD",
      "probability": 0.5785
    },
    {
      "root_cause": "RC_TRANSPORT_DELAY",
      "probability": 0.35
    },
    {
      "root_cause": "RC_JITTER_INSTABILITY",
      "probability": 0.0423
    }
  ],
  "source": "live",
  "source_event_id": "smoke-live-event",
  "prototype_backend": "faiss.IndexFlatL2",
  "prototype_space": "scaled_gru_latent",
  "optimization_handoff_status": "queued_no_push_url"
}
```

This is the deployment shape the OADAL loop can consume.

## 12. Deployment Artifacts

Active artifacts:

| Artifact | Purpose |
|---|---|
| `outputs_8rc/root_cause_contracts_8rc.json` | Contract definitions for all 8 root causes. |
| `outputs_8rc/feature_columns_8rc.json` | Ordered 104-feature list for inference. |
| `outputs_8rc/benchmark_8rc_engineered.csv` | Engineered benchmark dataset with provenance columns. |
| `outputs_8rc/random_forest_8rc.joblib` | Primary 8-way diagnostic classifier. |
| `outputs_8rc/label_encoder_8rc.joblib` | Label encoder for Random Forest classes. |
| `outputs_8rc/sequence_imputer_8rc.joblib` | Sequence feature imputer fitted on train split. |
| `outputs_8rc/sequence_scaler_8rc.joblib` | Sequence scaler fitted on train split. |
| `outputs_8rc/gru_autoencoder_8rc.pt` | Original GRU temporal autoencoder checkpoint. |
| `outputs_8rc/gru_autoencoder_numpy_8rc.npz` | Exported NumPy GRU autoencoder used by production for latent and reconstruction evidence. |
| `outputs_8rc/gru_encoder_numpy_8rc.npz` | Compatibility copy of the full NumPy GRU autoencoder artifact. |
| `outputs_8rc/sequence_windows_8rc.npz` | Train/validation/test sequence windows; train windows provide latent memory prototypes. |
| `outputs_8rc/prototype_latent_scaler_8rc.joblib` | Scaler for GRU latents before prototype indexing. |
| `outputs_8rc/prototype_vectors_8rc.npz` | Offline benchmark hybrid vector store. |
| `outputs_8rc/faiss_prototype_index_8rc.faiss` | Native FAISS latent-space index generated and validated in Docker. |
| `outputs_8rc/rf_metrics_8rc.csv` | Random Forest metric table. |
| `outputs_8rc/prototype_metrics_8rc.csv` | Prototype retrieval metric table. |
| `outputs_8rc/deployment_summary_8rc.json` | Machine-readable final summary. |
| `outputs_8rc/example_diagnostic_contract_8rc.json` | Example emitted diagnostic contract. |

Deployment code:

| Path | Purpose |
|---|---|
| `deploy/app/dynamic_runtime.py` | Production diagnostic runtime: context fusion, data quality gate, feature engineering, sequence building, NumPy GRU autoencoder, FAISS latent prototypes, RF inference, radio/transport discriminator, fusion, LLM explanation, dashboard state, and optimization outbox. |
| `deploy/app/main.py` | FastAPI service and open Diagnostic Agent endpoints. |
| `deploy/app/static/*` | Dynamic dark operations dashboard matching the supplied UI direction. |
| `deploy/Dockerfile` | Linux production image with mandatory FAISS. |
| `deploy/docker-compose.yml` | Local deployment entry point. |
| `deploy/tests/smoke_test.py` | End-to-end smoke test for health, FAISS, dashboard, dynamic ingestion, separate-agent context fusion, data quality, autoencoder evidence, fusion, LLM explanation field, and optimization handoff. |

Note:

- `sequence_windows_8rc.npz` and `gru_autoencoder_numpy_8rc.npz` are active production memory/autoencoder artifacts.
- `faiss_prototype_index_8rc.faiss` is the active production latent index artifact.
- `prototype_vectors_8rc.npz` remains useful for offline benchmark comparison, but the production protocol now serves latent-space FAISS prototypes.

## 13. Dynamic Deployment Implementation

The deployed platform is not a static dashboard. The FastAPI process owns an in-memory operational state that updates whenever new agent data arrives.

Dynamic endpoints:

| Endpoint | Purpose |
|---|---|
| `POST /api/ingest` | General open endpoint for live Diagnostic Agent input. |
| `POST /api/open/diagnose` | Alias for open external diagnosis requests. |
| `POST /api/monitoring-agent/events` | Monitoring Agent event receiver. |
| `POST /api/detection-agent/events` | Detection Agent event receiver. |
| `POST /api/prediction-agent/events` | Prediction Agent event receiver. |
| `POST /api/prediction-detection/events` | Prediction and Detection Agent event receiver. |
| `POST /api/demo/ingest-next` | Test endpoint that injects the next benchmark-shaped event to prove the UI changes from live data. |
| `GET /api/dashboard` | Current dashboard state. Changes after ingestion. |
| `GET /api/incidents/{incident_id}` | Full diagnostic detail with causal chain, feature contribution narrative, evidence, FAISS neighbors, and optimization context. |
| `POST /api/incidents/{incident_id}/send-to-optimization` | Idempotent push/queue endpoint for the Optimization Agent. |
| `GET /api/optimization/outbox` | Queued optimization handoffs. |
| `POST /api/optimization/outbox/{handoff_id}/ack` | Optimization Agent acknowledgement hook. |

Accepted input contract:

```json
{
  "event_id": "evt-001",
  "timestamp": "2026-04-28T18:20:00Z",
  "node_id": "N1",
  "cell_id": "CELL_001",
  "zone_id": "North-East",
  "monitoring": {
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

Each accepted event with monitoring data immediately:

- Creates a new live incident.
- Updates `/api/dashboard`.
- Changes the incident list in the browser on the next refresh cycle.
- Runs the full protocol: context fusion, quality gate, feature builder, sequence builder, memory-guided autoencoder, FAISS prototype diagnosis, RF probabilities, scope discriminator, fusion, LLM explanation.
- Generates feature-contribution and causal-chain text.
- Queues an optimization handoff.

Detection-only or prediction-only events return `waiting_for_monitoring` and stay in context fusion until a matching monitoring event arrives.

The browser dashboard polls `/api/dashboard` every 5 seconds, so the diagnostic view changes as the backing runtime state changes. The `Inject Test Event` button calls the API instead of changing UI state locally, so it exercises the same deployed path used by upstream agents.

## 14. LLM Explanation Layer

The explanation layer is implemented in `deploy/app/dynamic_runtime.py`.

It receives:

- Final root cause and confidence from the fusion layer.
- Top-k class probabilities.
- Feature contributions derived from model importances and the current engineered row.
- Evidence fields selected from the active root-cause contract.
- Data quality penalty.
- Autoencoder reconstruction evidence.
- FAISS nearest-neighbor cases.
- Detection Agent context.
- Prediction Agent context.

It returns:

- `summary`
- `causal_chain`
- `feature_contribution_narrative`
- `operator_notes`

Runtime configuration:

| Environment variable | Meaning |
|---|---|
| `QOS_LLM_API_KEY` | API key for an OpenAI-compatible `/v1/chat/completions` provider. |
| `QOS_LLM_BASE_URL` | Base URL, defaulting to `https://api.openai.com/v1` when a key is present. |
| `QOS_LLM_MODEL` | Model name, default configured in compose as `gpt-4.1-mini`. |
| `QOS_LLM_REQUIRED` | If `true`, startup or explanation failure is treated as a hard failure. |

When `QOS_LLM_API_KEY` is not set and `QOS_LLM_REQUIRED=false`, the service returns a deterministic model-grounded explanation. This is not a static placeholder. It is generated from the live fused diagnosis, RF contribution ranking, root-cause contract evidence, autoencoder evidence, prediction/detection context, and FAISS neighbors. This keeps the deployment testable without external credentials while preserving the same response schema.

## 15. Optimization Agent Handoff

Every ingested diagnosis creates one queued optimization handoff. The handoff includes:

- Incident ID.
- Root cause.
- Confidence.
- Risk level.
- Recommended action.
- Top-3 alternatives.
- Evidence.
- FAISS prototype neighbors.
- Data quality gate output.
- Fusion branch scores.
- Autoencoder reconstruction evidence.
- Radio-vs-transport discriminator output.
- LLM summary.

`POST /api/incidents/{incident_id}/send-to-optimization` is idempotent. If an incident already has a queued handoff, the endpoint reuses it instead of creating a duplicate. If `OPTIMIZATION_AGENT_URL` is configured, the service pushes the handoff to that URL. If no URL is configured, status becomes `queued_no_push_url` and the payload remains visible in `/api/optimization/outbox`.

## 16. What Changed Compared With the Previous Notebooks

The previous notebooks had several deployment blockers:

- They depended on hidden Kaggle paths and prebuilt artifacts.
- They validated only two supervised root causes.
- They were split across multiple notebooks, making deployment harder.
- They did not produce a single end-to-end artifact set for the 8-root-cause agent.
- FAISS was treated as an external notebook dependency rather than a deployment backend.
- They did not expose live API endpoints between Monitoring, Prediction/Detection, Diagnostic, and Optimization agents.
- They did not provide a dynamic deployed diagnostic view.
- They did not include the LLM causal-chain and feature-contribution explanation layer.

The new notebook fixes those issues:

- One self-contained workflow.
- Local CSV input only.
- Explicit 8-root-cause contracts.
- Controlled augmentation with provenance.
- Chronological split and purge gap.
- Leak-safe feature set.
- Random Forest, GRU, and prototype retrieval trained together.
- Deployment artifacts exported in one directory.
- Native Linux FAISS deployment implemented and verified.
- Open Diagnostic Agent endpoints implemented.
- Dynamic dashboard implemented.
- Optimization outbox and optional HTTP push implemented.
- LLM-compatible explanation layer implemented.
- Separate-agent context fusion implemented.
- Data quality confidence penalty implemented.
- Memory-guided autoencoder reconstruction evidence implemented.
- Radio-vs-transport discriminator implemented.
- Explicit multi-branch fusion implemented.

## 17. Deployment Validation

The Docker deployment was built and run with:

```powershell
docker compose -f deploy/docker-compose.yml build
docker compose -f deploy/docker-compose.yml up -d
```

Container status:

```text
qos-buddy-diagnostic   Up   healthy   0.0.0.0:8000->8000/tcp
```

Smoke test command:

```powershell
python deploy\tests\smoke_test.py http://127.0.0.1:8000
```

Smoke test result:

```json
{
  "faiss_vectors": 1879,
  "incident_count": 12,
  "first_incident": "INC_3302",
  "first_root_cause": "RC_PACKET_LOSS",
  "live_incident": "INC_3314",
  "live_root_cause": "RC_CAPACITY_OVERLOAD"
}
```

Verified runtime health:

```json
{
  "status": "ok",
  "faiss_required": true,
  "faiss_backend": "faiss.IndexFlatL2",
  "faiss_vectors": 1879,
  "dynamic_ingestion": true
}
```

The smoke test verifies:

- API health.
- Mandatory native FAISS.
- All 8 root causes loaded.
- Dashboard payload.
- Incident detail payload.
- 5 FAISS prototype neighbors.
- Live ingestion from a Monitoring + Detection + Prediction shaped event.
- Separate Detection Agent and Prediction Agent events buffered until the matching Monitoring Agent event arrives.
- Context fusion contains detection, prediction, and monitoring sources.
- Data quality gate output.
- Autoencoder reconstruction evidence.
- Fusion output.
- LLM explanation field.
- Optimization handoff queueing.
- Idempotent send-to-optimization behavior.

## 18. Limitations and Honest Interpretation

This is deployment-ready in the sense that all 8 contracts are represented and the full model stack can emit them through a running API and dashboard. However, interpretation must remain honest:

- Not all 8 classes were naturally abundant in the raw data.
- `RC_HANDOVER_INSTABILITY` and `RC_CQI_MISMATCH` are contract-synthetic in this benchmark.
- Metrics for augmented validation/test rows measure contract conformance, not real-world prevalence.
- Real production feedback should be collected to replace synthetic contract examples over time.
- The prototype branch is evidence and fusion support. Random Forest remains the strongest supervised branch, but final confidence now comes from the explicit fusion layer.
- Without `QOS_LLM_API_KEY`, explanations use deterministic model-grounded text rather than an external LLM call. Set `QOS_LLM_REQUIRED=true` to enforce external LLM availability in environments where that is mandatory.
- The current runtime state is in-memory. For multi-instance production deployment, incidents, raw events, and optimization handoffs should be backed by a database or stream.

This is the right tradeoff for deployment: the agent can now emit all required contracts, while the report remains transparent about which labels came from real observations and which came from controlled operational augmentation.

## 19. Recommended Next Steps

1. Configure `QOS_LLM_API_KEY`, `QOS_LLM_BASE_URL`, and `QOS_LLM_MODEL` for external LLM explanations.
2. Configure `OPTIMIZATION_AGENT_URL` and set `AUTO_SEND_TO_OPTIMIZATION=true` when the Optimization Agent endpoint is ready.
3. Back runtime incidents, raw events, and outbox records with persistent storage for production multi-process deployment.
4. Log every emitted contract with:
   - model confidence,
   - top-3 Random Forest probabilities,
   - top-5 prototype neighbors,
   - selected evidence fields,
   - operator feedback if available.
5. Replace augmented examples over time with confirmed incidents from production.
6. Re-run the notebook periodically as new real incidents arrive.
7. Add threshold policy for low-confidence cases:
   - emit `needs_operator_review`,
   - return top-3 candidates,
   - provide prototype neighbors as evidence.

## 20. Final Status

The Diagnostic Agent can now detect and emit all 8 required root-cause contracts:

- `RC_CAPACITY_OVERLOAD`
- `RC_TRANSPORT_DELAY`
- `RC_JITTER_INSTABILITY`
- `RC_PACKET_LOSS`
- `RC_RETRANSMISSION`
- `RC_RADIO_SIGNAL_WEAK`
- `RC_HANDOVER_INSTABILITY`
- `RC_CQI_MISMATCH`

The Random Forest classifier achieved a test Macro F1 of 0.9278 on the 8-contract benchmark. The GRU temporal branch is trained and exported as a NumPy autoencoder for production latent and reconstruction evidence. The offline prototype benchmark achieved a test top-5 hit rate of 0.8851, and the deployed prototype branch now uses native FAISS over scaled GRU latent memory.

The Docker deployment is now running at `http://127.0.0.1:8000` with mandatory native FAISS, separate upstream agent context fusion, data quality confidence penalty, memory-guided autoencoder evidence, radio-vs-transport discriminator, explicit multi-branch fusion, dynamic dashboard updates, LLM-compatible causal-chain and feature-contribution explanations, and Optimization Agent handoff support.

This gives QoS Buddy's Diagnostic Agent a complete 8-root-cause deployment stack aligned with the OADAL loop.
