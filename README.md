# QoS Buddy

## Overview
QoS Buddy is an AI-powered multi-agent platform for network Quality of Service monitoring, diagnosis, prediction, optimization, and reporting.

This project was developed as part of the **PIDS – 4DS4 Engineering Program** at **Esprit School of Engineering** (Academic Year **2025–2026**).

QoS Buddy helps network operations teams monitor live QoS signals, detect abnormal behavior, forecast service degradation, diagnose likely root causes, recommend remediation actions, and preserve operational knowledge through incident memory and AI-assisted reporting.

## Features
- Real-time collection of network and system QoS indicators such as latency, jitter, packet loss, throughput, CPU usage, active connections, and Wi-Fi signal quality
- Live monitoring dashboard with role-based access for operators, engineers, executives, and administrators
- Anomaly detection for abnormal network behavior
- Prediction and forecasting of QoS degradation and potential service breaches
- Diagnostic agent for root-cause analysis of incidents using AI and historical similarity retrieval
- Optimization engine for remediation recommendations and policy-aware decision support
- Incident memory and RAG support using ChromaDB
- AI chatbot for questions related to live network status, incidents, diagnostics, and reports
- Executive and operational reporting with business-oriented insights, KPI trends, MTTD, MTTR, and post-mortem support
- Authentication and authorization using Keycloak

## Tech Stack

### Frontend
- Next.js
- TypeScript
- Dashboard UI

### Backend
- Python
- FastAPI
- Redis
- PostgreSQL
- Docker
- Docker Compose
- MLflow
- ChromaDB
- Keycloak
- Ollama
- Qwen2.5

### AI / Data / Monitoring
- Scikit-learn
- XGBoost
- Random Forest
- GRU
- LSTM
- Autoencoders
- FAISS
- Time-Series Analysis
- iperf3

## Architecture
QoS Buddy follows a multi-agent architecture where each component plays a dedicated role in the QoS assurance pipeline:

- **Monitoring Agent**: collects and structures live telemetry from the host and network environment
- **Detection Agent**: identifies anomalies from real-time QoS metrics
- **Prediction Agent**: forecasts future QoS degradation and risk of breach
- **Diagnostic Agent**: analyzes incidents and infers likely root causes
- **Optimization Agent**: recommends remediation actions with policy-aware decision support
- - **Reporting Agent**: generates executive and operational reports
- **RAG / Memory Layer**: stores incidents, reports, and operational knowledge using ChromaDB
- **Gateway and Dashboard**: expose APIs, live views, chatbot features, and role-based access

## Contributors
- Amri Mohamed Aziz
- Hassani Amani
- Darghoumi Nour Elhoude
- Gannouni Nour Elhoude
- Soulaymane Diallo
- Ghassen Saddem

## Academic Context
Developed at **Esprit School of Engineering – Tunisia**  
**PIDS – 4DS4 | Academic Year 2025–2026**

This project was carried out as an academic engineering project focused on applying artificial intelligence, multi-agent systems, and software engineering practices to real-world network QoS management problems.

## Getting Started

### Prerequisites
- Docker Desktop
- Python 3.10+
- Ollama installed locally
- `qwen2.5` model available locally

### Run the Project
From the project root:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\START-HERE.ps1
