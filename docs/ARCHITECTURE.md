# Architecture

QoS Buddy uses a multi-agent architecture. Each service owns one part of the network assurance workflow, and the integrated deployment connects them through Docker Compose, Redis streams, HTTP APIs, and shared operational memory.

## High-Level Flow

```text
Host / router / Wi-Fi metrics
        |
        v
Monitoring collector
        |
        v
JSONL event stream -> Redis streams
        |
        +--> Detection Agent
        +--> Prediction Agent
        +--> Diagnostic Agent
        +--> Optimization Agent
        +--> RAG memory and Reporting
        |
        v
Gateway API -> Dashboard, chatbot, reports, approvals, audit views
```

## Integrated Deployment

The runnable stack lives in `Deployment/qos-buddy/`.

Main services:

| Service | Purpose |
| --- | --- |
| `shell` | Next.js dashboard |
| `gateway` | API gateway, authentication integration, live data routing |
| `redis` | Event stream and coordination layer |
| `postgres` | Relational persistence for platform services |
| `keycloak` | Local role-based access control |
| `rag` | ChromaDB-backed incident and knowledge memory |
| `reporting` | Executive and operational report generation |
| `synthesis` | Incident summaries and recommendation narratives |
| `monitoring` | Bridge from host telemetry into the platform |
| `detection` | Real-time anomaly detection service |
| `prediction` | Risk forecasting service |
| `diagnostic` | Root-cause inference service |
| `optimization` | Policy-aware remediation recommendation service |

## Data Movement

The monitoring collector writes live samples to `Deployment/monitoring/network_stream.jsonl` during runtime. The Docker monitoring bridge tails this stream and publishes normalized events. Downstream agents enrich the events with anomaly, prediction, diagnostic, and optimization outputs. The gateway and dashboard expose the latest operational state to users.

## AI And Memory

The stack uses local-first AI by default:

- Ollama serves the local language model through `host.docker.internal:11434`.
- ChromaDB stores incident memory, runbook context, reports, and live operational memory.
- MLflow is used by selected agents for experiment and trace visibility.
- FAISS and trained model artifacts are packaged where needed for diagnostic and prediction workloads.

## Security Model

The demo uses Keycloak for browser authentication and role-based access. Demo users are intentionally included for local evaluation. Real secrets must be configured through local `.env` files and must not be committed.

