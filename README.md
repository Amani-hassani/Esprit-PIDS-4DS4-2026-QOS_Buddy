# QoS Buddy — Event-Driven Multi-Agent System for Proactive QoS Management

## Overview

QoS Buddy is a multi-agent system for proactive Quality of Service (QoS) management in telecommunication networks. Its purpose is to transform raw network monitoring into anomaly detection, risk prediction, root-cause diagnosis, optimization recommendations, and structured reporting. The architecture is organized around four major blocks: **Data Sources Layer**, **Data Preparation Layer**, **AI Agent Layer**, and **Control Layer**. The AI layer contains six specialized agents, while orchestration and governance are handled outside the AI layer by a deterministic **Workflow Engine** and a **Policy & Safety Gate**.

## Features

- Multi-agent telecom QoS analysis pipeline
- Real-time and batch-oriented KPI monitoring
- Anomaly detection and severity scoring
- Risk prediction for future SLA degradation
- Root-cause diagnosis with explainability-oriented design
- Optimization proposal generation
- Reporting and documentation support
- Event-driven coordination through a deterministic workflow layer
- Human-in-the-loop approval for critical actions
- Repository structured for modular collaboration across six team members

## Tech Stack

### Frontend
- Dashboard / visualization layer (to be finalized by the Reporting/Dashboard workstream)

### Backend
- Python-based agents and orchestration components
- Event-driven workflow logic
- Local and server-side execution depending on deployment target

### Data / Storage
- Time-series and structured operational data stores depending on implementation maturity
- File storage for reports, artifacts, and model outputs

### ML / AI
- Statistical detection
- Time-series forecasting
- Root-cause analysis
- Optimization logic
- Reporting / summarization support


## Architecture

QoS Buddy follows an **event-driven multi-agent architecture** with clear separation between intelligence and control. The system is built around three main ideas: **separation of intelligence and control**, **event-driven coordination**, and **enterprise-grade safety and governance**. The six specialized AI agents provide analytical intelligence, while the **Workflow Engine** provides deterministic control and the **Policy & Safety Gate** enforces validation and human approval where needed.

### High-Level Flow

**Monitoring → Detection → Prediction / Diagnostic → Optimization → Reporting**

This collaboration is aligned with the **OADAL** cycle:

**Observe → Analyze → Decide → Act → Learn**

### Main Architectural Blocks

1. **Data Sources Layer**  
   Raw operational inputs such as network KPIs, alarms, incident logs, topology, and configuration metadata. 

2. **Data Preparation Layer**  
   Cleaning, normalization, feature extraction, aggregation, and context enrichment before AI processing.

3. **AI Agent Layer**  
   Six specialized agents:
   - Monitoring Agent
   - Detection Agent
   - Prediction Agent
   - Diagnostic Agent
   - Optimization Agent
   - Reporting Agent

4. **Control Layer**  
   Non-agent orchestration and governance components:
   - Workflow Engine
   - Policy & Safety Gate
   - Event Bus
   - Human Approval Queue

## Repository Structure

This repository is organized as a **monorepo** so that all agents, shared assets, documentation, experiments, and control-layer components remain in one coherent project.

```text
qos-buddy/
├── README.md
├── .gitignore
├── docs/
│   ├── architecture/
│   ├── reports/
│   └── roadmap/
├── agents/
│   ├── monitoring-agent/
│   ├── detection-agent/
│   ├── prediction-agent/
│   ├── diagnostic-agent/
│   ├── optimization-agent/
│   └── reporting-agent/
├── control/
│   ├── workflow-engine/
│   ├── policy-safety-gate/
│   ├── event-bus/
│   └── approval-queue/
├── shared/
│   ├── schemas/
│   ├── configs/
│   ├── constants/
│   └── utils/
├── notebooks/
│   ├── detection/
│   ├── prediction/
│   ├── diagnostic/
│   └── experiments/
├── data/
│   ├── samples/
│   └── references/
└── scripts/
```

## Detailed Role of Every Folder and Key File

### Root files

#### `README.md`
Main repository entry point. It explains the project, architecture, repository structure, collaboration model, and setup guidance.

#### `.gitignore`
Defines which files must **not** be tracked in Git, such as local environments, logs, secrets, caches, generated artifacts, and large local-only data files.

---

### `docs/`
Documentation space for project-wide written material.

#### `docs/architecture/`
Contains architecture references and diagrams for the full QoS Buddy platform.  
Typical contents:
- global architecture proposal
- agent interaction diagrams
- deployment diagrams
- workflow/control-layer diagrams

#### `docs/reports/`
Contains project reports, formal writeups, milestone documents, and professor-facing material.

#### `docs/roadmap/`
Contains planning material:
- phase plans
- sprint plans
- integration milestones
- project timelines

---

### `agents/`
This folder contains the six specialized AI agents of the system. These agents provide **intelligence**, not orchestration.

#### `agents/monitoring-agent/`
Tracks network health and maintains KPI state snapshots.  
Typical responsibilities:
- ingest raw QoS metrics
- maintain state snapshots
- package monitoring outputs for downstream use

#### `agents/detection-agent/`
Detects abnormal KPI behavior and emits anomaly events.  
Typical responsibilities:
- anomaly scoring
- severity estimation
- event creation for the workflow engine

#### `agents/prediction-agent/`
Forecasts future KPI behavior and SLA risk.  
Typical responsibilities:
- short-term time-series prediction
- risk scoring
- future degradation warnings

#### `agents/diagnostic-agent/`
Determines the probable root cause of degradation and explains why it happened.  
Typical responsibilities:
- deterministic preprocessing
- root-cause ranking
- evidence generation
- later, model-based diagnosis and explainability

#### `agents/optimization-agent/`
Generates and ranks corrective actions.  
Typical responsibilities:
- action proposal
- expected impact estimation
- fallback rule logic
- later optimization learning

#### `agents/reporting-agent/`
Transforms system outcomes into structured human-readable reports.  
Typical responsibilities:
- summaries
- technical reports
- pre/post-action analysis
- lessons learned documentation


---

### `control/`
This folder contains the **control layer**, which is distinct from the AI agents. The architecture report explicitly states that orchestration should be handled by a deterministic backend system, not by an AI agent. 

#### `control/workflow-engine/`
Holds the deterministic orchestration logic of QoS Buddy.  
Typical responsibilities:
- event routing
- workflow execution
- retries
- timeouts
- state persistence
- audit logging

#### `control/policy-safety-gate/`
Holds the validation/governance layer for proposed actions.  
Typical responsibilities:
- risk checks
- impact checks
- rollback validation
- change-window checks
- decision outcome generation:
  - approved
  - pending approval
  - rejected
  - deferred

#### `control/event-bus/`
Holds abstractions, contracts, or implementation code for event exchange between agents and control components.

#### `control/approval-queue/`
Holds human-in-the-loop approval flow logic and related models/interfaces.

---

### `shared/`
Shared assets reused across multiple agents and/or control components.

#### `shared/schemas/`
Shared request/response schemas, event schemas, payload contracts, and common data models.

#### `shared/configs/`
Shared configuration templates or common config files used across components.

#### `shared/constants/`
Centralized constants such as:
- event names
- enum-like constant values
- global thresholds shared across modules
- common labels or identifiers

#### `shared/utils/`
Reusable helper functions and utilities shared across the project.

---

### `notebooks/`
Notebook workspace for experimentation, exploratory work, and training pipelines.

#### `notebooks/detection/`
Detection-focused experiments and anomaly-model notebooks.

#### `notebooks/prediction/`
Prediction-focused experiments and time-series forecasting notebooks.

#### `notebooks/diagnostic/`
Diagnostic-focused experiments, feature studies, and root-cause analysis notebooks.

#### `notebooks/experiments/`
Cross-agent or general experiments that do not belong to a single agent-specific folder.

---

### `data/`
Lightweight repository-safe data assets only.

#### `data/samples/`
Small example files for demonstration, schema checks, or safe toy inputs.

#### `data/references/`
Static reference material such as:
- field dictionaries
- label mappings
- scenario descriptions
- safe metadata tables

---

### `scripts/`
Reusable project-level helper scripts.

Typical examples:
- environment setup helpers
- data organization helpers
- repo maintenance scripts
- lightweight integration scripts

## Contributors

- Monitoring Agent — [Ghassen Saddem]
- Detection Agent — [Soulaymane Diallo]
- Prediction Agent — [Nour El Houda Darghoumi]
- Diagnostic Agent — [Mohamed Aziz Amri]
- Optimization Agent — [Amani Hassani]
- Reporting Agent — [Nour El Houda Gannouni]

## Academic Context

This project was developed at **Esprit School of Engineering – Tunisia** as an academic engineering project. The GitHub standardization guide requires public repositories to use the Esprit naming/branding conventions, to include a structured README, and to use repository descriptions and topics aligned with the academic context. In particular, public repositories should include wording such as **“Developed at Esprit School of Engineering – Tunisia”**, the academic year, and the main technologies. The required minimum README structure also includes sections such as Overview, Features, Tech Stack, Architecture, Contributors, Academic Context, Getting Started, and Acknowledgments.

### Repository publication note
The current repository can remain private during setup and integration. Before public publication, verify:
- repository naming convention
- description format
- topics
- README structure
- public visibility requirements.

## Getting Started

### 1. Clone the repository
```bash
git clone https://github.com/AzizX25/qos-buddy.git
cd qos-buddy
```

### 2. Switch to your assigned branch
```bash
git fetch origin
git checkout -b agent/YOUR-AGENT origin/agent/YOUR-AGENT
```

Examples:
```bash
git checkout -b agent/diagnostic origin/agent/diagnostic
git checkout -b agent/prediction origin/agent/prediction
```

### 3. Work only inside your assigned agent folder
Each team member should place their work only inside the appropriate folder under `agents/`.

### 4. Push changes to your own branch
```bash
git add .
git commit -m "Initial integration of [agent name]"
git push
```

### Team rules
- Do not push directly to `main`
- Do not modify another agent’s folder without coordination
- Do not commit secrets, passwords, `.env`, logs, or local environments
- Keep folder names, filenames, and commit messages clean and consistent

## Repository Metadata for Public Publication

According to the Esprit GitHub standardization document, public repositories should follow:

### Naming convention
`Esprit-[PI]-[Classe]-[AU]-[NomDuProjet]`

### Public repository description should include
- Developed at Esprit School of Engineering – Tunisia
- Academic year
- Main technologies used

### Minimum required topics
- `esprit-school-of-engineering`
- `academic-project`
- `esprit-[PI]`
- academic year
- main technology fileciteturn40file0

## Acknowledgments

- Esprit School of Engineering – Tunisia
- QoS Buddy project team
- Academic supervisors and tutors
- Contributors to each specialized agent and control-layer component
