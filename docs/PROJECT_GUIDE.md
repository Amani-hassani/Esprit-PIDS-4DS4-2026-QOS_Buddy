# QoS Buddy Project Guide

QoS Buddy is a local AI network assurance platform. We designed it to show how a network operations team can move from raw telemetry to practical decisions: detect what is wrong, predict what may happen next, diagnose why it is happening, recommend a safe action, and communicate the result clearly.

## Review Path

For a quick recruiter review:

1. Read the root `README.md` for the project overview.
2. Read `docs/ARCHITECTURE.md` for the system flow.
3. Open `Deployment/qos-buddy/README.md` for the integrated demo stack.
4. Review the agent READMEs under `Deployment/` for implementation details.
5. Inspect notebooks and reports only if you want model-level evidence.

## Agent Responsibilities

| Agent | Responsibility | Main Evidence |
| --- | --- | --- |
| Monitoring | Collect live QoS, Wi-Fi, router, and host metrics | JSONL streams, CSV samples |
| Detection | Identify anomalies in live QoS signals | Keras model artifacts, FastAPI service |
| Prediction | Forecast service risks and QoS degradation | XGBoost, LSTM, Prophet, MLflow notes |
| Diagnostic | Infer likely root causes | Random Forest, GRU autoencoder, FAISS |
| Optimization | Recommend safe remediation actions | Policy gate, bandit policies, approvals |
| Reporting | Produce operational and executive summaries | Report service and PDF generation |
| RAG Memory | Store incidents and operational context | ChromaDB-backed services |

## What Makes The Project Useful

- It combines live telemetry, ML inference, diagnostics, recommendations, reporting, and memory in one workflow.
- It shows full-stack implementation across Python services, web dashboards, Docker orchestration, and ML artifacts.
- It keeps model and data artifacts available so reviewers can inspect the work without rebuilding every training step.
- It separates demo credentials and `.env.example` files from private runtime configuration.

## Current State

The repository is a portfolio-ready academic demo. The integrated Docker stack is the main runnable product. Individual agent folders preserve the development and validation work that led to the integrated demo.

