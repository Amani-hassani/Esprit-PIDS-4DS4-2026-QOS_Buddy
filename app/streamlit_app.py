"""Streamlit NOC dashboard for QoS prediction and incident intelligence."""

from __future__ import annotations

import io
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components
from plotly.subplots import make_subplots

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.prediction_agent import PredictionAgent
from agent.terminal_report import print_prediction_terminal_summary
from config import LSTM_WINDOW
from data_pipeline.loader import apply_incidents_schema_cleaning, apply_qos_schema_cleaning
from models.prophet_forecaster import ProphetForecaster
from rag.incident_store import IncidentStore

UI_CHROMA_DIR = ROOT / "rag" / "chroma_streamlit_ui"
TARGET_ORDER = [
    "call_drop_risk",
    "latency_breach_risk",
    "throughput_risk",
    "jitter_risk",
    "congestion_risk",
    "mos_risk",
]
SEVERITY_STYLE = {
    "normal": {"bg": "#0f8a42", "label": "NORMAL", "class": ""},
    "watch": {"bg": "#1d4ed8", "label": "WATCH", "class": ""},
    "warning": {"bg": "#ea580c", "label": "WARNING", "class": ""},
    "high": {"bg": "#b91c1c", "label": "HIGH", "class": ""},
    "critical": {"bg": "#7f1d1d", "label": "CRITICAL", "class": "critical-pulse"},
    "unknown": {"bg": "#475569", "label": "UNKNOWN", "class": ""},
}


def _inject_css() -> None:
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&family=IBM+Plex+Sans:wght@300;400;500;600;700&display=swap');

    :root {
        --bg:        #05080f;
        --bg2:       #090d18;
        --bg3:       #0e1524;
        --border:    rgba(148,163,184,0.12);
        --border2:   rgba(148,163,184,0.22);
        --text:      #e2e8f0;
        --text2:     #94a3b8;
        --text3:     #4b5a6e;
        --mono:      'JetBrains Mono', monospace;
        --sans:      'IBM Plex Sans', sans-serif;
        --green:     #22c55e;
        --blue:      #3b82f6;
        --amber:     #f59e0b;
        --red:       #ef4444;
        --crimson:   #dc2626;
        --cyan:      #06b6d4;
    }

    /* BASE */
    .stApp { background: var(--bg) !important; font-family: var(--sans); }
    html, body { background: var(--bg) !important; }

    /* HEADER */
    .noc-header {
        background: linear-gradient(135deg, #070e1f 0%, #0b1830 60%, #0d2040 100%);
        border: 1px solid rgba(59,130,246,0.2);
        border-radius: 6px;
        padding: 1rem 1.25rem;
        margin-bottom: 1.25rem;
        display: flex;
        align-items: center;
        justify-content: space-between;
        flex-wrap: wrap;
        gap: 0.75rem;
    }
    .noc-title {
        font-family: var(--mono);
        font-size: 1.1rem;
        font-weight: 700;
        color: #f8fafc;
        letter-spacing: 0.06em;
        text-transform: uppercase;
        margin: 0;
    }
    .noc-subtitle {
        font-size: 0.72rem;
        color: var(--text3);
        font-family: var(--mono);
        letter-spacing: 0.04em;
        margin-top: 2px;
    }
    .live-badge {
        display: inline-flex;
        align-items: center;
        gap: 0.4rem;
        font-family: var(--mono);
        font-size: 0.72rem;
        font-weight: 700;
        color: #fca5a5;
        background: rgba(220,38,38,0.15);
        border: 1px solid rgba(239,68,68,0.35);
        border-radius: 4px;
        padding: 0.25rem 0.6rem;
        letter-spacing: 0.08em;
    }
    .live-dot {
        width: 7px; height: 7px;
        border-radius: 50%;
        background: #ef4444;
        box-shadow: 0 0 0 0 rgba(239,68,68,0.8);
        animation: pulseDot 1.4s infinite;
    }
    .clock-chip {
        font-family: var(--mono);
        font-size: 0.78rem;
        color: #93c5fd;
        background: rgba(30,58,138,0.25);
        border: 1px solid rgba(59,130,246,0.22);
        border-radius: 4px;
        padding: 0.2rem 0.55rem;
    }

    /* GLASS PANEL */
    .panel {
        background: linear-gradient(160deg, rgba(9,15,28,0.92), rgba(12,20,36,0.95));
        border: 1px solid var(--border);
        border-radius: 6px;
        padding: 0.9rem 1rem;
        backdrop-filter: blur(8px);
        box-shadow: 0 4px 16px rgba(0,0,0,0.4);
    }
    .panel-label {
        font-family: var(--mono);
        font-size: 0.68rem;
        font-weight: 700;
        letter-spacing: 0.1em;
        text-transform: uppercase;
        color: var(--text3);
        margin-bottom: 0.4rem;
    }

    /* ALERT CARD */
    .alert-card {
        border-radius: 6px;
        border: 1px solid;
        overflow: hidden;
        margin-bottom: 1.25rem;
        font-family: var(--sans);
    }
    .alert-card-header {
        padding: 0.9rem 1rem;
        border-bottom: 1px solid rgba(148,163,184,0.1);
        display: flex;
        align-items: center;
        justify-content: space-between;
        flex-wrap: wrap;
        gap: 0.75rem;
    }
    .alert-metric-name {
        font-family: var(--mono);
        font-size: 1.25rem;
        font-weight: 700;
        letter-spacing: 0.04em;
        color: #f8fafc;
    }
    .alert-card-body { padding: 0.9rem 1rem; }
    .alert-badge {
        font-family: var(--mono);
        font-size: 0.68rem;
        font-weight: 700;
        letter-spacing: 0.1em;
        text-transform: uppercase;
        padding: 0.2rem 0.55rem;
        border-radius: 3px;
        border: 1px solid;
    }
    .conf-number {
        font-family: var(--mono);
        font-size: 2rem;
        font-weight: 700;
        line-height: 1;
    }
    .eta-number {
        font-family: var(--mono);
        font-size: 1.3rem;
        font-weight: 700;
        line-height: 1;
    }

    /* TOASTS */
    .toast-container {
        display: flex;
        flex-direction: column;
        gap: 0.5rem;
    }
    .toast {
        border-radius: 5px;
        border-left: 3px solid;
        padding: 0.65rem 0.85rem;
        background: rgba(9,15,28,0.92);
        display: flex;
        flex-direction: column;
        gap: 0.25rem;
        transition: all 0.2s;
        cursor: default;
        position: relative;
        overflow: hidden;
    }
    .toast::before {
        content: '';
        position: absolute;
        top: 0; left: 0; right: 0;
        height: 1px;
        background: linear-gradient(90deg, transparent, rgba(255,255,255,0.06), transparent);
    }
    .toast-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 0.5rem;
    }
    .toast-title {
        font-family: var(--mono);
        font-size: 0.78rem;
        font-weight: 700;
        letter-spacing: 0.04em;
        color: #f1f5f9;
    }
    .toast-meta {
        font-family: var(--mono);
        font-size: 0.68rem;
        color: var(--text3);
        letter-spacing: 0.03em;
    }
    .toast-body {
        font-size: 0.82rem;
        color: var(--text2);
        line-height: 1.5;
    }
    .toast-tag {
        font-family: var(--mono);
        font-size: 0.64rem;
        font-weight: 700;
        letter-spacing: 0.06em;
        padding: 0.12rem 0.4rem;
        border-radius: 2px;
        text-transform: uppercase;
    }

    /* LLM TERMINAL */
    .llm-terminal {
        background: #030508;
        border: 1px solid rgba(34,197,94,0.25);
        border-radius: 6px;
        padding: 0;
        overflow: hidden;
        font-family: var(--mono);
    }
    .llm-terminal-bar {
        background: rgba(15,25,40,0.95);
        border-bottom: 1px solid rgba(34,197,94,0.2);
        padding: 0.45rem 0.75rem;
        display: flex;
        align-items: center;
        gap: 0.5rem;
    }
    .llm-terminal-dot {
        width: 8px; height: 8px;
        border-radius: 50%;
    }
    .llm-terminal-label {
        font-size: 0.7rem;
        font-weight: 700;
        color: rgba(34,197,94,0.7);
        letter-spacing: 0.08em;
        text-transform: uppercase;
    }
    .llm-terminal-body {
        padding: 1rem;
        font-size: 0.82rem;
        color: #86efac;
        line-height: 1.65;
        white-space: pre-wrap;
        min-height: 120px;
    }

    /* SHAP BAR */
    .shap-row {
        display: flex;
        align-items: center;
        gap: 0.6rem;
        margin-bottom: 0.5rem;
    }
    .shap-label {
        font-family: var(--mono);
        font-size: 0.75rem;
        color: var(--text2);
        width: 220px;
        flex-shrink: 0;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }
    .shap-bar-track {
        flex: 1;
        height: 8px;
        background: rgba(255,255,255,0.06);
        border-radius: 2px;
        overflow: hidden;
    }
    .shap-bar-fill {
        height: 100%;
        border-radius: 2px;
        transition: width 0.6s ease;
    }
    .shap-value {
        font-family: var(--mono);
        font-size: 0.72rem;
        color: var(--text3);
        width: 72px;
        text-align: right;
        flex-shrink: 0;
    }

    /* RISK GRID */
    .risk-grid {
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        gap: 0.6rem;
        margin-bottom: 1rem;
    }
    .risk-cell {
        background: rgba(9,15,28,0.9);
        border: 1px solid var(--border);
        border-radius: 5px;
        padding: 0.65rem 0.75rem;
        border-top: 2px solid;
        transition: border-color 0.3s;
    }
    .risk-cell-name {
        font-family: var(--mono);
        font-size: 0.65rem;
        font-weight: 700;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: var(--text3);
        margin-bottom: 0.35rem;
    }
    .risk-cell-value {
        font-family: var(--mono);
        font-size: 1.45rem;
        font-weight: 700;
        line-height: 1;
    }
    .risk-cell-bar {
        height: 3px;
        border-radius: 1px;
        margin-top: 0.45rem;
    }

    /* SEVERITY */
    .sev-banner {
        padding: 0.6rem 1rem;
        border-radius: 5px;
        border: 1px solid;
        display: flex;
        align-items: center;
        gap: 0.75rem;
        margin-bottom: 1rem;
    }
    .sev-label {
        font-family: var(--mono);
        font-size: 1.2rem;
        font-weight: 700;
        letter-spacing: 0.08em;
    }
    .sev-sub {
        font-family: var(--mono);
        font-size: 0.72rem;
        color: rgba(255,255,255,0.55);
        letter-spacing: 0.04em;
    }

    /* DOWNLOAD */
    .download-row {
        display: flex;
        gap: 0.5rem;
        flex-wrap: wrap;
        margin: 0.75rem 0;
    }

    /* SECTION HEADER */
    .section-hdr {
        font-family: var(--mono);
        font-size: 0.72rem;
        font-weight: 700;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        color: var(--text3);
        padding: 0.35rem 0;
        border-bottom: 1px solid var(--border);
        margin-bottom: 0.85rem;
        display: flex;
        align-items: center;
        gap: 0.5rem;
    }
    .section-hdr-dot {
        width: 5px; height: 5px;
        border-radius: 50%;
    }

    /* ETA CARD */
    .eta-card {
        background: rgba(9,15,28,0.9);
        border: 1px solid var(--border);
        border-radius: 6px;
        padding: 0.85rem 1rem;
        display: flex;
        align-items: center;
        justify-content: space-between;
        flex-wrap: wrap;
        gap: 1rem;
        margin-bottom: 1rem;
    }
    .eta-left { display: flex; flex-direction: column; gap: 0.2rem; }
    .eta-value {
        font-family: var(--mono);
        font-size: 2.2rem;
        font-weight: 700;
        line-height: 1;
    }
    .eta-sublabel {
        font-family: var(--mono);
        font-size: 0.68rem;
        color: var(--text3);
        letter-spacing: 0.06em;
        text-transform: uppercase;
    }
    .eta-reason {
        font-size: 0.78rem;
        color: var(--text2);
        max-width: 380px;
        line-height: 1.5;
    }
    .eta-detail-pill {
        font-family: var(--mono);
        font-size: 0.68rem;
        color: var(--text3);
        background: rgba(255,255,255,0.04);
        border: 1px solid var(--border);
        border-radius: 3px;
        padding: 0.15rem 0.45rem;
        display: inline-block;
        margin: 0.15rem 0.15rem 0 0;
    }

    /* METRIC OVERRIDES */
    div[data-testid="stMetricValue"] {
        font-family: var(--mono) !important;
        font-size: 1.6rem !important;
        font-weight: 700 !important;
        color: #f8fafc !important;
    }
    div[data-testid="stMetricLabel"] {
        font-family: var(--mono) !important;
        font-size: 0.7rem !important;
        font-weight: 700 !important;
        letter-spacing: 0.06em !important;
        text-transform: uppercase !important;
        color: var(--text3) !important;
    }

    /* SIDEBAR */
    section[data-testid="stSidebar"] {
        background: var(--bg2) !important;
        border-right: 1px solid var(--border) !important;
    }
    section[data-testid="stSidebar"] .stButton button {
        font-family: var(--mono) !important;
        font-weight: 700 !important;
        letter-spacing: 0.04em !important;
    }

    /* TABS */
    .stTabs [data-baseweb="tab"] {
        font-family: var(--mono) !important;
        font-size: 0.75rem !important;
        font-weight: 700 !important;
        letter-spacing: 0.06em !important;
        text-transform: uppercase !important;
        color: var(--text3) !important;
    }
    .stTabs [aria-selected="true"] {
        color: var(--cyan) !important;
        border-bottom-color: var(--cyan) !important;
    }

    /* EXPANDER */
    .stExpander {
        border: 1px solid var(--border) !important;
        border-radius: 5px !important;
        background: rgba(9,15,28,0.85) !important;
    }
    .stExpander summary {
        font-family: var(--mono) !important;
        font-size: 0.8rem !important;
        font-weight: 700 !important;
        color: var(--text2) !important;
        letter-spacing: 0.04em !important;
    }

    /* FOOTER */
    .noc-footer {
        margin-top: 1.5rem;
        padding: 0.65rem 1rem;
        border-top: 1px solid var(--border);
        display: flex;
        align-items: center;
        justify-content: space-between;
        flex-wrap: wrap;
        gap: 0.5rem;
    }
    .footer-text {
        font-family: var(--mono);
        font-size: 0.68rem;
        color: var(--text3);
        letter-spacing: 0.04em;
    }

    /* ANIMATIONS */
    @keyframes pulseDot {
        0%   { box-shadow: 0 0 0 0 rgba(239,68,68,0.8); }
        70%  { box-shadow: 0 0 0 8px rgba(239,68,68,0); }
        100% { box-shadow: 0 0 0 0 rgba(239,68,68,0); }
    }
    @keyframes criticalRing {
        0%   { box-shadow: 0 0 0 0 rgba(220,38,38,0.7), 0 0 0 0 rgba(220,38,38,0.4); }
        50%  { box-shadow: 0 0 0 6px rgba(220,38,38,0), 0 0 0 12px rgba(220,38,38,0); }
        100% { box-shadow: 0 0 0 0 rgba(220,38,38,0.7), 0 0 0 0 rgba(220,38,38,0.4); }
    }
    @keyframes slideIn {
        from { opacity: 0; transform: translateY(-6px); }
        to   { opacity: 1; transform: translateY(0); }
    }
    .animate-in { animation: slideIn 0.35s ease forwards; }

    /* STATUS BADGES */
    .status-badge {
        font-family: var(--mono);
        font-size: 0.65rem;
        font-weight: 700;
        letter-spacing: 0.06em;
        padding: 0.15rem 0.45rem;
        border-radius: 3px;
        border: 1px solid;
        display: inline-block;
        margin: 0.1rem 0.15rem 0.1rem 0;
        text-transform: uppercase;
    }
    .badge-ok      { background: rgba(22,163,74,0.15); color: #86efac; border-color: rgba(74,222,128,0.35); }
    .badge-missing { background: rgba(220,38,38,0.15); color: #fca5a5; border-color: rgba(248,113,113,0.4); }
    </style>
    """, unsafe_allow_html=True)


def _init_session_state() -> None:
    defaults: dict[str, Any] = {
        "raw_df": pd.DataFrame(),
        "inc_df": pd.DataFrame(),
        "prediction_result": None,
        "last_prediction_timestamp": None,
        "selected_node": None,
        "selected_node_rows": 0,
        "llm_backend": "ollama",
        "last_feature_row": {},
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def _load_qos_from_uploads(files: list) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for f in files:
        raw = pd.read_csv(io.BytesIO(f.getvalue()))
        if not raw.empty:
            frames.append(raw)
    if not frames:
        return pd.DataFrame()
    return apply_qos_schema_cleaning(pd.concat(frames, ignore_index=True))


def _load_incidents_from_uploads(files: list) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for f in files:
        raw = pd.read_csv(io.BytesIO(f.getvalue()))
        if not raw.empty:
            frames.append(raw)
    if not frames:
        return pd.DataFrame()
    return apply_incidents_schema_cleaning(pd.concat(frames, ignore_index=True))


def _build_incident_store(incident_df: pd.DataFrame) -> IncidentStore:
    UI_CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    store = IncidentStore(persist_dir=UI_CHROMA_DIR, collection_name="streamlit_ui_incidents")
    if not incident_df.empty:
        store.ingest(incident_df, replace=True)
    return store


def _clean_target_name(name: str) -> str:
    cleaned = name.replace("_risk", "").replace("_", " ").strip()
    return f"{cleaned.title()} Risk"


def _gauge_band_color(score: float) -> str:
    if score < 0.30:
        return "#16a34a"
    if score < 0.50:
        return "#f59e0b"
    if score < 0.70:
        return "#f97316"
    return "#dc2626"


def _render_header() -> None:
    now_txt = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d  %H:%M:%S  %Z")
    st.markdown(f"""
    <div class="noc-header">
        <div>
            <div class="noc-title">▣ QoS Prediction Agent</div>
            <div class="noc-subtitle">NOC Dashboard  ·  XGBoost + LSTM + Prophet  ·  SHAP + RAG + LLM</div>
        </div>
        <div style="display:flex;align-items:center;gap:0.75rem;flex-wrap:wrap;">
            <span class="clock-chip">{now_txt}</span>
            <span class="live-badge"><span class="live-dot"></span>LIVE</span>
        </div>
    </div>
    """, unsafe_allow_html=True)


def _model_artifact_badges(model_dir: Path) -> str:
    required = [
        "preprocessor.joblib",
        "lstm_qos.pt",
        "xgb_feature_columns.joblib",
        *[f"xgb_{t}_calibrated.joblib" for t in TARGET_ORDER],
    ]
    badges: list[str] = []
    for fn in required:
        exists = (model_dir / fn).exists()
        cls = "badge-ok" if exists else "badge-missing"
        prefix = "OK" if exists else "MISSING"
        badges.append(f"<span class='status-badge {cls}'>{prefix}: {fn}</span>")

    prophet_files = sorted(model_dir.glob("prophet_*.json"))
    if prophet_files:
        badges.append(
            f"<span class='status-badge badge-ok'>OK: Prophet models ({len(prophet_files)}) for ETA</span>"
        )
    else:
        badges.append(
            "<span class='status-badge badge-missing'>MISSING: Prophet model (*.json) - ETA may default to no crossing</span>"
        )

    return "".join(badges)


def _render_severity_banner(severity: str, max_risk: float) -> None:
    cfg = SEVERITY_STYLE.get(severity, SEVERITY_STYLE["unknown"])
    color = cfg["bg"]
    label = cfg["label"]
    is_critical = severity == "critical"
    ring_style = "animation: criticalRing 1.2s infinite;" if is_critical else ""
    st.markdown(f"""
    <div class="sev-banner animate-in"
         style="border-color:{color}40;background:{color}12;{ring_style}">
        <div style="width:10px;height:10px;border-radius:50%;
                    background:{color};flex-shrink:0;
                    {'animation:criticalRing 1.2s infinite;' if is_critical else ''}">
        </div>
        <div>
            <div class="sev-label" style="color:{color}">{label}</div>
            <div class="sev-sub">MAX ENSEMBLE RISK: {max_risk:.1%}  ·  SEVERITY LEVEL {['NORMAL','WATCH','WARNING','HIGH','CRITICAL','UNKNOWN'].index(label) if label in ['NORMAL','WATCH','WARNING','HIGH','CRITICAL','UNKNOWN'] else '?'}/5</div>
        </div>
    </div>
    """, unsafe_allow_html=True)


def _format_metric_name(metric: str) -> str:
    """Convert 'latency_breach_risk' → 'LATENCY BREACH'."""
    cleaned = metric.replace("_risk", "").replace("_", " ").strip()
    return cleaned.upper()


def _severity_noc_color(conf: float) -> tuple[str, str, str]:
    """Return (severity_name, hex_color, status_badge_color) based on confidence."""
    if conf < 0.30:
        return ("NORMAL", "#10b981", "#0f766e")  # green
    elif conf < 0.50:
        return ("WATCH", "#3b82f6", "#0c4a6e")  # blue
    elif conf < 0.70:
        return ("WARNING", "#f59e0b", "#78350f")  # amber
    elif conf < 0.85:
        return ("HIGH", "#ef4444", "#7f1d1d")  # red
    else:
        return ("CRITICAL", "#dc2626", "#991b1b")  # dark red


def _render_primary_alert(result) -> None:
    """Render single comprehensive primary alert with full transparency and drivers."""
    primary_metric = result.primary_metric_name or ""
    primary_eta = result.primary_metric_eta_min
    primary_conf = result.primary_metric_probability
    
    # Convert target-grouped drivers back to flat list for display
    top_drivers_dict = result.top_3_drivers or {}
    if isinstance(top_drivers_dict, dict):
        top_drivers = []
        for target, drivers in top_drivers_dict.items():
            top_drivers.extend(drivers)
    else:
        top_drivers = top_drivers_dict or []
    
    timestamp = result.timestamp
    node_id = result.node_id
    severity_name, severity_hex, _ = _severity_noc_color(primary_conf)
    
    # Format ETA status
    if not np.isfinite(primary_eta) or primary_eta == float("inf") or primary_eta > 1e6:
        eta_status = "N/A"
        eta_color = "#10b981"
        eta_icon = "N/A"
    elif primary_eta < 5:
        eta_status = f"IMMEDIATE ({primary_eta:.1f}m)"
        eta_color = "#dc2626"
        eta_icon = "⚠"
    elif primary_eta < 15:
        eta_status = f"URGENT ({primary_eta:.1f}m)"
        eta_color = "#ef4444"
        eta_icon = "⚠"
    elif primary_eta < 30:
        eta_status = f"SOON ({primary_eta:.1f}m)"
        eta_color = "#f59e0b"
        eta_icon = "!"
    else:
        eta_status = f"{primary_eta:.1f}m"
        eta_color = "#3b82f6"
        eta_icon = "→"
    
    with st.container(border=True):
        # Header: Metric + Severity + ETA in single row
        col1, col2, col3 = st.columns([2.5, 1.5, 1.5], gap="large")
        
        with col1:
            st.markdown(f"### 🔴 {_format_metric_name(primary_metric)}")
            st.caption(f"Node {node_id} | {timestamp}")
        
        with col2:
            st.markdown(f"**SEVERITY**\n\n`{severity_name}`")
            st.metric("Probability", f"{primary_conf:.0%}")
        
        with col3:
            st.markdown(f"**EXHAUSTION**\n\n`{eta_icon} {eta_status}`")
        
        st.divider()
        
        # Margin Breakdown (Inline, not expander - for transparency)
        st.markdown("**Margin Analysis** — Why this severity?")
        if result.margins_per_metric:
            breakdown_data = []
            for metric in sorted(result.margins_per_metric.keys()):
                prob = result.risk_probs.get(metric, 0.0)
                thresh = result.decision_thresholds_used.get(metric, 0.5)
                margin = result.margins_per_metric[metric]
                is_highest = metric == result.highest_margin_metric
                
                badge = "🔴 PRIMARY" if is_highest else "—"
                breakdown_data.append({
                    "Metric": metric.replace("_risk", "").replace("_", " ").title(),
                    "Prob": f"{prob:.1%}",
                    "Thresh": f"{thresh:.1%}",
                    "Margin": f"{margin:+.4f}",
                    "": badge
                })
            
            st.dataframe(pd.DataFrame(breakdown_data), use_container_width=True, hide_index=True)
        
        st.divider()
        
        # Root Cause Drivers (concise)
        if top_drivers:
            st.markdown("**Root Cause Drivers (SHAP)**")
            drivers_data = []
            for i, driver in enumerate(top_drivers[:3], 1):
                feature = str(driver.get("feature", "?"))
                value = float(driver.get("value", 0.0))
                direction = str(driver.get("direction", "unknown")).lower()
                impact = "↑" if "increase" in direction else "↓"
                drivers_data.append({
                    "#": i,
                    "Feature": feature,
                    "SHAP": f"{value:+.4f}",
                    "": impact
                })
            st.dataframe(pd.DataFrame(drivers_data), use_container_width=True, hide_index=True)


def _risk_color(score: float) -> str:
    if score < 0.30:
        return "#22c55e"
    if score < 0.50:
        return "#3b82f6"
    if score < 0.70:
        return "#f59e0b"
    if score < 0.85:
        return "#ef4444"
    return "#dc2626"


def _render_risk_grid(risk_probs: dict) -> None:
    cells_html = ""
    for target in TARGET_ORDER:
        val = float(risk_probs.get(target, 0.0))
        color = _risk_color(val)
        name = target.replace("_risk", "").replace("_", " ").upper()
        bar_w = int(val * 100)
        cells_html += f"""
        <div class="risk-cell" style="border-top-color:{color};">
            <div class="risk-cell-name">{name}</div>
            <div class="risk-cell-value" style="color:{color};">{val:.1%}</div>
            <div class="risk-cell-bar" style="width:{bar_w}%;background:{color};opacity:0.7;"></div>
        </div>"""
    st.markdown(f'<div class="risk-grid">{cells_html}</div>', unsafe_allow_html=True)


def _severity_incident_badge(value: str) -> str:
    v = (value or "unknown").strip().lower()
    color = {
        "low": "#1d4ed8",
        "medium": "#ea580c",
        "high": "#b91c1c",
        "critical": "#7f1d1d",
    }.get(v, "#475569")
    return (
        f"<span style='background:{color};padding:0.2rem 0.55rem;border-radius:999px;"
        "font-size:0.72rem;font-weight:700;color:#fff;'>"
        f"{v.upper()}</span>"
    )


def _render_copy_button(text: str, key: str) -> None:
    payload = json.dumps(text)
    components.html(
        f"""
        <div style="margin-top:0.5rem;">
            <button onclick='navigator.clipboard.writeText({payload})'
              style="background:#0f766e;color:#ecfeff;border:none;padding:8px 12px;
              border-radius:8px;font-weight:700;cursor:pointer;">Copy Alert</button>
        </div>
        """,
        height=46,
        scrolling=False,
    )


def _render_eta_card(
    eta_value: float,
    status: str,
    reason: str,
    max_forecast: float | None = None,
    threshold: float | None = None,
    horizon_min: float | None = None,
) -> None:
    import math

    no_crossing = not math.isfinite(eta_value) or eta_value > 1e6
    if no_crossing:
        eta_txt = "N/A"
        eta_color = "#22c55e"
        eta_label = "NOT ESTIMABLE"
    elif eta_value < 5:
        eta_txt = f"{eta_value:.1f} min"
        eta_color = "#dc2626"
        eta_label = "IMMINENT"
    elif eta_value < 15:
        eta_txt = f"{eta_value:.1f} min"
        eta_color = "#ef4444"
        eta_label = "URGENT"
    elif eta_value < 30:
        eta_txt = f"{eta_value:.1f} min"
        eta_color = "#f59e0b"
        eta_label = "APPROACHING"
    else:
        eta_txt = f"{eta_value:.1f} min"
        eta_color = "#3b82f6"
        eta_label = "FORECAST"

    pills = ""
    if max_forecast is not None and threshold is not None:
        pills += f'<span class="eta-detail-pill">PEAK: {max_forecast:.3f}</span>'
        pills += f'<span class="eta-detail-pill">THRESHOLD: {threshold:.2f}</span>'
    if horizon_min is not None:
        pills += f'<span class="eta-detail-pill">HORIZON: {horizon_min:.0f} min</span>'

    st.markdown(f"""
    <div class="eta-card">
        <div class="eta-left">
            <div class="eta-sublabel">⏱ Capacity Exhaustion ETA</div>
            <div class="eta-value" style="color:{eta_color};">{eta_txt}</div>
            <div style="font-family:var(--mono);font-size:0.7rem;color:{eta_color};
                        letter-spacing:0.06em;margin-top:0.2rem;">{eta_label}</div>
            <div style="margin-top:0.35rem;">{pills}</div>
        </div>
        <div class="eta-reason">{reason or "Prophet forecast completed."}</div>
    </div>
    """, unsafe_allow_html=True)


def _render_download_section(result) -> None:
    """Render a downloadable results section with JSON, CSV, and text report."""
    st.markdown('<div class="section-hdr"><span class="section-hdr-dot" style="background:#a78bfa;"></span>EXPORT — Download Results</div>', unsafe_allow_html=True)

    col_json, col_csv, col_txt = st.columns(3)

    with col_json:
        json_bytes = result.to_json().encode("utf-8")
        st.download_button(
            label="⬇ Full Result (JSON)",
            data=json_bytes,
            file_name=f"qos_prediction_{result.node_id}_{result.timestamp[:10]}.json",
            mime="application/json",
            use_container_width=True,
            help="Complete PredictionResult including all probabilities, SHAP, RAG, ETA",
        )

    with col_csv:
        rows = []
        for target, prob in result.risk_probs.items():
            rows.append(
                {
                    "target": target,
                    "probability": round(float(prob), 6),
                    "severity": (
                        "critical" if float(prob) >= 0.85 else
                        "high" if float(prob) >= 0.70 else
                        "warning" if float(prob) >= 0.50 else
                        "watch" if float(prob) >= 0.30 else "normal"
                    ),
                }
            )
        csv_df = pd.DataFrame(rows)
        csv_bytes = csv_df.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="⬇ Risk Scores (CSV)",
            data=csv_bytes,
            file_name=f"risk_scores_{result.node_id}_{result.timestamp[:10]}.csv",
            mime="text/csv",
            use_container_width=True,
            help="Flat CSV of all 6 risk probabilities with severity labels",
        )

    with col_txt:
        import io as _io
        buf = _io.StringIO()
        print_prediction_terminal_summary(result, stream=buf)
        txt_bytes = buf.getvalue().encode("utf-8")
        st.download_button(
            label="⬇ NOC Report (TXT)",
            data=txt_bytes,
            file_name=f"noc_report_{result.node_id}_{result.timestamp[:10]}.txt",
            mime="text/plain",
            use_container_width=True,
            help="Human-readable NOC summary including SHAP, RAG, and LLM alert",
        )

    if result.shap_features:
        # Convert target-grouped features to flat format for CSV export
        if isinstance(result.shap_features, dict):
            flat_features = []
            for target, features in result.shap_features.items():
                for feat in features:
                    flat_features.append({
                        "target": target,
                        "feature": feat.get("feature"),
                        "value": feat.get("value"),
                        "direction": feat.get("direction"),
                    })
            shap_df = pd.DataFrame(flat_features) if flat_features else pd.DataFrame()
        else:
            # Fallback for flat format
            shap_df = pd.DataFrame(result.shap_features)
        
        if not shap_df.empty:
            shap_csv = shap_df.to_csv(index=False).encode("utf-8")
            st.download_button(
                label="⬇ SHAP Features (CSV)",
                data=shap_csv,
                file_name=f"shap_features_{result.node_id}_{result.timestamp[:10]}.csv",
                mime="text/csv",
                help="SHAP feature contributions for this prediction",
                use_container_width=True,
            )


def _compute_eta_debug_fallback(raw: pd.DataFrame, node_id: str, model_dir: Path) -> dict[str, Any]:
    """Compute ETA debug on the fly for legacy cached predictions (no debug fields)."""
    if raw.empty:
        return {
            "eta_min": float("inf"),
            "status": "prophet_error",
            "reason": "Aucune donnée QoS chargée pour recalculer ETA.",
            "max_forecast": None,
            "threshold": None,
            "horizon_min": None,
        }
    if "timestamp" not in raw.columns:
        return {
            "eta_min": float("inf"),
            "status": "prophet_error",
            "reason": "Colonne timestamp manquante pour Prophet.",
            "max_forecast": None,
            "threshold": None,
            "horizon_min": None,
        }

    df = raw.copy()
    if "node_id" in df.columns and node_id and node_id != "default":
        df = df[df["node_id"].astype(str) == str(node_id)].copy()
    if df.empty:
        return {
            "eta_min": float("inf"),
            "status": "prophet_error",
            "reason": "Aucune ligne trouvée pour ce node_id.",
            "max_forecast": None,
            "threshold": None,
            "horizon_min": None,
        }

    if "congestion_index" not in df.columns:
        if "queue_length" in df.columns and "active_connections" in df.columns:
            df["congestion_index"] = df["queue_length"] / (df["active_connections"] + 1.0)
        else:
            return (
                {
                    "eta_min": float("inf"),
                    "status": "prophet_error",
                    "reason": "Impossible de calculer congestion_index (queue_length/active_connections absents).",
                    "max_forecast": None,
                    "threshold": None,
                    "horizon_min": None,
                }
            )

    try:
        forecaster = ProphetForecaster(model_dir=model_dir)
        if hasattr(forecaster, "forecast_capacity_diagnostics"):
            diag = forecaster.forecast_capacity_diagnostics(str(node_id), df)
            return {
                "eta_min": float(diag.get("eta_min", float("inf"))),
                "status": str(diag.get("status", "prophet_error")),
                "reason": str(diag.get("reason", "Diagnostic ETA indisponible.")),
                "max_forecast": diag.get("max_forecast"),
                "threshold": diag.get("threshold"),
                "horizon_min": diag.get("horizon_min"),
            }

        eta = forecaster.forecast_capacity_exhaustion_eta_min(str(node_id), df)
        if np.isfinite(eta) and eta != float("inf"):
            return {
                "eta_min": float(eta),
                "status": "ok",
                "reason": "Forecast Prophet OK (mode compatibilité): seuil atteint.",
                "max_forecast": None,
                "threshold": None,
                "horizon_min": None,
            }
        return {
            "eta_min": float("inf"),
            "status": "no_crossing",
            "reason": "Forecast Prophet OK (mode compatibilité): aucun franchissement du seuil.",
            "max_forecast": None,
            "threshold": None,
            "horizon_min": None,
        }
    except Exception as exc:
        return {
            "eta_min": float("inf"),
            "status": "prophet_error",
            "reason": f"Erreur Prophet pendant le diagnostic ETA: {type(exc).__name__}: {str(exc)}",
            "max_forecast": None,
            "threshold": None,
            "horizon_min": None,
        }


def _render_timeseries_panel(raw: pd.DataFrame, node_id: str) -> None:
    if raw.empty:
        return
    node_df = raw.copy()
    if "node_id" in raw.columns and node_id and node_id != "default":
        node_df = raw[raw["node_id"].astype(str) == str(node_id)].copy()
    if node_df.empty:
        st.info("No rows for selected node in time-series panel.")
        return

    node_df = node_df.sort_values("timestamp" if "timestamp" in node_df.columns else node_df.columns[0]).tail(100)
    for col in ["latency_ms", "throughput_mbps", "jitter_ms", "mos_estimate"]:
        if col not in node_df.columns:
            node_df[col] = np.nan

    x = node_df["timestamp"] if "timestamp" in node_df.columns else np.arange(len(node_df))
    fig = make_subplots(
        rows=4,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.05,
        subplot_titles=("Latency (ms)", "Throughput (Mbps)", "Jitter (ms)", "MOS Estimate"),
    )

    traces = [
        ("latency_ms", "#60a5fa"),
        ("throughput_mbps", "#34d399"),
        ("jitter_ms", "#f59e0b"),
        ("mos_estimate", "#f472b6"),
    ]
    for idx, (col, color) in enumerate(traces, start=1):
        fig.add_trace(
            go.Scatter(
                x=x,
                y=node_df[col],
                mode="lines",
                line={"color": color, "width": 2.2},
                name=col,
                hovertemplate=f"{col}: %{{y:.3f}}<extra></extra>",
            ),
            row=idx,
            col=1,
        )

    if "anomaly_flag" in node_df.columns:
        flag = node_df["anomaly_flag"].astype(bool).to_numpy()
        if flag.any() and len(node_df) > 1:
            start = None
            x_vals = list(x)
            for i, is_anom in enumerate(flag):
                if is_anom and start is None:
                    start = i
                if (not is_anom or i == len(flag) - 1) and start is not None:
                    end_i = i if not is_anom else i
                    fig.add_vrect(
                        x0=x_vals[start],
                        x1=x_vals[end_i],
                        fillcolor="rgba(239, 68, 68, 0.14)",
                        layer="below",
                        line_width=0,
                    )
                    start = None

    fig.update_layout(
        height=760,
        margin={"l": 20, "r": 20, "t": 40, "b": 25},
        hovermode="x unified",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(15,23,42,0.4)",
        font={"color": "#dbeafe"},
        showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_sidebar() -> dict[str, Any]:
    with st.sidebar:
        st.markdown("### ⚙️ Control Panel")
        st.markdown("<div class='panel-glass'>Live inputs and model readiness</div>", unsafe_allow_html=True)
        model_dir = Path(st.text_input("Model directory", value=str(ROOT / "models" / "saved"))).expanduser()
        st.session_state.model_dir = model_dir
        generate_llm = st.checkbox("Generate LLM NOC Alert", value=True)

        st.markdown("#### Model Status")
        st.markdown(_model_artifact_badges(model_dir), unsafe_allow_html=True)

        st.divider()
        st.markdown("#### QoS CSV Upload")
        qos_files = st.file_uploader(
            "Upload QoS CSV files",
            type=["csv"],
            accept_multiple_files=True,
            key="qos_uploader",
        )

        st.markdown("#### Incidents CSV Upload")
        inc_files = st.file_uploader(
            "Upload incidents CSV files",
            type=["csv"],
            accept_multiple_files=True,
            key="inc_uploader",
        )

        raw = _load_qos_from_uploads(list(qos_files)) if qos_files else pd.DataFrame()
        inc = _load_incidents_from_uploads(list(inc_files)) if inc_files else pd.DataFrame()
        st.session_state.raw_df = raw
        st.session_state.inc_df = inc

        selected_node = "default"
        rows_for_node = len(raw)
        if not raw.empty and "node_id" in raw.columns:
            vc = raw.groupby(raw["node_id"].astype(str), sort=False).size().sort_index()
            labels: list[str] = []
            label_map: dict[str, str] = {}
            for nid, n in vc.items():
                n_rows = int(n)
                display = f"🛰️ {nid} ({n_rows} rows)"
                labels.append(display)
                label_map[display] = str(nid)
            choice = st.selectbox("🧭 Node Selector", options=labels)
            selected_node = label_map[choice]
            rows_for_node = int(vc.get(selected_node, 0))
        elif not raw.empty:
            st.caption("No node_id column found, using full series.")

        st.session_state.selected_node = selected_node
        st.session_state.selected_node_rows = rows_for_node

        run = st.button("🚀 Run Prediction", type="primary", use_container_width=True)

        return {
            "model_dir": model_dir,
            "generate_llm": generate_llm,
            "run": run,
            "rows_for_node": rows_for_node,
            "selected_node": selected_node,
        }


def _run_prediction_if_requested(ctrl: dict[str, Any]) -> None:
    if not ctrl["run"]:
        return
    raw: pd.DataFrame = st.session_state.raw_df
    incident_df: pd.DataFrame = st.session_state.inc_df
    selected_node = ctrl["selected_node"]

    if raw.empty:
        st.warning("Upload at least one QoS CSV file before running prediction.")
        return
    if ctrl["rows_for_node"] < LSTM_WINDOW:
        st.warning(f"Need at least {LSTM_WINDOW} rows for the selected node.")
        return

    with st.spinner("Running ensemble scoring, forecast, SHAP, RAG, and LLM alert..."):
        prog = st.progress(0, text="Preparing incident store")
        try:
            store = _build_incident_store(incident_df) if not incident_df.empty else IncidentStore()
            prog.progress(25, text="Loading prediction agent")
            agent = PredictionAgent(model_dir=ctrl["model_dir"], incident_store=store)
            node_arg = selected_node if selected_node != "default" else "default"
            target_history = raw if node_arg == "default" else raw[raw["node_id"].astype(str) == str(node_arg)].copy()
            prog.progress(55, text="Running prediction")
            result = agent.predict(node_arg, raw, generate_llm=ctrl["generate_llm"])
            prog.progress(80, text="Preparing explainability snapshot")
            try:
                prepared = agent._prepare_frame(target_history)
                st.session_state.last_feature_row = prepared.iloc[-1].to_dict() if not prepared.empty else {}
            except Exception:
                st.session_state.last_feature_row = {}
            prog.progress(100, text="Prediction complete")
        except Exception as exc:
            st.error(str(exc))
            return

    print_prediction_terminal_summary(result)
    st.session_state.prediction_result = result
    st.session_state.last_prediction_timestamp = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    st.session_state.llm_backend = "ollama"


def _render_dashboard_body() -> None:
    result = st.session_state.prediction_result
    raw: pd.DataFrame = st.session_state.raw_df
    selected_node = st.session_state.selected_node or "default"

    if raw.empty:
        st.markdown("""
        <div class="panel" style="text-align:center;padding:2rem;">
            <div style="font-family:var(--mono);font-size:0.9rem;color:var(--text3);letter-spacing:0.06em;">
                AWAITING DATA<br>
                <span style="font-size:0.75rem;margin-top:0.5rem;display:block;">
                    Upload QoS CSV files from the Control Panel to activate the dashboard
                </span>
            </div>
        </div>""", unsafe_allow_html=True)
        return

    if result is None:
        node_txt = selected_node if selected_node != "default" else "all rows"
        st.markdown(f"""
        <div class="panel">
            <span class="panel-label">Dataset loaded</span>
            <div style="font-family:var(--mono);font-size:0.82rem;color:var(--text2);">
                {len(raw):,} rows  ·  Node: {node_txt}  ·  Ready to predict
            </div>
        </div>""", unsafe_allow_html=True)
        return

    # === PRIMARY ALERT (single source of truth for severity, metric, ETA, drivers) ===
    _render_primary_alert(result)

    # === RISK BREAKDOWN, DRIVERS, CONTEXT, ALERT ===
    tab_risk, tab_shap, tab_rag, tab_llm = st.tabs([
        "⬡ RISK BREAKDOWN",
        "◈ SHAP DRIVERS",
        "◎ RAG INCIDENTS",
        "⟁ LLM ALERT",
    ])

    with tab_risk:
        st.markdown('<div class="section-hdr"><span class="section-hdr-dot" style="background:#3b82f6;"></span>ENSEMBLE — All 6 Risk Scores</div>', unsafe_allow_html=True)
        _render_risk_grid(result.risk_probs)
        targets_display = [t.replace("_risk", "").replace("_", " ").upper() for t in TARGET_ORDER]
        values = [float(result.risk_probs.get(t, 0)) for t in TARGET_ORDER]
        fig_radar = go.Figure(go.Scatterpolar(
            r=values + [values[0]],
            theta=targets_display + [targets_display[0]],
            fill="toself",
            fillcolor="rgba(59,130,246,0.1)",
            line={"color": "#3b82f6", "width": 2},
            marker={"color": [_risk_color(v) for v in values + [values[0]]], "size": 8},
        ))
        fig_radar.update_layout(
            polar={
                "bgcolor": "rgba(5,8,15,0.6)",
                "radialaxis": {
                    "visible": True,
                    "range": [0, 1],
                    "color": "#334155",
                    "tickformat": ".0%",
                    "tickfont": {"size": 9, "family": "JetBrains Mono", "color": "#475569"},
                },
                "angularaxis": {
                    "color": "#334155",
                    "tickfont": {"size": 10, "family": "JetBrains Mono", "color": "#94a3b8"},
                },
            },
            paper_bgcolor="rgba(0,0,0,0)",
            margin={"l": 30, "r": 30, "t": 30, "b": 30},
            height=320,
            showlegend=False,
        )
        st.plotly_chart(fig_radar, use_container_width=True)

    with tab_shap:
        st.markdown('<div class="section-hdr"><span class="section-hdr-dot" style="background:#f59e0b;"></span>SHAP — Root Cause Drivers</div>', unsafe_allow_html=True)
        
        # Convert target-grouped features to flat format for display
        shap_features_dict = result.shap_features or {}
        if isinstance(shap_features_dict, dict):
            shap_rows = []
            for target, features in shap_features_dict.items():
                for feat in features:
                    shap_rows.append({
                        "target": target,
                        "feature": feat.get("feature"),
                        "value": feat.get("value"),
                        "direction": feat.get("direction"),
                    })
        else:
            shap_rows = shap_features_dict if isinstance(shap_features_dict, list) else []
        
        if not shap_rows:
            st.info("No SHAP features available for this prediction.")
        else:
            sdf = pd.DataFrame(shap_rows)
            if "feature" not in sdf.columns:
                st.dataframe(sdf, use_container_width=True)
            else:
                sdf["value"] = pd.to_numeric(sdf.get("value", 0.0), errors="coerce").fillna(0.0)
                sdf["direction"] = sdf.get("direction", "increases_risk")
                
                # Deduplicate: keep highest absolute SHAP value per feature
                sdf["abs_value"] = sdf["value"].abs()
                sdf_dedup = sdf.loc[sdf.groupby("feature")["abs_value"].idxmax()].drop(columns=["abs_value"])
                sdf_sorted = sdf_dedup.sort_values("value", key=lambda s: s.abs(), ascending=False)
                
                max_abs = sdf_sorted["value"].abs().max() or 1.0
                rows_html = ""
                for _, row in sdf_sorted.iterrows():
                    feat = str(row["feature"])
                    val = float(row["value"])
                    direc = str(row["direction"])
                    color = "#fb7185" if "increase" in direc else "#22d3ee"
                    bar_w = int(abs(val) / max_abs * 100)
                    rows_html += f"""<div class="shap-row">
                        <div class="shap-label" title="{feat}">{feat}</div>
                        <div class="shap-bar-track"><div class="shap-bar-fill" style="width:{bar_w}%;background:{color};"></div></div>
                        <div class="shap-value" style="color:{color};">{val:+.4f}</div>
                    </div>"""
                st.markdown(rows_html, unsafe_allow_html=True)
                feature_vals = st.session_state.last_feature_row or {}
                sdf_plot = sdf_dedup.sort_values("value", key=lambda s: s.abs(), ascending=True)
                colors_list = sdf_plot["direction"].map({"increases_risk": "#fb7185", "decreases_risk": "#22d3ee"}).fillna("#94a3b8")
                fv_list = sdf_plot["feature"].map(lambda f: feature_vals.get(f, float("nan")))
                fig = go.Figure(go.Bar(
                    x=sdf_plot["value"], y=sdf_plot["feature"], orientation="h",
                    marker_color=list(colors_list),
                    customdata=[[fv] for fv in fv_list],
                    hovertemplate="<b>%{y}</b><br>Value: %{customdata[0]:.4f}<br>SHAP: %{x:.4f}<extra></extra>",
                ))
                fig.update_layout(
                    height=300, margin={"l": 8, "r": 8, "t": 20, "b": 8},
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(5,8,15,0.5)",
                    xaxis_title="SHAP Contribution", yaxis_title="",
                    font={"color": "#94a3b8", "family": "JetBrains Mono", "size": 11},
                    xaxis={"gridcolor": "rgba(148,163,184,0.1)", "zerolinecolor": "rgba(148,163,184,0.25)"},
                )
                st.plotly_chart(fig, use_container_width=True)

    with tab_rag:
        st.markdown('<div class="section-hdr"><span class="section-hdr-dot" style="background:#06b6d4;"></span>RAG — Similar Incident Intelligence</div>', unsafe_allow_html=True)
        incidents = result.retrieved_incidents or []
        if not incidents:
            st.markdown("""<div class="panel" style="text-align:center;padding:1.5rem;">
                <div style="font-family:var(--mono);font-size:0.78rem;color:var(--text3);letter-spacing:0.05em;">
                    NO INCIDENTS IN VECTOR DATABASE<br>
                    <span style="font-size:0.7rem;margin-top:0.3rem;display:block;">
                        Upload incident CSVs from the Control Panel to enable RAG context
                    </span></div></div>""", unsafe_allow_html=True)
        else:
            sev_colors = {"critical": ("#dc2626", "CRITICAL"), "high": ("#ef4444", "HIGH"), "medium": ("#f59e0b", "MEDIUM"), "low": ("#22c55e", "LOW")}
            toasts_html = '<div class="toast-container">'
            for i, inc in enumerate(incidents, 1):
                meta = inc.get("metadata", inc)
                itype = str(meta.get("incident_type", inc.get("incident_type", "Unknown")))
                sev = str(meta.get("severity", inc.get("severity", "unknown"))).lower()
                node = str(meta.get("node_id", inc.get("node_id", "N/A")))
                dur = meta.get("duration_sec", inc.get("duration_sec", "N/A"))
                score = meta.get("max_score", inc.get("max_score", "N/A"))
                dist = inc.get("distance", None)
                doc = str(inc.get("document", ""))
                color, sev_label = sev_colors.get(sev, ("#94a3b8", sev.upper()))
                sim_pct = f"{(1 - float(dist)) * 100:.0f}%" if dist is not None else "N/A"
                toasts_html += f"""<div class="toast" style="border-left-color:{color};animation:slideIn 0.3s ease {i*0.08:.2f}s both;">
                    <div class="toast-header">
                        <div style="display:flex;align-items:center;gap:0.5rem;">
                            <span class="toast-tag" style="background:{color}20;color:{color};border:1px solid {color}50;">{sev_label}</span>
                            <span class="toast-title">#{i} — {itype.replace('_',' ').upper()}</span>
                        </div>
                        <div style="display:flex;align-items:center;gap:0.5rem;">
                            <span class="toast-meta">SIM: {sim_pct}</span>
                            <span class="toast-meta">NODE: {node}</span>
                        </div>
                    </div>
                    <div class="toast-body">{doc}</div>
                    <div style="display:flex;gap:0.4rem;margin-top:0.3rem;flex-wrap:wrap;">
                        <span class="eta-detail-pill">DUR: {dur}s</span>
                        <span class="eta-detail-pill">SCORE: {score}</span>
                        <span class="eta-detail-pill">DIST: {f'{float(dist):.4f}' if dist is not None else 'N/A'}</span>
                    </div>
                </div>"""
            toasts_html += "</div>"
            st.markdown(toasts_html, unsafe_allow_html=True)

    with tab_llm:
        st.markdown('<div class="section-hdr"><span class="section-hdr-dot" style="background:#22c55e;"></span>LLM — NOC Alert Narrative</div>', unsafe_allow_html=True)
        backend = (st.session_state.llm_backend or "ollama").title()
        alert_txt = (result.explanation or "").strip()
        if alert_txt:
            alert_lower = alert_txt.lower()
            if "radio layer" in alert_lower and "qos layer" in alert_lower:
                layer_tag = '<span class="alert-badge" style="color:#f59e0b;border-color:#f59e0b50;background:#f59e0b10;">RADIO + QoS LAYER</span>'
            elif "radio layer" in alert_lower:
                layer_tag = '<span class="alert-badge" style="color:#06b6d4;border-color:#06b6d450;background:#06b6d410;">RADIO LAYER</span>'
            elif "qos layer" in alert_lower:
                layer_tag = '<span class="alert-badge" style="color:#a78bfa;border-color:#a78bfa50;background:#a78bfa10;">QoS LAYER</span>'
            else:
                layer_tag = ""
            st.markdown(f"""<div class="llm-terminal">
                <div class="llm-terminal-bar">
                    <div class="llm-terminal-dot" style="background:#dc2626;"></div>
                    <div class="llm-terminal-dot" style="background:#f59e0b;"></div>
                    <div class="llm-terminal-dot" style="background:#22c55e;"></div>
                    <span class="llm-terminal-label" style="margin-left:0.5rem;">NOC-ALERT-GENERATOR  ·  {backend.upper()}</span>
                    <div style="margin-left:auto;">{layer_tag}</div>
                </div>
                <div class="llm-terminal-body">{alert_txt}</div>
            </div>""", unsafe_allow_html=True)
            escaped = alert_txt.replace("`", "\\`").replace("\\", "\\\\").replace("\n", "\\n")
            components.html(f"""<div style="margin-top:0.5rem;">
                <button onclick="navigator.clipboard.writeText(`{escaped}`).then(()=>this.textContent='✓ COPIED').catch(()=>this.textContent='Copy failed')"
                    style="font-family:'JetBrains Mono',monospace;font-size:0.72rem;font-weight:700;letter-spacing:0.06em;text-transform:uppercase;
                           background:rgba(9,15,28,0.9);color:#94a3b8;border:1px solid rgba(148,163,184,0.2);border-radius:4px;
                           padding:0.35rem 0.85rem;cursor:pointer;">⎘ COPY ALERT TO CLIPBOARD</button>
            </div>""", height=50)
            st.code(alert_txt, language="markdown")
        else:
            st.markdown(f"""<div class="panel" style="text-align:center;padding:1.5rem;border:1px solid rgba(239,68,68,0.2);border-radius:6px;background:rgba(7,14,31,0.9);">
                <div style="font-family:var(--mono);font-size:0.9rem;color:#f59e0b;letter-spacing:0.06em;margin-bottom:0.5rem;">
                    ⚠ LLM ALERT UNAVAILABLE
                </div>
                <div style="font-size:0.8rem;color:var(--text2);line-height:1.6;">
                    Ollama LLM generation is not available. This usually means:<br>
                    <strong>1) Ollama service not running:</strong> Start with <span style="font-family:var(--mono);background:rgba(0,0,0,0.4);padding:0.1rem 0.3rem;border-radius:2px;">ollama serve</span><br>
                    <strong>2) Model not installed:</strong> Run <span style="font-family:var(--mono);background:rgba(0,0,0,0.4);padding:0.1rem 0.3rem;border-radius:2px;">ollama pull llama3</span> or <span style="font-family:var(--mono);background:rgba(0,0,0,0.4);padding:0.1rem 0.3rem;border-radius:2px;">ollama pull mistral</span><br>
                    <strong>3) Connection error:</strong> Verify Ollama is listening on <span style="font-family:var(--mono);background:rgba(0,0,0,0.4);padding:0.1rem 0.3rem;border-radius:2px;">http://localhost:11434</span><br>
                    <strong>4) Model download in progress:</strong> Check <span style="font-family:var(--mono);background:rgba(0,0,0,0.4);padding:0.1rem 0.3rem;border-radius:2px;">ollama list</span> for download status<br>
                    <br>
                    💡 All predictions remain fully functional. Only natural language alert synthesis is disabled.
                </div>
            </div>""", unsafe_allow_html=True)

    st.markdown("---")
    _render_download_section(result)

    ts = st.session_state.last_prediction_timestamp or "N/A"
    st.markdown(f"""
    <div class="noc-footer">
        <span class="footer-text">MODEL: XGBoost(0.55) + LSTM(0.45)  ·  ETA: Prophet  ·  EXPLAIN: SHAP  ·  CONTEXT: ChromaDB RAG</span>
        <span class="footer-text">LAST PREDICTION: {ts}  ·  LLM: {(st.session_state.llm_backend or "ollama").upper()}</span>
    </div>""", unsafe_allow_html=True)


def main() -> None:
    st.set_page_config(
        page_title="QoS Prediction Agent - NOC Dashboard",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    _inject_css()
    _init_session_state()
    _render_header()
    controls = _render_sidebar()
    _run_prediction_if_requested(controls)
    _render_dashboard_body()


if __name__ == "__main__":
    main()
