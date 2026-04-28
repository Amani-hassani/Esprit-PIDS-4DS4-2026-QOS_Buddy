import os
import json
import sys
import subprocess

import streamlit as st
import pandas as pd

from data_loader import load_timeseries, load_incidents
from sample_selector import pick_most_interesting_sample, top_interesting_samples
from usecase_1_narrative import generate_narrative
from usecase_2_qa import answer_question
from usecase_3_root_cause import classify_root_cause
from usecase_4_insights import generate_ai_insights
from usecase_5_dl_explainer import explain_dl_anomaly, generate_global_dl_summary
from usecase_6_tone_adaptation import generate_all_tones
from usecase_7_benchmark import run_benchmark
from analytics import (
    build_overview_metrics,
    build_time_series,
    build_anomaly_distribution,
    build_daily_comparison,
    build_trend_summary,
    build_incident_summary,
)
from charts import (
    line_chart_latency,
    line_chart_jitter,
    line_chart_throughput,
    bar_anomaly_distribution,
    line_daily_comparison,
)
from report_export import build_report_text, build_report_pdf


# ══════════════════════════════════════════════════════════════
# PAGE CONFIG & DESIGN SYSTEM
# ══════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="QoS Buddy",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600;700&family=DM+Mono:wght@400;500&family=Syne:wght@600;700;800&display=swap');

/* ── Root variables ── */
:root {
    --bg:        #0a0f1e;
    --surface:   #111827;
    --surface2:  #1a2236;
    --border:    rgba(255,255,255,0.07);
    --accent:    #3b82f6;
    --accent2:   #06b6d4;
    --green:     #10b981;
    --yellow:    #f59e0b;
    --red:       #ef4444;
    --text:      #f1f5f9;
    --muted:     #64748b;
    --radius:    14px;
}

/* ── Global reset ── */
html, body, [class*="css"] {
    font-family: 'DM Sans', sans-serif;
    background-color: var(--bg) !important;
    color: var(--text) !important;
}

.block-container {
    padding: 1.5rem 2rem 3rem 2rem !important;
    max-width: 1400px;
}

/* ── Sidebar ── */
[data-testid="stSidebar"] {
    background: var(--surface) !important;
    border-right: 1px solid var(--border) !important;
}
[data-testid="stSidebar"] * { color: var(--text) !important; }
[data-testid="stSidebar"] .stSelectbox label,
[data-testid="stSidebar"] .stCheckbox label,
[data-testid="stSidebar"] .stSlider label {
    color: var(--muted) !important;
    font-size: 0.78rem;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    font-weight: 600;
}

/* ── Hero banner ── */
.hero {
    background: linear-gradient(135deg, #0f172a 0%, #1e3a5f 50%, #0f2744 100%);
    border: 1px solid rgba(59,130,246,0.25);
    border-radius: 20px;
    padding: 2rem 2.5rem;
    margin-bottom: 2rem;
    position: relative;
    overflow: hidden;
}
.hero::before {
    content: '';
    position: absolute;
    top: -60px; right: -60px;
    width: 200px; height: 200px;
    background: radial-gradient(circle, rgba(59,130,246,0.15) 0%, transparent 70%);
    border-radius: 50%;
}
.hero::after {
    content: '';
    position: absolute;
    bottom: -40px; left: 30%;
    width: 300px; height: 150px;
    background: radial-gradient(ellipse, rgba(6,182,212,0.08) 0%, transparent 70%);
}
.hero-tag {
    display: inline-block;
    background: rgba(59,130,246,0.15);
    border: 1px solid rgba(59,130,246,0.3);
    color: #93c5fd;
    font-size: 0.72rem;
    font-weight: 600;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    padding: 4px 12px;
    border-radius: 100px;
    margin-bottom: 1rem;
}
.hero h1 {
    font-family: 'Syne', sans-serif;
    font-size: 2rem;
    font-weight: 800;
    margin: 0 0 0.5rem 0;
    background: linear-gradient(135deg, #f1f5f9 0%, #93c5fd 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
}
.hero p {
    color: #94a3b8;
    margin: 0;
    font-size: 0.95rem;
    font-weight: 400;
}

/* ── Section headers ── */
.section-header {
    font-family: 'Syne', sans-serif;
    font-size: 1.1rem;
    font-weight: 700;
    color: var(--text);
    margin: 2rem 0 1rem 0;
    display: flex;
    align-items: center;
    gap: 8px;
}
.section-header::after {
    content: '';
    flex: 1;
    height: 1px;
    background: var(--border);
    margin-left: 8px;
}

/* ── Metric cards ── */
[data-testid="metric-container"] {
    background: var(--surface) !important;
    border: 1px solid var(--border) !important;
    border-radius: var(--radius) !important;
    padding: 1.2rem !important;
    transition: border-color 0.2s;
}
[data-testid="metric-container"]:hover {
    border-color: rgba(59,130,246,0.3) !important;
}
[data-testid="stMetricLabel"] {
    color: var(--muted) !important;
    font-size: 0.75rem !important;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    font-weight: 600;
}
[data-testid="stMetricValue"] {
    font-family: 'DM Mono', monospace !important;
    font-size: 1.6rem !important;
    font-weight: 500 !important;
    color: var(--text) !important;
}

/* ── Trend badges ── */
.trend-box {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 0.9rem 1.2rem;
    display: flex;
    align-items: center;
    gap: 10px;
    font-size: 0.88rem;
    font-weight: 500;
}
.trend-up-bad  { border-left: 3px solid var(--red) !important;    color: #fca5a5; }
.trend-down-bad{ border-left: 3px solid var(--red) !important;    color: #fca5a5; }
.trend-up-good { border-left: 3px solid var(--green) !important;  color: #6ee7b7; }
.trend-stable  { border-left: 3px solid var(--muted) !important;  color: var(--muted); }

/* ── Cards / panels ── */
.card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 1.4rem;
}

/* ── Status pills ── */
.pill-green  { display:inline-block; background:rgba(16,185,129,0.15); color:#6ee7b7; border:1px solid rgba(16,185,129,0.3);  border-radius:100px; padding:2px 10px; font-size:0.78rem; font-weight:600; }
.pill-yellow { display:inline-block; background:rgba(245,158,11,0.15); color:#fcd34d; border:1px solid rgba(245,158,11,0.3);  border-radius:100px; padding:2px 10px; font-size:0.78rem; font-weight:600; }
.pill-red    { display:inline-block; background:rgba(239,68,68,0.15);  color:#fca5a5; border:1px solid rgba(239,68,68,0.3);   border-radius:100px; padding:2px 10px; font-size:0.78rem; font-weight:600; }

/* ── Tabs ── */
[data-testid="stTabs"] [data-testid="stTab"] {
    font-weight: 600;
    font-size: 0.88rem;
    color: var(--muted) !important;
    padding: 0.6rem 1.2rem;
    border-radius: 8px 8px 0 0;
}
[data-testid="stTabs"] [aria-selected="true"] {
    color: var(--text) !important;
    background: var(--surface) !important;
    border-bottom: 2px solid var(--accent) !important;
}

/* ── Buttons ── */
.stButton > button {
    background: linear-gradient(135deg, #2563eb, #0891b2) !important;
    color: white !important;
    border: none !important;
    border-radius: 10px !important;
    font-weight: 600 !important;
    font-size: 0.85rem !important;
    padding: 0.55rem 1.4rem !important;
    transition: opacity 0.2s, transform 0.1s !important;
    letter-spacing: 0.02em;
}
.stButton > button:hover {
    opacity: 0.88 !important;
    transform: translateY(-1px) !important;
}

/* ── Download buttons ── */
.stDownloadButton > button {
    background: var(--surface2) !important;
    color: var(--text) !important;
    border: 1px solid var(--border) !important;
    border-radius: 10px !important;
    font-weight: 500 !important;
}

/* ── Dataframes ── */
[data-testid="stDataFrame"] {
    border: 1px solid var(--border) !important;
    border-radius: var(--radius) !important;
    overflow: hidden;
}

/* ── Info / success / warning boxes ── */
.stInfo    { background: rgba(59,130,246,0.08)  !important; border-left: 3px solid var(--accent)  !important; border-radius: 8px !important; }
.stSuccess { background: rgba(16,185,129,0.08)  !important; border-left: 3px solid var(--green)   !important; border-radius: 8px !important; }
.stWarning { background: rgba(245,158,11,0.08)  !important; border-left: 3px solid var(--yellow)  !important; border-radius: 8px !important; }
.stError   { background: rgba(239,68,68,0.08)   !important; border-left: 3px solid var(--red)     !important; border-radius: 8px !important; }

/* ── Spinner ── */
[data-testid="stSpinner"] { color: var(--accent) !important; }

/* ── Select / input ── */
[data-testid="stSelectbox"] > div > div,
[data-testid="stTextInput"] > div > div {
    background: var(--surface2) !important;
    border-color: var(--border) !important;
    border-radius: 8px !important;
    color: var(--text) !important;
}

/* ── Expander ── */
[data-testid="stExpander"] {
    background: var(--surface2) !important;
    border: 1px solid var(--border) !important;
    border-radius: var(--radius) !important;
}
[data-testid="stExpander"] summary { font-weight: 600; font-size: 0.88rem; }

/* ── Code blocks ── */
code, pre {
    font-family: 'DM Mono', monospace !important;
    font-size: 0.82rem !important;
    background: var(--surface2) !important;
    border: 1px solid var(--border) !important;
    border-radius: 8px !important;
}

/* ── Scrollbar ── */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: var(--bg); }
::-webkit-scrollbar-thumb { background: #334155; border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: #475569; }

/* ── Score circle ── */
.score-block {
    display: flex;
    align-items: center;
    gap: 24px;
    padding: 20px 24px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 16px;
    margin-bottom: 1.5rem;
}
.score-number {
    font-family: 'Syne', sans-serif;
    font-size: 3rem;
    font-weight: 800;
    line-height: 1;
}
.score-label { font-weight: 700; font-size: 1rem; margin-bottom: 4px; }
.score-meta  { font-size: 0.82rem; color: var(--muted); }

/* ── Tone card ── */
.tone-card {
    border-radius: 12px;
    padding: 16px 20px;
    font-family: 'DM Mono', monospace;
    font-size: 0.85rem;
    line-height: 1.7;
    white-space: pre-wrap;
    border-left: 4px solid;
}
.tone-engineer { background: rgba(239,68,68,0.08);  border-color: #ef4444; }
.tone-manager  { background: rgba(245,158,11,0.08); border-color: #f59e0b; }
.tone-director { background: rgba(59,130,246,0.08); border-color: #3b82f6; }

/* ── Bench row coloring ── */
.bench-green  { color: #6ee7b7 !important; }
.bench-yellow { color: #fcd34d !important; }
.bench-red    { color: #fca5a5 !important; }

/* ── ML section labels ── */
.ml-badge {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    background: rgba(59,130,246,0.12);
    border: 1px solid rgba(59,130,246,0.25);
    color: #93c5fd;
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    padding: 3px 10px;
    border-radius: 100px;
    margin-bottom: 0.5rem;
}
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════

def run_python_script(script_candidates):
    for script_path in script_candidates:
        if os.path.exists(script_path):
            try:
                result = subprocess.run(
                    [sys.executable, script_path],
                    capture_output=True, text=True, cwd=os.getcwd()
                )
                if result.returncode == 0:
                    return True, result.stdout or "Exécution terminée."
                return False, result.stderr or "Erreur inconnue."
            except Exception as e:
                return False, str(e)
    return False, f"Aucun script trouvé : {script_candidates}"


def trend_class(text: str) -> str:
    t = text.lower()
    if "dégradation" in t or "hausse" in t and "amélioration" not in t:
        return "trend-up-bad"
    if "amélioration" in t:
        return "trend-up-good"
    return "trend-stable"


def style_dl_table(df: pd.DataFrame):
    def highlight_row(row):
        label = str(row.get("dl_label", ""))
        if label == "Highly Atypical Time Window":
            return ["background-color: rgba(239,68,68,0.12)"] * len(row)
        if label == "Atypical Time Window":
            return ["background-color: rgba(245,158,11,0.12)"] * len(row)
        return ["background-color: rgba(16,185,129,0.05)"] * len(row)
    return df.style.apply(highlight_row, axis=1)


def dl_status_badge(value):
    if value == "Highly Atypical Time Window":
        return "🔴 " + value
    if value == "Atypical Time Window":
        return "🟠 " + value
    return "🟢 " + value


# ══════════════════════════════════════════════════════════════
# DATA LOADING
# ══════════════════════════════════════════════════════════════

@st.cache_data
def get_data():
    return load_timeseries(), load_incidents()

try:
    df, incidents_df = get_data()
except Exception as e:
    st.error(f"Erreur lors du chargement des données : {e}")
    st.stop()


# ══════════════════════════════════════════════════════════════
# HERO BANNER
# ══════════════════════════════════════════════════════════════

st.markdown("""
<div class="hero">
    <div class="hero-tag">📡 Reporting Agent — QoS Buddy</div>
    <h1>Network Intelligence Dashboard</h1>
    <p>Analyse temps réel · LLM narratif · ML clustering · Deep Learning · Benchmark ITU-T & 3GPP</p>
</div>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════════════

with st.sidebar:
    st.markdown("""
    <div style="padding:12px 0 20px 0">
        <div style="font-family:'Syne',sans-serif;font-size:1.1rem;font-weight:800;color:#f1f5f9">
            ⚙️ Filtres
        </div>
        <div style="color:#64748b;font-size:0.78rem;margin-top:2px">Personnaliser la vue</div>
    </div>
    """, unsafe_allow_html=True)

    filtered_df = df.copy()

    if "source_file" in df.columns:
        source_files = ["Tous"] + sorted(df["source_file"].dropna().astype(str).unique().tolist())
        selected_file = st.selectbox("Fichier source", source_files)
        if selected_file != "Tous":
            filtered_df = filtered_df[filtered_df["source_file"].astype(str) == selected_file]

    if "anomaly_type" in filtered_df.columns:
        anomaly_types = ["Tous"] + sorted(filtered_df["anomaly_type"].dropna().astype(str).unique().tolist())
        selected_anomaly = st.selectbox("Type d'anomalie", anomaly_types)
        if selected_anomaly != "Tous":
            filtered_df = filtered_df[filtered_df["anomaly_type"].astype(str) == selected_anomaly]

    if "traffic_type" in filtered_df.columns:
        traffic_types = ["Tous"] + sorted(filtered_df["traffic_type"].dropna().astype(str).unique().tolist())
        selected_traffic = st.selectbox("Type de trafic", traffic_types)
        if selected_traffic != "Tous":
            filtered_df = filtered_df[filtered_df["traffic_type"].astype(str) == selected_traffic]

    only_anomalies = st.checkbox("Anomalies uniquement", value=False)
    if only_anomalies and "anomaly_flag" in filtered_df.columns:
        filtered_df = filtered_df[filtered_df["anomaly_flag"].astype(str).str.lower() == "true"]

    top_n = st.slider("Top lignes intéressantes", 3, 20, 10)

    st.markdown("---")
    st.markdown(f"""
    <div style="font-size:0.78rem;color:#475569;line-height:1.8">
        <div>📊 <b>{len(filtered_df):,}</b> samples</div>
        <div>⚡ <b>{len(incidents_df):,}</b> incidents</div>
    </div>
    """, unsafe_allow_html=True)

# Capture filtres actifs pour narrative adaptative
active_filters = {
    "source_file":    selected_file    if "source_file"   in df.columns else "Tous",
    "anomaly_type":   selected_anomaly if "anomaly_type"  in df.columns else "Tous",
    "traffic_type":   selected_traffic if "traffic_type"  in df.columns else "Tous",
    "only_anomalies": only_anomalies,
}


# ══════════════════════════════════════════════════════════════
# ANALYTICS
# ══════════════════════════════════════════════════════════════

metrics       = build_overview_metrics(filtered_df, incidents_df)
ts_df         = build_time_series(filtered_df)
dist_df       = build_anomaly_distribution(filtered_df)
daily_df      = build_daily_comparison(filtered_df)
trend_summary = build_trend_summary(filtered_df)
inc_summary_df= build_incident_summary(incidents_df, limit=10)
top_rows      = top_interesting_samples(filtered_df, n=top_n)
sample_row    = pick_most_interesting_sample(filtered_df)


# ══════════════════════════════════════════════════════════════
# KPIs
# ══════════════════════════════════════════════════════════════

st.markdown('<div class="section-header">📊 Vue d\'ensemble</div>', unsafe_allow_html=True)

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Samples",          f"{metrics['samples']:,}")
k2.metric("Incidents",        f"{metrics['incidents']:,}")
k3.metric("Anomalies",        f"{metrics['anomalies']:,}")
k4.metric("Latence moyenne",  f"{metrics['avg_latency']} ms"   if metrics['avg_latency']   else "N/A")
k5.metric("Throughput moyen", f"{metrics['avg_throughput']} Mbps" if metrics['avg_throughput'] else "N/A")

k6, k7, k8, _, __ = st.columns(5)
k6.metric("Jitter moyen",   f"{metrics['avg_jitter']} ms"   if metrics['avg_jitter']   else "N/A")
k7.metric("Latence max",    f"{metrics['max_latency']} ms"   if metrics['max_latency']  else "N/A")
k8.metric("Jitter max",     f"{metrics['max_jitter']} ms"    if metrics['max_jitter']   else "N/A")


# ══════════════════════════════════════════════════════════════
# TENDANCES
# ══════════════════════════════════════════════════════════════

st.markdown('<div class="section-header">📈 Tendances</div>', unsafe_allow_html=True)

t1, t2, t3 = st.columns(3)
for col, label, key in [
    (t1, "Latence",    "latency_trend"),
    (t2, "Jitter",     "jitter_trend"),
    (t3, "Throughput", "throughput_trend"),
]:
    val = trend_summary.get(key, "N/A")
    css = trend_class(val)
    col.markdown(
        f'<div class="trend-box {css}"><span style="font-weight:700">{label}</span> — {val}</div>',
        unsafe_allow_html=True
    )


# ══════════════════════════════════════════════════════════════
# GRAPHIQUES
# ══════════════════════════════════════════════════════════════

st.markdown('<div class="section-header">📉 Graphiques analytiques</div>', unsafe_allow_html=True)

chart_style = dict(
    plot_bgcolor='rgba(0,0,0,0)',
    paper_bgcolor='rgba(0,0,0,0)',
    font_color='#94a3b8',
    xaxis=dict(gridcolor='rgba(255,255,255,0.05)', linecolor='rgba(255,255,255,0.1)'),
    yaxis=dict(gridcolor='rgba(255,255,255,0.05)', linecolor='rgba(255,255,255,0.1)'),
    margin=dict(l=10, r=10, t=40, b=10),
)

c1, c2 = st.columns(2)
with c1:
    fig = line_chart_latency(ts_df)
    if fig:
        fig.update_layout(**chart_style)
        st.plotly_chart(fig, use_container_width=True)
    fig2 = line_chart_throughput(ts_df)
    if fig2:
        fig2.update_layout(**chart_style)
        st.plotly_chart(fig2, use_container_width=True)
with c2:
    fig3 = line_chart_jitter(ts_df)
    if fig3:
        fig3.update_layout(**chart_style)
        st.plotly_chart(fig3, use_container_width=True)
    fig4 = bar_anomaly_distribution(dist_df)
    if fig4:
        fig4.update_layout(**chart_style)
        st.plotly_chart(fig4, use_container_width=True)

fig5 = line_daily_comparison(daily_df)
if fig5:
    fig5.update_layout(**chart_style)
    st.plotly_chart(fig5, use_container_width=True)


# ══════════════════════════════════════════════════════════════
# TOP MESURES
# ══════════════════════════════════════════════════════════════

st.markdown('<div class="section-header">🔍 Top mesures intéressantes</div>', unsafe_allow_html=True)
if top_rows:
    top_df = pd.DataFrame(top_rows)
    display_cols = [c for c in [
        "timestamp","latency_ms","jitter_ms","packet_loss_pct",
        "throughput_mbps","traffic_type","anomaly_type",
        "anomaly_score","interest_score","source_file"
    ] if c in top_df.columns]
    st.dataframe(top_df[display_cols], use_container_width=True, height=280)
else:
    st.warning("Aucune donnée après filtrage.")

# Mesure sélectionnée
st.markdown('<div class="section-header">🎯 Mesure automatiquement sélectionnée</div>', unsafe_allow_html=True)
if sample_row is None:
    st.warning("Aucune mesure disponible.")
    st.stop()

st.dataframe(pd.DataFrame([{
    k: sample_row.get(k) for k in [
        "timestamp","latency_ms","jitter_ms","packet_loss_pct",
        "throughput_mbps","traffic_type","anomaly_type","anomaly_score",
        "interest_score","source_file"
    ]
}]), use_container_width=True)


# ══════════════════════════════════════════════════════════════
# ANALYSE LLM — USECASES 1/2/3
# ══════════════════════════════════════════════════════════════

st.markdown('<div class="section-header">🤖 Analyse LLM</div>', unsafe_allow_html=True)

narrative_result = ""
root_cause_result = ""

tab1, tab2, tab3 = st.tabs(["💬 Narrative", "🔎 Cause racine", "❓ Q&A"])

with tab1:
    col_btn, col_info = st.columns([1, 3])
    with col_btn:
        if st.button("Générer la narrative", key="btn_narrative"):
            with st.spinner("LLM en cours..."):
                narrative_result = generate_narrative(sample_row)
            st.session_state["narrative_result"] = narrative_result
    if "narrative_result" in st.session_state:
        st.markdown(
            f'<div class="card" style="margin-top:1rem">{st.session_state["narrative_result"]}</div>',
            unsafe_allow_html=True
        )

with tab2:
    col_btn2, _ = st.columns([1, 3])
    with col_btn2:
        if st.button("Classifier la cause", key="btn_root_cause"):
            with st.spinner("Classification..."):
                root_cause_result = classify_root_cause(sample_row)
            st.session_state["root_cause_result"] = root_cause_result
    if "root_cause_result" in st.session_state:
        st.code(st.session_state["root_cause_result"], language="json")

with tab3:
    question = st.text_input(
        "Question",
        value="Quel est le problème le plus critique observé et pourquoi ?",
        label_visibility="collapsed",
        placeholder="Pose une question sur les données réseau..."
    )
    if st.button("Analyser", key="btn_qa"):
        with st.spinner("Analyse LLM..."):
            answer = answer_question(question, filtered_df, incidents_df, top_rows=top_rows)
        st.session_state["qa_answer"] = answer
    if "qa_answer" in st.session_state:
        st.markdown(
            f'<div class="card" style="margin-top:1rem">{st.session_state["qa_answer"]}</div>',
            unsafe_allow_html=True
        )


# ══════════════════════════════════════════════════════════════
# INCIDENTS TABLE
# ══════════════════════════════════════════════════════════════

st.markdown('<div class="section-header">🚨 Incidents principaux</div>', unsafe_allow_html=True)
if not inc_summary_df.empty:
    st.dataframe(inc_summary_df, use_container_width=True, height=260)
else:
    st.info("Aucun incident disponible.")


# ══════════════════════════════════════════════════════════════
# AI INSIGHTS — USECASE 4
# ══════════════════════════════════════════════════════════════

st.markdown('<div class="section-header">💡 Insights intelligents LLM + ML</div>', unsafe_allow_html=True)

cluster_summary_df = None
top_atypical_df    = None
cluster_summary_path = "outputs/kmeans_pro/cluster_summary.csv"
top_atypical_path    = "outputs/isolation_forest_pro/top_atypical_incidents.csv"

if os.path.exists(cluster_summary_path):
    cluster_summary_df = pd.read_csv(cluster_summary_path)
if os.path.exists(top_atypical_path):
    top_atypical_df = pd.read_csv(top_atypical_path)

col_btn_ins, col_info_ins = st.columns([1, 3])
with col_btn_ins:
    if st.button("Générer les insights", key="btn_ai_insights"):
        with st.spinner("Génération des insights..."):
            insights_text = generate_ai_insights(
                sample_row=sample_row,
                cluster_summary_df=cluster_summary_df,
                top_atypical_df=top_atypical_df
            )
        st.session_state["insights_text"] = insights_text
if "insights_text" in st.session_state:
    st.markdown(
        f'<div class="card" style="margin-top:1rem">{st.session_state["insights_text"]}</div>',
        unsafe_allow_html=True
    )


# ══════════════════════════════════════════════════════════════
# EXPORT RAPPORT
# ══════════════════════════════════════════════════════════════

st.markdown('<div class="section-header">📄 Exporter le rapport</div>', unsafe_allow_html=True)

col_exp, _ = st.columns([1, 3])
with col_exp:
    if st.button("Préparer le rapport", key="btn_export_report"):
        with st.spinner("Génération..."):
            nar = st.session_state.get("narrative_result") or generate_narrative(sample_row)
            rc  = st.session_state.get("root_cause_result") or classify_root_cause(sample_row)
            incidents_preview = inc_summary_df.to_string(index=False) if not inc_summary_df.empty else "N/A"
            report_text = build_report_text(
                metrics=metrics, trend_summary=trend_summary,
                narrative=nar, root_cause=rc,
                incidents_preview=incidents_preview
            )
            pdf_buffer = build_report_pdf(report_text)
        st.session_state["report_text"] = report_text
        st.session_state["pdf_buffer"]  = pdf_buffer

if "report_text" in st.session_state:
    dl1, dl2 = st.columns(2)
    with dl1:
        st.download_button("⬇️ Télécharger TXT", st.session_state["report_text"],
                           "qos_buddy_report.txt", "text/plain")
    with dl2:
        st.download_button("⬇️ Télécharger PDF", st.session_state["pdf_buffer"],
                           "qos_buddy_report.pdf", "application/pdf")


# ══════════════════════════════════════════════════════════════
# ANALYSE MACHINE LEARNING
# ══════════════════════════════════════════════════════════════

st.markdown('<div class="section-header">🧠 Analyse Machine Learning</div>', unsafe_allow_html=True)

tab_ml1, tab_ml2, tab_ml3 = st.tabs([
    "🔵 K-Means Clustering",
    "🟠 Isolation Forest",
    "🔴 Autoencoder Deep Learning"
])

# ── K-MEANS ──────────────────────────────────────────────────
with tab_ml1:
    st.markdown('<div class="ml-badge">🔵 Non supervisé · Scikit-learn</div>', unsafe_allow_html=True)
    st.markdown("**K-Means Clustering** — Regroupe les incidents en familles homogènes pour structurer le rapport.")

    kmeans_dir           = "outputs/kmeans_pro"
    cluster_summary_path = os.path.join(kmeans_dir, "cluster_summary.csv")
    metadata_path        = os.path.join(kmeans_dir, "metadata.json")
    elbow_path           = os.path.join(kmeans_dir, "elbow_method.png")
    silhouette_path      = os.path.join(kmeans_dir, "silhouette_scores.png")
    pca_path             = os.path.join(kmeans_dir, "clusters_pca.png")

    col_run, col_desc = st.columns([1, 3])
    with col_run:
        if st.button("▶ Lancer K-Means", key="run_kmeans_btn"):
            with st.spinner("Clustering en cours..."):
                success, message = run_python_script(["ml_kmeans_pro.py", "data/ml_kmeans_pro.py"])
            if success:
                st.success("K-Means exécuté avec succès.")
                st.cache_data.clear()
            else:
                st.error("Erreur K-Means")
                st.code(message)
    with col_desc:
        st.info("Segmente automatiquement les incidents en clusters (Mineurs / Modérés / Critiques) via l'algorithme K-Means avec sélection optimale par méthode Elbow et score Silhouette.")

    if os.path.exists(cluster_summary_path):
        cluster_df = pd.read_csv(cluster_summary_path)

        # Cluster cards
        if "cluster_label" in cluster_df.columns:
            cols = st.columns(len(cluster_df))
            for i, (_, row) in enumerate(cluster_df.iterrows()):
                label    = row.get("cluster_label", f"Cluster {i}")
                size     = int(row.get("cluster_size", 0))
                score    = round(float(row.get("max_score", 0)), 2) if "max_score" in row else "N/A"
                severity = row.get("dominant_severity", "N/A")
                inc_type = row.get("dominant_incident_type", "N/A")

                sev_color = {"critical": "#ef4444", "high": "#f59e0b",
                             "medium": "#3b82f6", "low": "#10b981"}.get(str(severity).lower(), "#64748b")

                cols[i].markdown(f"""
                <div class="card" style="text-align:center;border-top:3px solid {sev_color}">
                    <div style="font-size:0.7rem;font-weight:700;letter-spacing:0.12em;text-transform:uppercase;
                                color:{sev_color};opacity:0.8;margin-bottom:6px">Cluster {i}</div>
                    <div style="font-family:'Syne',sans-serif;font-size:1.1rem;font-weight:800;margin-bottom:8px">{label}</div>
                    <div style="font-size:2rem;font-weight:700;color:{sev_color}">{size}</div>
                    <div style="color:#64748b;font-size:0.75rem;margin-bottom:8px">incidents</div>
                    <div style="font-size:0.78rem">Score moy: <b>{score}</b></div>
                    <div style="font-size:0.78rem">Sévérité: <b style="color:{sev_color}">{severity}</b></div>
                    <div style="font-size:0.75rem;color:#64748b;margin-top:4px">{inc_type}</div>
                </div>
                """, unsafe_allow_html=True)

        st.markdown("<div style='margin-top:1.5rem'></div>", unsafe_allow_html=True)

        # Tableau complet
        with st.expander("📋 Tableau complet des clusters"):
            st.dataframe(cluster_df, use_container_width=True)

        # Graphiques
        col_g1, col_g2, col_g3 = st.columns(3)
        with col_g1:
            if os.path.exists(elbow_path):
                st.image(elbow_path, caption="Elbow Method", use_container_width=True)
        with col_g2:
            if os.path.exists(silhouette_path):
                st.image(silhouette_path, caption="Silhouette Score", use_container_width=True)
        with col_g3:
            if os.path.exists(pca_path):
                st.image(pca_path, caption="Projection PCA", use_container_width=True)

        if os.path.exists(metadata_path):
            with st.expander("ℹ️ Métadonnées du modèle"):
                with open(metadata_path, encoding="utf-8") as f:
                    st.json(json.load(f))
    else:
        st.warning("Aucun résultat K-Means disponible. Lancez le modèle.")


# ── ISOLATION FOREST ─────────────────────────────────────────
with tab_ml2:
    st.markdown('<div class="ml-badge">🟠 Détection d\'anomalies · Scikit-learn</div>', unsafe_allow_html=True)
    st.markdown("**Isolation Forest** — Identifie les incidents atypiques invisibles au clustering classique.")

    iso_dir          = "outputs/isolation_forest_pro"
    metadata_path    = os.path.join(iso_dir, "metadata.json")
    top_atypical_path= os.path.join(iso_dir, "top_atypical_incidents.csv")
    all_scored_path  = os.path.join(iso_dir, "incidents_isolation_scored.csv")
    pca_path_iso     = os.path.join(iso_dir, "isolation_pca.png")
    score_dist_path  = os.path.join(iso_dir, "isolation_score_distribution.png")

    col_run2, col_desc2 = st.columns([1, 3])
    with col_run2:
        if st.button("▶ Lancer Isolation Forest", key="run_iso_btn"):
            with st.spinner("Exécution..."):
                success, message = run_python_script(["ml_isolation_forest_pro.py"])
            if success:
                st.success("Isolation Forest exécuté.")
                st.cache_data.clear()
            else:
                st.error("Erreur")
                st.code(message)
    with col_desc2:
        st.info("Met en évidence les incidents atypiques parmi les incidents déjà identifiés — complète le clustering sans empiéter sur les autres agents.")

    if os.path.exists(metadata_path):
        with open(metadata_path, encoding="utf-8") as f:
            meta_iso = json.load(f)

        m1, m2, m3 = st.columns(3)
        m1.metric("Incidents analysés",  meta_iso.get("n_samples", "N/A"))
        m2.metric("Incidents atypiques", meta_iso.get("n_outliers", "N/A"))
        m3.metric("Ratio atypique",      meta_iso.get("outlier_ratio", "N/A"))

    if os.path.exists(top_atypical_path):
        top_at = pd.read_csv(top_atypical_path)
        st.markdown("**Top incidents atypiques**")
        st.dataframe(top_at, use_container_width=True, height=240)

    col_viz1, col_viz2 = st.columns(2)
    with col_viz1:
        if os.path.exists(score_dist_path):
            st.image(score_dist_path, caption="Distribution des scores", use_container_width=True)
    with col_viz2:
        if os.path.exists(pca_path_iso):
            st.image(pca_path_iso, caption="Projection PCA", use_container_width=True)

    if os.path.exists(all_scored_path):
        scored_df = pd.read_csv(all_scored_path)
        with st.expander("📋 Aperçu complet des incidents scorés"):
            show_cols = [c for c in [
                "incident_type","severity","duration_sec","max_score",
                "isolation_score","outlier_flag","outlier_label","source_file"
            ] if c in scored_df.columns]
            st.dataframe(scored_df[show_cols].head(100), use_container_width=True)
    else:
        st.warning("Aucun résultat Isolation Forest disponible.")


# ── AUTOENCODER DL ───────────────────────────────────────────
with tab_ml3:
    st.markdown('<div class="ml-badge">🔴 Deep Learning · PyTorch Autoencoder</div>', unsafe_allow_html=True)
    st.markdown("**Autoencoder** — Apprend le comportement normal du réseau et détecte les déviances via erreur de reconstruction.")

    dl_dir           = "outputs/autoencoder_pro"
    metadata_path    = os.path.join(dl_dir, "metadata.json")
    results_path     = os.path.join(dl_dir, "autoencoder_results.csv")
    top_dl_path      = os.path.join(dl_dir, "top_dl_anomalies.csv")
    error_dist_path  = os.path.join(dl_dir, "reconstruction_error_distribution.png")
    error_time_path  = os.path.join(dl_dir, "reconstruction_error_timeseries.png")
    training_loss_path = os.path.join(dl_dir, "training_loss.png")

    col_run3, col_desc3 = st.columns([1, 3])
    with col_run3:
        if st.button("▶ Lancer Autoencoder", key="run_autoencoder_btn"):
            with st.spinner("Entraînement DL..."):
                success, message = run_python_script(["ml_autoencoder_pro.py"])
            if success:
                st.success("Autoencoder exécuté.")
                st.cache_data.clear()
            else:
                st.error("Erreur")
                st.code(message)
    with col_desc3:
        st.info("Apprend la représentation normale du réseau (time-series), puis signale les mesures avec erreur de reconstruction élevée comme anomalies DL.")

    meta_dl = None
    if os.path.exists(metadata_path):
        with open(metadata_path, encoding="utf-8") as f:
            meta_dl = json.load(f)
        d1, d2, d3 = st.columns(3)
        d1.metric("Mesures analysées", meta_dl.get("n_total_samples","N/A"))
        d2.metric("Anomalies DL",      meta_dl.get("n_dl_anomalies","N/A"))
        d3.metric("Ratio DL",          meta_dl.get("dl_anomaly_ratio","N/A"))

    top_dl_df = None
    if os.path.exists(top_dl_path):
        top_dl_df = pd.read_csv(top_dl_path).copy()
        if "dl_label" in top_dl_df.columns:
            top_dl_df["dl_label_display"] = top_dl_df["dl_label"].apply(dl_status_badge)

        st.markdown("**Top anomalies Deep Learning**")
        display_cols = [c for c in [
            "timestamp","latency_ms","jitter_ms","packet_loss_pct","throughput_mbps",
            "rsrp_dbm","sinr_db","channel_util_pct","anomaly_type","anomaly_score",
            "reconstruction_error","dl_label"
        ] if c in top_dl_df.columns]
        st.dataframe(style_dl_table(top_dl_df[display_cols].copy()), use_container_width=True)

        # LLM explainer
        st.markdown("**Explication LLM des anomalies DL**")
        col_sel, col_exp_txt = st.columns([1, 2])
        with col_sel:
            selected_idx = st.selectbox(
                "Anomalie à expliquer",
                options=list(range(len(top_dl_df))),
                format_func=lambda i: f"#{i} — {top_dl_df.iloc[i].get('anomaly_type','N/A')} (err={round(float(top_dl_df.iloc[i].get('reconstruction_error',0)),3)})"
            )
            if st.button("Expliquer", key="btn_explain_one_dl"):
                with st.spinner("LLM..."):
                    explanation = explain_dl_anomaly(top_dl_df.iloc[selected_idx])
                st.session_state["dl_explanation_one"] = explanation
        with col_exp_txt:
            if "dl_explanation_one" in st.session_state:
                st.markdown(
                    f'<div class="card">{st.session_state["dl_explanation_one"]}</div>',
                    unsafe_allow_html=True
                )

        col_gb, _ = st.columns([1, 3])
        with col_gb:
            if st.button("Résumé global DL", key="btn_explain_global_dl"):
                with st.spinner("Résumé LLM..."):
                    global_summary = generate_global_dl_summary(top_dl_df, meta_dl)
                st.session_state["dl_global_summary"] = global_summary
        if "dl_global_summary" in st.session_state:
            st.markdown(
                f'<div class="card" style="margin-top:1rem">{st.session_state["dl_global_summary"]}</div>',
                unsafe_allow_html=True
            )

    col_viz_dl1, col_viz_dl2 = st.columns(2)
    with col_viz_dl1:
        if os.path.exists(error_dist_path):
            st.image(error_dist_path, caption="Distribution erreurs de reconstruction", use_container_width=True)
    with col_viz_dl2:
        if os.path.exists(training_loss_path):
            st.image(training_loss_path, caption="Courbe d'apprentissage", use_container_width=True)
    if os.path.exists(error_time_path):
        st.image(error_time_path, caption="Erreur de reconstruction dans le temps", use_container_width=True)

    if os.path.exists(results_path):
        dl_df = pd.read_csv(results_path).copy()
        with st.expander("📋 Aperçu complet des résultats Autoencoder"):
            show_cols = [c for c in [
                "timestamp","latency_ms","jitter_ms","packet_loss_pct","throughput_mbps",
                "rsrp_dbm","sinr_db","channel_util_pct","reconstruction_error","dl_anomaly_flag","dl_label","source_file"
            ] if c in dl_df.columns]
            st.dataframe(style_dl_table(dl_df[show_cols].head(100)), use_container_width=True)
    else:
        st.warning("Aucun résultat Autoencoder disponible.")


# ══════════════════════════════════════════════════════════════
# 🧠 INTELLIGENCE LLM AVANCÉE — USECASES 6, 7 & 8
# ══════════════════════════════════════════════════════════════

from usecase_8_audio_report import render_audio_report_widget
from usecase_9_digest_email import render_digest_widget
from usecase_10_adaptive_narrative import render_adaptive_narrative_widget

st.markdown('<div class="section-header">🧬 Intelligence LLM Avancée</div>', unsafe_allow_html=True)

tab_tone, tab_bench, tab_audio, tab_digest, tab_adaptive = st.tabs([
    "📣 Rapport Multi-Destinataire",
    "📐 Benchmark ITU-T & 3GPP",
    "🎙️ Rapport Audio",
    "📧 Digest Email",
    "⚡ Narrative Auto-Évolutive"
])

# ── TONE ADAPTATION ──────────────────────────────────────────
with tab_tone:
    st.markdown('<div class="ml-badge">📣 LLM · Narration adaptative multi-audience</div>', unsafe_allow_html=True)
    st.markdown("**Tone Adaptation** — Le même rapport reformulé en 3 versions selon le destinataire.")

    col_tone_btn, col_tone_info = st.columns([1, 3])
    with col_tone_btn:
        if st.button("Générer les 3 versions", key="btn_tone"):
            with st.spinner("LLM en cours pour les 3 audiences..."):
                tone_results = generate_all_tones(
                    metrics=metrics,
                    trend_summary=trend_summary,
                    sample_row=sample_row,
                    cluster_summary_df=cluster_summary_df,
                    top_atypical_df=top_atypical_df
                )
            st.session_state["tone_results"] = tone_results
    with col_tone_info:
        st.info("Le LLM reformule les données existantes selon le niveau de langage de chaque destinataire. Aucun calcul supplémentaire — uniquement de la narration adaptative.")

    if "tone_results" in st.session_state:
        tone = st.session_state["tone_results"]
        eng_tab, mgr_tab, dir_tab = st.tabs(["👷 Ingénieur", "📊 Manager", "🏢 Directeur"])

        with eng_tab:
            st.markdown("""
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:12px">
                <span style="font-size:1.2rem">📟</span>
                <span style="font-weight:700">Notification SMS technique</span>
                <span class="pill-red">Ultra-concis</span>
                <span class="pill-red">Métriques brutes</span>
            </div>
            """, unsafe_allow_html=True)
            st.markdown(
                f'<div class="tone-card tone-engineer">{tone.get("engineer","N/A")}</div>',
                unsafe_allow_html=True
            )
            st.caption("🎯 Ingénieur terrain — 3 lignes max, nœud + métriques + action immédiate")

        with mgr_tab:
            st.markdown("""
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:12px">
                <span style="font-size:1.2rem">📧</span>
                <span style="font-weight:700">Email exécutif</span>
                <span class="pill-yellow">Impact business</span>
                <span class="pill-yellow">Recommandation</span>
            </div>
            """, unsafe_allow_html=True)
            st.markdown(
                f'<div class="tone-card tone-manager">{tone.get("manager","N/A")}</div>',
                unsafe_allow_html=True
            )
            st.caption("🎯 Responsable opérationnel — synthèse, impact client, action requise")

        with dir_tab:
            st.markdown("""
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:12px">
                <span style="font-size:1.2rem">📑</span>
                <span style="font-weight:700">Rapport structuré</span>
                <span style="display:inline-block;background:rgba(59,130,246,0.15);color:#93c5fd;border:1px solid rgba(59,130,246,0.3);border-radius:100px;padding:2px 10px;font-size:0.78rem;font-weight:600">Stratégique</span>
                <span style="display:inline-block;background:rgba(59,130,246,0.15);color:#93c5fd;border:1px solid rgba(59,130,246,0.3);border-radius:100px;padding:2px 10px;font-size:0.78rem;font-weight:600">Analytique</span>
            </div>
            """, unsafe_allow_html=True)
            st.markdown(
                f'<div class="tone-card tone-director">{tone.get("director","N/A")}</div>',
                unsafe_allow_html=True
            )
            st.caption("🎯 Directeur technique — contexte, tendances, risques, recommandations stratégiques")


# ── BENCHMARK SECTORIEL ──────────────────────────────────────
with tab_bench:
    st.markdown('<div class="ml-badge">📐 LLM · Standards ITU-T & 3GPP</div>', unsafe_allow_html=True)
    st.markdown("**Benchmark Sectoriel** — Conformité automatique aux normes internationales télécom.")

    col_bench_btn, col_bench_info = st.columns([1, 3])
    with col_bench_btn:
        if st.button("Lancer le benchmark", key="btn_benchmark"):
            with st.spinner("Évaluation des standards en cours..."):
                bench_report = run_benchmark(filtered_df)
            st.session_state["bench_report"] = bench_report
    with col_bench_info:
        st.info(
            "8 standards évalués : ITU-T G.114 (latence), ITU-T Y.1541 (jitter), "
            "ITU-T E.501 (packet loss), ITU-T P.10 (MOS), 3GPP TS 22.261 (throughput), "
            "3GPP TS 36.214 (SINR, RSRP), 3GPP TS 36.321 (CQI)."
        )

    if "bench_report" in st.session_state:
        bench      = st.session_state["bench_report"]
        compliance = bench["compliance"]
        results    = bench["results"]

        # Score card
        score = compliance["score"]
        score_color = "#10b981" if score >= 80 else "#f59e0b" if score >= 60 else "#ef4444"
        st.markdown(f"""
        <div class="score-block">
            <div class="score-number" style="color:{score_color}">{score}%</div>
            <div>
                <div class="score-label">Score de conformité global</div>
                <div class="score-meta">
                    ✅ {compliance['green']} conformes &nbsp;·&nbsp;
                    ⚠️ {compliance['yellow']} limites &nbsp;·&nbsp;
                    🔴 {compliance['red']} non conformes &nbsp;·&nbsp;
                    {compliance['total']} métriques évaluées
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        # Résultats table
        col_bench_tbl, col_bench_narr = st.columns([1, 1])

        with col_bench_tbl:
            st.markdown("**Résultats par métrique**")
            for r in results:
                status = r["status"]
                if "Conforme" in status:
                    pill_cls = "pill-green"
                elif "Limite" in status:
                    pill_cls = "pill-yellow"
                else:
                    pill_cls = "pill-red"

                st.markdown(f"""
                <div style="display:flex;justify-content:space-between;align-items:center;
                            padding:10px 14px;border-radius:8px;margin-bottom:6px;
                            background:var(--surface);border:1px solid var(--border)">
                    <div>
                        <div style="font-weight:600;font-size:0.88rem">{r['description'][:30]}</div>
                        <div style="color:#64748b;font-size:0.75rem;font-family:'DM Mono',monospace">{r['reference']}</div>
                    </div>
                    <div style="text-align:right">
                        <div style="font-family:'DM Mono',monospace;font-size:0.9rem;font-weight:600">
                            {r['measured']:.1f}{r['unit']}
                        </div>
                        <div style="font-size:0.72rem;color:#64748b">{r['direction']}{r['threshold']}{r['unit']}</div>
                    </div>
                    <span class="{pill_cls}" style="margin-left:12px">{status}</span>
                </div>
                """, unsafe_allow_html=True)

        with col_bench_narr:
            st.markdown("**Analyse narrative LLM**")
            st.markdown(
                f'<div class="card" style="height:100%;min-height:300px">{bench["narrative"]}</div>',
                unsafe_allow_html=True
            )

        with st.expander("🔬 KPIs bruts utilisés"):
            kpi_rows = [{"Métrique": k, "Valeur": v} for k, v in bench["kpis"].items() if v is not None]
            if kpi_rows:
                st.dataframe(pd.DataFrame(kpi_rows), use_container_width=True)


# ── RAPPORT AUDIO TTS ─────────────────────────────────────────
with tab_audio:
    render_audio_report_widget(metrics, trend_summary, sample_row)

# ── DIGEST EMAIL ──────────────────────────────────────────────
with tab_digest:
    render_digest_widget(metrics, trend_summary, sample_row)

# ── NARRATIVE AUTO-ÉVOLUTIVE ──────────────────────────────────
with tab_adaptive:
    render_adaptive_narrative_widget(
        filtered_df, metrics, trend_summary,
        sample_row, active_filters
    )


# ══════════════════════════════════════════════════════════════
# DONNÉES BRUTES
# ══════════════════════════════════════════════════════════════

st.markdown('<div class="section-header">🗃️ Données brutes</div>', unsafe_allow_html=True)
show_cols = [c for c in [
    "timestamp","latency_ms","jitter_ms","packet_loss_pct",
    "throughput_mbps","traffic_type","anomaly_flag","anomaly_type",
    "anomaly_score","source_file"
] if c in filtered_df.columns]
st.dataframe(filtered_df[show_cols].head(100), use_container_width=True, height=280)