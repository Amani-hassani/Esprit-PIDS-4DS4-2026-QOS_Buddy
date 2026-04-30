# 📡 QoS Buddy — Reporting Agent

> **Intelligent QoS Monitoring & Reporting System** — Multi-agent architecture for proactive telecom network supervision.

![Python](https://img.shields.io/badge/Python-3.10+-blue?logo=python)
![Streamlit](https://img.shields.io/badge/Streamlit-App-red?logo=streamlit)
![Ollama](https://img.shields.io/badge/LLM-Phi--3%20Mini%20via%20Ollama-purple)
![ML](https://img.shields.io/badge/ML-Scikit--learn%20%7C%20XGBoost%20%7C%20PyTorch-orange)
![Status](https://img.shields.io/badge/Status-Active-brightgreen)

---

## 🧠 Overview

The **Reporting Agent** is one of six specialized agents in the **QoS Buddy** multi-agent system, dedicated to proactive Quality of Service supervision of telecom networks.

It transforms raw network metrics — latency, jitter, throughput, packet loss, anomaly scores — into **intelligent reports, executive summaries, and actionable recommendations**, using a hybrid engine combining **LLM (Phi-3 Mini via Ollama)**, **Machine Learning**, and **Deep Learning**.

---

## 🏗️ Multi-Agent Architecture

```
QoS Buddy System
├── 🔍 Monitoring Agent     — Real-time QoS data ingestion
├── 🚨 Detection Agent      — Anomaly & issue detection
├── 📈 Prediction Agent     — Performance forecasting
├── 🔎 Diagnostic Agent     — Root cause analysis
├── ⚙️  Optimization Agent   — Optimization recommendations
└── 📊 Reporting Agent      ← THIS REPO
```

---

## ✨ Use Cases (10 implemented)

| # | Use Case | Description |
|---|----------|-------------|
| 1 | **Intelligent Narrative** | Generates structured report: executive summary + technical analysis + immediate recommendation |
| 2 | **Q&A on QoS Data** | Natural language question answering on network metrics |
| 3 | **Root Cause Classification** | Pre-classifies root causes of critical incidents |
| 4 | **Key Insights** | Extracts actionable insights from network KPIs |
| 5 | **DL Explainer** | Explains Deep Learning model predictions in human language |
| 6 | **Tone Adaptation** | Generates the same report in 3 versions: Engineer (SMS) / Manager (Email) / Director (Strategic report) |
| 7 | **Benchmark** | Compares LLM performance across multiple prompting strategies |
| 8 | **Audio Report** | Converts reports to voice audio (MP3) for hands-free consumption |
| 9 | **Digest Email** | Generates automated digest emails with KPI summaries |
| 10 | **Adaptive Narrative** | Dynamic narrative that adapts depth and style to data severity |

---

## 🤖 ML & DL Models

| Model | Task | Output |
|-------|------|--------|
| **Isolation Forest** | Unsupervised anomaly detection on incidents | Anomaly scores + top atypical incidents |
| **Autoencoder (PyTorch)** | Deep anomaly detection on QoS time-series | Reconstruction error + anomaly flags |
| **K-Means** | Incident clustering | Cluster profiles + PCA visualization |
| **XGBoost** | NHS metric forecasting (+1h, +2h, +6h) | Predictive QoS scores with feature importance |

---

## 📊 Data

Network metrics ingested per time-series sample:

- `latency_ms` — Network latency
- `jitter_ms` — Jitter
- `packet_loss_pct` — Packet loss rate
- `throughput_mbps` — Throughput
- `traffic_type` — Traffic type
- `anomaly_type` / `anomaly_score` — Anomaly classification
- `bandwidth_util_pct` — Bandwidth utilization
- Operational KPIs: **MTTD / MTTR**, incident severity

---

## 🗂️ Project Structure

```
reporting-agent/
├── main.py                          # Entry point (CLI)
├── streamlit_app.py                 # Interactive Streamlit dashboard
├── llm_engine.py                    # Ollama / Phi-3 Mini LLM interface
├── data_loader.py                   # Data ingestion (timeseries + incidents)
├── sample_selector.py               # Smart sample selection
├── prompt_builder.py                # Context → prompt formatting
├── analytics.py                     # KPI computation & trend analysis
├── charts.py                        # Plotly visualizations
├── report_export.py                 # PDF/report export (ReportLab)
│
├── usecase_1_narrative.py           # Intelligent narrative generation
├── usecase_2_qa.py                  # Q&A on QoS data
├── usecase_3_root_cause.py          # Root cause classification
├── usecase_4_insights.py            # Key insights extraction
├── usecase_5_dl_explainer.py        # DL model explainability
├── usecase_6_tone_adaptation.py     # Engineer / Manager / Director reports
├── usecase_7_benchmark.py           # LLM prompting benchmark
├── usecase_8_audio_report.py        # Audio report generation (MP3)
├── usecase_9_digest_email.py        # Automated digest emails
├── usecase_10_adaptive_narrative.py # Severity-adaptive narrative
│
├── ml_isolation_forest_pro.py       # Isolation Forest pipeline
├── ml_autoencoder_pro.py            # Autoencoder (PyTorch) pipeline
├── ml_kmeans_pro.py                 # K-Means clustering pipeline
│
├── data/                            # QoS timeseries & incidents (CSV)
└── outputs/                         # Model outputs, plots, audio reports
    ├── isolation_forest_pro/
    ├── autoencoder_pro/
    ├── kmeans_pro/
    ├── xgboost_nhs_pro/
    └── audio_reports/
```

---

## 🚀 Getting Started

### Prerequisites

- Python 3.10+
- [Ollama](https://ollama.ai) installed and running locally
- Phi-3 Mini model pulled:

```bash
ollama pull phi3:mini
```

### Installation

```bash
git clone https://github.com/NourGannouni/qos-buddy.git
cd qos-buddy
pip install -r requirements.txt
```

### Run CLI

```bash
python main.py
```

### Run Streamlit Dashboard

```bash
streamlit run streamlit_app.py
```

---

## 🛠️ Tech Stack

| Category | Tools |
|----------|-------|
| **LLM** | Phi-3 Mini, Ollama |
| **ML** | Scikit-learn, XGBoost, K-Means, Isolation Forest |
| **Deep Learning** | PyTorch (Autoencoder) |
| **Dashboard** | Streamlit, Plotly |
| **Export** | ReportLab (PDF), gTTS (Audio MP3) |
| **Data** | Pandas, NumPy |
| **Dev** | Python 3.10+, Git |

---

## 👩‍💻 Author

**Nour El Houda GANNOUNI**
Student Engineer in Data Science — ESPRIT, Tunis
[LinkedIn](https://www.linkedin.com/in/nourelhouda-gannouni-149a23311/) • [GitHub](https://github.com/NourGannouni)

---

## 📄 License

This project was developed as part of the PIDEV academic project at ESPRIT (2025–2026).