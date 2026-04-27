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


st.set_page_config(
    page_title="QoS Buddy Dashboard",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
.block-container {
    padding-top: 1.2rem;
    padding-bottom: 2rem;
}
.hero {
    padding: 1.2rem 1.4rem;
    border-radius: 18px;
    background: linear-gradient(135deg, #111827 0%, #1e293b 100%);
    border: 1px solid rgba(255,255,255,0.08);
    margin-bottom: 1rem;
}
.hero h1 {
    margin: 0;
    color: white;
}
.hero p {
    color: #cbd5e1;
    margin-top: 0.35rem;
}
.section-title {
    font-size: 1.15rem;
    font-weight: 700;
    margin: 0.6rem 0;
}
div[data-testid="metric-container"] {
    border: 1px solid rgba(255,255,255,0.07);
    padding: 12px;
    border-radius: 16px;
}
.stButton button {
    width: 100%;
    border-radius: 12px;
    font-weight: 600;
}
</style>
""", unsafe_allow_html=True)


@st.cache_data
def get_data():
    return load_timeseries(), load_incidents()


def run_python_script(script_candidates):
    for script_path in script_candidates:
        if os.path.exists(script_path):
            try:
                result = subprocess.run(
                    [sys.executable, script_path],
                    capture_output=True,
                    text=True,
                    cwd=os.getcwd()
                )

                if result.returncode == 0:
                    return True, result.stdout if result.stdout.strip() else "Execution terminee avec succes."
                else:
                    error_msg = result.stderr if result.stderr.strip() else "Erreur inconnue."
                    return False, error_msg
            except Exception as e:
                return False, str(e)

    return False, f"Aucun script trouve parmi : {script_candidates}"


try:
    df, incidents_df = get_data()
except Exception as e:
    st.error(f"Erreur lors du chargement des donnees : {e}")
    st.stop()


st.markdown("""
<div class="hero">
    <h1>📡 QoS Buddy — Dashboard analytique, LLM & ML</h1>
    <p>Suivi des tendances, comparaison des performances, visualisation des anomalies, analyse LLM et enrichissement ML du Reporting Agent.</p>
</div>
""", unsafe_allow_html=True)
def style_dl_table(df: pd.DataFrame):
    def highlight_row(row):
        label = str(row.get("dl_label", ""))
        if label == "Highly Atypical Time Window":
            return ["background-color: rgba(255, 0, 0, 0.18)"] * len(row)
        if label == "Atypical Time Window":
            return ["background-color: rgba(255, 165, 0, 0.20)"] * len(row)
        return ["background-color: rgba(0, 128, 0, 0.08)"] * len(row)

    return df.style.apply(highlight_row, axis=1)


def dl_status_badge(value):
    if value == "Highly Atypical Time Window":
        return "🔴 " + value
    if value == "Atypical Time Window":
        return "🟠 " + value
    return "🟢 " + value

# =========================
# SIDEBAR FILTRES
# =========================
st.sidebar.title("Filtres")

filtered_df = df.copy()

if "source_file" in df.columns:
    source_files = ["Tous"] + sorted(df["source_file"].dropna().astype(str).unique().tolist())
    selected_file = st.sidebar.selectbox("Fichier source", source_files)
    if selected_file != "Tous":
        filtered_df = filtered_df[filtered_df["source_file"].astype(str) == selected_file]

if "anomaly_type" in filtered_df.columns:
    anomaly_types = ["Tous"] + sorted(filtered_df["anomaly_type"].dropna().astype(str).unique().tolist())
    selected_anomaly = st.sidebar.selectbox("Type d'anomalie", anomaly_types)
    if selected_anomaly != "Tous":
        filtered_df = filtered_df[filtered_df["anomaly_type"].astype(str) == selected_anomaly]

if "traffic_type" in filtered_df.columns:
    traffic_types = ["Tous"] + sorted(filtered_df["traffic_type"].dropna().astype(str).unique().tolist())
    selected_traffic = st.sidebar.selectbox("Type de trafic", traffic_types)
    if selected_traffic != "Tous":
        filtered_df = filtered_df[filtered_df["traffic_type"].astype(str) == selected_traffic]

only_anomalies = st.sidebar.checkbox("Afficher uniquement les anomalies", value=False)
if only_anomalies and "anomaly_flag" in filtered_df.columns:
    filtered_df = filtered_df[filtered_df["anomaly_flag"].astype(str).str.lower() == "true"]

top_n = st.sidebar.slider("Top lignes interessantes", min_value=3, max_value=20, value=10, step=1)

# =========================
# ANALYTICS
# =========================
metrics = build_overview_metrics(filtered_df, incidents_df)
ts_df = build_time_series(filtered_df)
dist_df = build_anomaly_distribution(filtered_df)
daily_df = build_daily_comparison(filtered_df)
trend_summary = build_trend_summary(filtered_df)
inc_summary_df = build_incident_summary(incidents_df, limit=10)

top_rows = top_interesting_samples(filtered_df, n=top_n)
sample_row = pick_most_interesting_sample(filtered_df)

# =========================
# KPI SECTION
# =========================
st.markdown('<div class="section-title">Vue d’ensemble</div>', unsafe_allow_html=True)
k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Samples", metrics["samples"])
k2.metric("Incidents", metrics["incidents"])
k3.metric("Anomalies", metrics["anomalies"])
k4.metric("Latence moyenne", f"{metrics['avg_latency']} ms" if metrics["avg_latency"] is not None else "N/A")
k5.metric("Throughput moyen", f"{metrics['avg_throughput']} Mbps" if metrics["avg_throughput"] is not None else "N/A")

k6, k7, k8 = st.columns(3)
k6.metric("Jitter moyen", f"{metrics['avg_jitter']} ms" if metrics["avg_jitter"] is not None else "N/A")
k7.metric("Latence maximale", f"{metrics['max_latency']} ms" if metrics["max_latency"] is not None else "N/A")
k8.metric("Jitter maximal", f"{metrics['max_jitter']} ms" if metrics["max_jitter"] is not None else "N/A")

# =========================
# TRENDS
# =========================
st.markdown('<div class="section-title">Tendances</div>', unsafe_allow_html=True)
t1, t2, t3 = st.columns(3)
t1.info(f"Latence : {trend_summary['latency_trend']}")
t2.info(f"Jitter : {trend_summary['jitter_trend']}")
t3.info(f"Throughput : {trend_summary['throughput_trend']}")

# =========================
# CHARTS
# =========================
st.markdown('<div class="section-title">Graphiques analytiques</div>', unsafe_allow_html=True)
c1, c2 = st.columns(2)

lat_fig = line_chart_latency(ts_df)
jit_fig = line_chart_jitter(ts_df)
thr_fig = line_chart_throughput(ts_df)
anom_fig = bar_anomaly_distribution(dist_df)
daily_fig = line_daily_comparison(daily_df)

with c1:
    if lat_fig:
        st.plotly_chart(lat_fig, width="stretch")
    if thr_fig:
        st.plotly_chart(thr_fig, width="stretch")

with c2:
    if jit_fig:
        st.plotly_chart(jit_fig, width="stretch")
    if anom_fig:
        st.plotly_chart(anom_fig, width="stretch")

if daily_fig:
    st.plotly_chart(daily_fig, width="stretch")

# =========================
# TOP INTERESTING ROWS
# =========================
st.markdown('<div class="section-title">Top mesures les plus interessantes</div>', unsafe_allow_html=True)
if top_rows:
    top_df = pd.DataFrame(top_rows)
    display_cols = [c for c in [
        "timestamp", "latency_ms", "jitter_ms", "packet_loss_pct",
        "throughput_mbps", "traffic_type", "anomaly_type",
        "anomaly_score", "interest_score", "source_file"
    ] if c in top_df.columns]
    st.dataframe(top_df[display_cols], width="stretch", height=300)
else:
    st.warning("Aucune donnee disponible apres filtrage.")

# =========================
# SELECTED SAMPLE
# =========================
st.markdown('<div class="section-title">Mesure automatiquement selectionnee</div>', unsafe_allow_html=True)
if sample_row is None:
    st.warning("Aucune mesure selectionnable.")
    st.stop()

st.dataframe(pd.DataFrame([{
    "timestamp": str(sample_row.get("timestamp")),
    "latency_ms": sample_row.get("latency_ms"),
    "jitter_ms": sample_row.get("jitter_ms"),
    "packet_loss_pct": sample_row.get("packet_loss_pct"),
    "throughput_mbps": sample_row.get("throughput_mbps"),
    "traffic_type": sample_row.get("traffic_type"),
    "anomaly_type": sample_row.get("anomaly_type"),
    "anomaly_score": sample_row.get("anomaly_score"),
    "interest_score": sample_row.get("interest_score"),
    "source_file": sample_row.get("source_file"),
}]), width="stretch")

# =========================
# LLM TABS
# =========================
st.markdown('<div class="section-title">Analyse LLM</div>', unsafe_allow_html=True)
tab1, tab2, tab3 = st.tabs(["Narrative", "Cause racine", "Q&A"])

narrative_result = ""
root_cause_result = ""

with tab1:
    if st.button("Generer la narrative", key="btn_narrative"):
        with st.spinner("Generation en cours..."):
            narrative_result = generate_narrative(sample_row)
        st.write(narrative_result)

with tab2:
    if st.button("Classifier la cause racine", key="btn_root_cause"):
        with st.spinner("Classification en cours..."):
            root_cause_result = classify_root_cause(sample_row)
        st.code(root_cause_result, language="json")

with tab3:
    question = st.text_input(
        "Pose une question sur les donnees",
        value="Quel est le probleme le plus critique observe dans les donnees et pourquoi ?"
    )
    if st.button("Analyser la question", key="btn_qa"):
        with st.spinner("Analyse en cours..."):
            answer = answer_question(question, filtered_df, incidents_df, top_rows=top_rows)
        st.write(answer)

# =========================
# INCIDENTS TABLE
# =========================
st.markdown('<div class="section-title">Incidents principaux</div>', unsafe_allow_html=True)
if not inc_summary_df.empty:
    st.dataframe(inc_summary_df, width="stretch", height=280)
else:
    st.info("Aucun incident resume disponible.")

# =========================
# AI INSIGHTS
# =========================
st.markdown('<div class="section-title">Insights intelligents LLM + ML</div>', unsafe_allow_html=True)

cluster_summary_df = None
top_atypical_df = None

cluster_summary_path = "outputs/kmeans_pro/cluster_summary.csv"
top_atypical_path = "outputs/isolation_forest_pro/top_atypical_incidents.csv"

if os.path.exists(cluster_summary_path):
    cluster_summary_df = pd.read_csv(cluster_summary_path)

if os.path.exists(top_atypical_path):
    top_atypical_df = pd.read_csv(top_atypical_path)

if st.button("Generer des insights intelligents", key="btn_ai_insights"):
    with st.spinner("Generation des insights en cours..."):
        insights_text = generate_ai_insights(
            sample_row=sample_row,
            cluster_summary_df=cluster_summary_df,
            top_atypical_df=top_atypical_df
        )
    st.write(insights_text)

# =========================
# EXPORT SECTION
# =========================
st.markdown('<div class="section-title">Exporter rapport</div>', unsafe_allow_html=True)

if st.button("Preparer le rapport exportable", key="btn_export_report"):
    with st.spinner("Generation du rapport..."):
        if not narrative_result:
            narrative_result = generate_narrative(sample_row)
        if not root_cause_result:
            root_cause_result = classify_root_cause(sample_row)

        incidents_preview = inc_summary_df.to_string(index=False) if not inc_summary_df.empty else "N/A"
        report_text = build_report_text(
            metrics=metrics,
            trend_summary=trend_summary,
            narrative=narrative_result,
            root_cause=root_cause_result,
            incidents_preview=incidents_preview
        )
        pdf_buffer = build_report_pdf(report_text)

    st.download_button(
        label="Telecharger rapport TXT",
        data=report_text,
        file_name="qos_buddy_report.txt",
        mime="text/plain"
    )

    st.download_button(
        label="Telecharger rapport PDF",
        data=pdf_buffer,
        file_name="qos_buddy_report.pdf",
        mime="application/pdf"
    )

# =========================
# RAW DATA
# =========================
st.markdown('<div class="section-title">Apercu des donnees brutes</div>', unsafe_allow_html=True)
show_cols = [c for c in [
    "timestamp", "latency_ms", "jitter_ms", "packet_loss_pct",
    "throughput_mbps", "traffic_type", "anomaly_flag", "anomaly_type",
    "anomaly_score", "source_file"
] if c in filtered_df.columns]

st.dataframe(filtered_df[show_cols].head(100), width="stretch", height=320)

# =========================
# ANALYSE MACHINE LEARNING
# =========================
st.markdown("## Analyse Machine Learning")

tab_ml1, tab_ml2, tab_ml3 = st.tabs(["K-Means Clustering", "Isolation Forest", "Autoencoder DL"])

with tab_ml1:
    st.subheader("K-Means Clustering des incidents")

    kmeans_dir = "outputs/kmeans_pro"
    cluster_summary_path = os.path.join(kmeans_dir, "cluster_summary.csv")
    metadata_path = os.path.join(kmeans_dir, "metadata.json")
    elbow_path = os.path.join(kmeans_dir, "elbow_method.png")
    silhouette_path = os.path.join(kmeans_dir, "silhouette_scores.png")

    col_btn1, col_btn2 = st.columns([1, 3])

    with col_btn1:
        if st.button("Lancer K-Means", key="run_kmeans_btn"):
            with st.spinner("Execution du modele K-Means..."):
                success, message = run_python_script([
                    "ml_kmeans_pro.py",
                    "data/ml_kmeans_pro.py",
                    "ml_kmeans.py",
                    "data/ml_kmeans.py"
                ])

            if success:
                st.success("K-Means execute avec succes.")
                st.code(message)
            else:
                st.error("Erreur lors de l'execution de K-Means.")
                st.code(message)

    with col_btn2:
        st.info("Le clustering regroupe les incidents en familles homogenes afin de mieux structurer le rapport.")

    if os.path.exists(cluster_summary_path):
        cluster_summary = pd.read_csv(cluster_summary_path)

        st.write("### Resume des clusters")
        st.dataframe(cluster_summary, width="stretch")

        col1, col2 = st.columns(2)

        with col1:
            if os.path.exists(elbow_path):
                st.image(elbow_path, caption="Elbow Method", width="stretch")
            else:
                st.warning("Image Elbow Method introuvable.")

        with col2:
            if os.path.exists(silhouette_path):
                st.image(silhouette_path, caption="Silhouette Score", width="stretch")
            else:
                st.warning("Image Silhouette Score introuvable.")

        if os.path.exists(metadata_path):
            with st.expander("Informations du modele K-Means"):
                with open(metadata_path, "r", encoding="utf-8") as f:
                    metadata = json.load(f)
                st.json(metadata)
    else:
        st.warning("Aucun resultat K-Means disponible pour le moment.")

with tab_ml2:
    st.subheader("Isolation Forest des incidents atypiques")

    iso_dir = "outputs/isolation_forest_pro"
    metadata_path = os.path.join(iso_dir, "metadata.json")
    top_atypical_path = os.path.join(iso_dir, "top_atypical_incidents.csv")
    all_scored_path = os.path.join(iso_dir, "incidents_isolation_scored.csv")
    pca_path = os.path.join(iso_dir, "isolation_pca.png")
    score_dist_path = os.path.join(iso_dir, "isolation_score_distribution.png")

    col_btn1, col_btn2 = st.columns([1, 3])

    with col_btn1:
        if st.button("Lancer Isolation Forest", key="run_iso_btn"):
            with st.spinner("Execution du modele Isolation Forest..."):
                success, message = run_python_script([
                    "ml_isolation_forest_pro.py",
                    "data/ml_isolation_forest_pro.py"
                ])

            if success:
                st.success("Isolation Forest execute avec succes.")
                st.code(message)
            else:
                st.error("Erreur lors de l'execution de Isolation Forest.")
                st.code(message)

    with col_btn2:
        st.info(
            "Isolation Forest met en evidence les incidents atypiques au sein des incidents deja identifies. "
            "Il complete le clustering sans empiéter sur les autres agents."
        )

    if os.path.exists(metadata_path):
        with open(metadata_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)

        c1, c2, c3 = st.columns(3)
        c1.metric("Nombre d'incidents analyses", metadata.get("n_samples", "N/A"))
        c2.metric("Incidents atypiques", metadata.get("n_outliers", "N/A"))
        c3.metric("Ratio atypique", metadata.get("outlier_ratio", "N/A"))

        with st.expander("Informations du modele Isolation Forest"):
            st.json(metadata)

    if os.path.exists(top_atypical_path):
        top_atypical_df = pd.read_csv(top_atypical_path)
        st.write("### Top incidents atypiques")
        st.dataframe(top_atypical_df, width="stretch")

    col1, col2 = st.columns(2)

    with col1:
        if os.path.exists(score_dist_path):
            st.image(score_dist_path, caption="Distribution des scores d'anomalie", width="stretch")

    with col2:
        if os.path.exists(pca_path):
            st.image(pca_path, caption="Projection PCA des incidents atypiques", width="stretch")

    if os.path.exists(all_scored_path):
        scored_df = pd.read_csv(all_scored_path)
        st.write("### Apercu complet des incidents scores")
        show_cols = [c for c in [
            "incident_type",
            "severity",
            "duration_sec",
            "max_score",
            "severity_rank",
            "incident_weight",
            "isolation_score",
            "outlier_flag",
            "outlier_label",
            "source_file"
        ] if c in scored_df.columns]
        st.dataframe(scored_df[show_cols].head(100), width="stretch")
    else:
        st.warning("Aucun resultat Isolation Forest disponible pour le moment.")
with tab_ml3:
    st.subheader("Autoencoder Deep Learning pour validation d'anomalies")

    dl_dir = "outputs/autoencoder_pro"
    metadata_path = os.path.join(dl_dir, "metadata.json")
    results_path = os.path.join(dl_dir, "autoencoder_results.csv")
    top_dl_path = os.path.join(dl_dir, "top_dl_anomalies.csv")
    error_dist_path = os.path.join(dl_dir, "reconstruction_error_distribution.png")
    error_time_path = os.path.join(dl_dir, "reconstruction_error_timeseries.png")
    training_loss_path = os.path.join(dl_dir, "training_loss.png")

    col_btn1, col_btn2 = st.columns([1, 3])

    with col_btn1:
        if st.button("Lancer Autoencoder", key="run_autoencoder_btn"):
            with st.spinner("Execution du modele Autoencoder..."):
                success, message = run_python_script([
                    "ml_autoencoder_pro.py",
                    "data/ml_autoencoder_pro.py",
                    "ml_autoencoder.py",
                    "data/ml_autoencoder.py"
                ])

            if success:
                st.success("Autoencoder execute avec succes.")
                st.code(message)
            else:
                st.error("Erreur lors de l'execution de Autoencoder.")
                st.code(message)

    with col_btn2:
        st.info(
            "L'Autoencoder apprend le comportement normal du reseau a partir des time-series, "
            "puis signale les mesures dont l'erreur de reconstruction est elevee. "
            "Il apporte une validation Deep Learning complementaire sans refaire la prediction du futur."
        )

    metadata = None
    if os.path.exists(metadata_path):
        with open(metadata_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)

        c1, c2, c3 = st.columns(3)
        c1.metric("Mesures analysees", metadata.get("n_total_samples", "N/A"))
        c2.metric("Anomalies DL", metadata.get("n_dl_anomalies", "N/A"))
        c3.metric("Ratio anomalies DL", metadata.get("dl_anomaly_ratio", "N/A"))

        with st.expander("Informations du modele Autoencoder"):
            st.json(metadata)

    top_dl_df = None
    if os.path.exists(top_dl_path):
        top_dl_df = pd.read_csv(top_dl_path).copy()

        if "dl_label" in top_dl_df.columns:
            top_dl_df["dl_label_display"] = top_dl_df["dl_label"].apply(dl_status_badge)

        st.write("### Top anomalies Deep Learning")

        display_cols = [c for c in [
            "timestamp",
            "latency_ms",
            "jitter_ms",
            "packet_loss_pct",
            "throughput_mbps",
            "rsrp_dbm",
            "sinr_db",
            "channel_util_pct",
            "anomaly_type",
            "anomaly_score",
            "reconstruction_error",
            "dl_label"
        ] if c in top_dl_df.columns]

        styled_df = style_dl_table(top_dl_df[display_cols].copy())
        st.dataframe(styled_df, width="stretch")

        st.markdown("### Explication intelligente des anomalies DL")

        col_a, col_b = st.columns([1, 2])

        with col_a:
            selected_idx = st.selectbox(
                "Choisir une anomalie a expliquer",
                options=list(range(len(top_dl_df))),
                format_func=lambda i: f"Ligne {i} - {top_dl_df.iloc[i].get('anomaly_type', 'N/A')} - erreur {round(float(top_dl_df.iloc[i].get('reconstruction_error', 0)), 3)}"
            )

            if st.button("Expliquer cette anomalie", key="btn_explain_one_dl"):
                with st.spinner("Generation de l'explication LLM..."):
                    explanation = explain_dl_anomaly(top_dl_df.iloc[selected_idx])
                st.session_state["dl_explanation_one"] = explanation

        with col_b:
            if "dl_explanation_one" in st.session_state:
                st.write(st.session_state["dl_explanation_one"])

        if st.button("Generer un resume global des anomalies DL", key="btn_explain_global_dl"):
            with st.spinner("Generation du resume global LLM..."):
                global_summary = generate_global_dl_summary(top_dl_df, metadata)
            st.session_state["dl_global_summary"] = global_summary

        if "dl_global_summary" in st.session_state:
            st.write("### Resume global LLM des anomalies Deep Learning")
            st.write(st.session_state["dl_global_summary"])

    col1, col2 = st.columns(2)

    with col1:
        if os.path.exists(error_dist_path):
            st.image(error_dist_path, caption="Distribution des erreurs de reconstruction", width="stretch")

    with col2:
        if os.path.exists(training_loss_path):
            st.image(training_loss_path, caption="Courbe d'apprentissage de l'Autoencoder", width="stretch")

    if os.path.exists(error_time_path):
        st.image(error_time_path, caption="Erreur de reconstruction dans le temps", width="stretch")

    if os.path.exists(results_path):
        dl_df = pd.read_csv(results_path).copy()

        st.write("### Apercu complet des resultats Autoencoder")
        show_cols = [c for c in [
            "timestamp",
            "latency_ms",
            "jitter_ms",
            "packet_loss_pct",
            "throughput_mbps",
            "rsrp_dbm",
            "sinr_db",
            "channel_util_pct",
            "reconstruction_error",
            "dl_anomaly_flag",
            "dl_label",
            "source_file"
        ] if c in dl_df.columns]

        preview_df = dl_df[show_cols].head(100).copy()
        st.dataframe(style_dl_table(preview_df), width="stretch")
    else:
        st.warning("Aucun resultat Autoencoder disponible pour le moment.")