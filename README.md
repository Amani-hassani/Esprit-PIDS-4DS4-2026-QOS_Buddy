# QoS Buddy

QoS Buddy is an AI-assisted network quality-of-service platform. We built it as a multi-agent system that monitors live network conditions, detects anomalies, predicts service risk, diagnoses likely root causes, recommends remediation actions, and produces operational reports.

This repository was developed for the PIDS 4DS4 engineering program at Esprit School of Engineering during the 2025-2026 academic year. The project is organized as a runnable local demo plus the individual agent workspaces used to build and validate the system.

## What We Built

QoS Buddy connects several specialized agents into one network operations workflow:

- Monitoring Agent: collects host, Wi-Fi, router, and QoS telemetry.
- Detection Agent: identifies abnormal network behavior from live metrics.
- Prediction Agent: forecasts QoS degradation and service breach risk.
- Diagnostic Agent: infers likely root causes using model evidence and historical similarity.
- Optimization Agent: recommends remediation actions with policy checks and approvals.
- Reporting Agent: generates operational and executive summaries.
- RAG memory layer: stores incidents, reports, lessons, and context for assistant answers.
- Dashboard and Gateway: expose the user interface, APIs, role-based access, chatbot, and live views.

## Repository Guide

The main runnable stack is under `Deployment/`. The top-level folders provide navigation for the portfolio version of the repository.

```text
.
|-- Deployment/                 Runnable integrated demo and agent workspaces
|-- docs/                       Project guide, architecture, runbook, and artifact notes
|-- notebooks/                  Curated notebooks for model evaluation and reporting
|-- agents/                     Portfolio navigation for agent responsibilities
|-- shared/                     Placeholder for shared schemas, constants, and utilities
|-- data/                       Placeholder for small public samples
|-- scripts/                    Placeholder for repository-level helper scripts
`-- README.md                   Project overview for GitHub visitors
```

For a first review, start with:

1. `docs/PROJECT_GUIDE.md`
2. `docs/ARCHITECTURE.md`
3. `Deployment/qos-buddy/README.md`
4. `docs/RUNBOOK.md`
5. `docs/ARTIFACTS.md`

## Technology Stack

- Frontend: Next.js, React, TypeScript, SvelteKit, React dashboard components.
- Backend: Python, FastAPI, Docker, Docker Compose, Redis, PostgreSQL.
- Authentication: Keycloak with role-based access.
- AI and ML: scikit-learn, XGBoost, Random Forest, GRU, LSTM, autoencoders, FAISS.
- Memory and reporting: ChromaDB, local Ollama, Qwen2.5, MLflow, PDF reporting.
- Monitoring: host collectors, JSONL event streams, iperf3, router and Wi-Fi metrics.

## Run The Local Demo

The current demo targets Windows with Docker Desktop and PowerShell.

Prerequisites:

- Docker Desktop in Linux container mode.
- Python 3.10 or newer on `PATH`.
- PowerShell.
- Ollama installed and running locally.
- Local model available:

```powershell
ollama pull qwen2.5
```

Start the stack from the deployment folder:

```powershell
cd Deployment
Set-ExecutionPolicy -Scope Process Bypass
.\START-HERE.ps1
```

Open the dashboard:

```text
http://localhost:3000
```

Main local services:

| Service | URL |
| --- | --- |
| Dashboard | `http://localhost:3000` |
| Gateway API | `http://localhost:8080` |
| Keycloak | `http://localhost:8081` |
| RAG Service | `http://localhost:8088` |
| Reporting Service | `http://localhost:8089` |
| Jaeger | `http://localhost:16686` |

Demo users are imported into the local Keycloak realm on first startup:

| User | Password | Role |
| --- | --- | --- |
| `noc-exec` | `demo` | NOC Executive |
| `noc-engineer` | `demo` | NOC Engineer |
| `engineer` | `demo` | AI Engineer |
| `admin-noc` | `demo` | Site Admin |

These credentials are for the local demo only.

## Documentation

- `docs/PROJECT_GUIDE.md`: product goal, agent responsibilities, and reviewer path.
- `docs/ARCHITECTURE.md`: event flow, services, data movement, and deployment shape.
- `docs/RUNBOOK.md`: setup, startup, shutdown, health checks, and troubleshooting.
- `docs/ARTIFACTS.md`: why trained models, datasets, notebooks, and reports are committed.
- `Deployment/README_DEPLOYMENT.md`: portable demo package notes.
- `Deployment/README_DEMO_PACKAGE.md`: demo flow and operational checklist.

## Data And Artifacts

This repository intentionally includes selected trained models, notebooks, CSV samples, generated figures, and deployment artifacts. We keep them in Git because this academic demo is designed to be inspectable and runnable without requiring every reviewer to retrain the models first.

Runtime state, real environment files, logs, local databases, Docker volumes, and private credentials should remain untracked. See `docs/ARTIFACTS.md` and `.gitignore` for details.

## Contributors

- Amri Mohamed Aziz
- Hassani Amani
- Darghoumi Nour Elhoude
- Gannouni Nour Elhoude
- Soulaymane Diallo
- Ghassen Saddem

## Acknowledgments

We thank Esprit School of Engineering for the academic framework and project supervision. We also acknowledge the open-source communities behind the monitoring, machine learning, web, and infrastructure tools used in this project.
