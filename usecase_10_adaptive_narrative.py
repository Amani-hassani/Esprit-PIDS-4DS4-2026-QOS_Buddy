"""
REPORTING AGENT — Usecase 10 : Report Narrative Auto-Évolutif
=============================================================
Le rapport se réécrit automatiquement en temps réel selon les filtres
appliqués dans le dashboard Streamlit.

Chaque changement de filtre (type d'anomalie, fichier source, période)
déclenche une nouvelle génération LLM qui adapte le texte du rapport
au contexte filtré actuel.

Utilise ask_llama() du llm_engine existant.
"""

import hashlib
import pandas as pd
from llm_engine import ask_llama


SYSTEM_PROMPT = """
Tu es un expert réseau télécom intégré au Reporting Agent de QoS Buddy.
Tu génères un rapport narratif dynamique qui s'adapte exactement au contexte
des données filtrées actuellement affichées dans le dashboard.

Règles STRICTES :
- Commence TOUJOURS par "📊 Contexte actuel :" suivi du filtre actif
- Adapte ton analyse UNIQUEMENT aux données du filtre courant
- Si filtre = un type d'anomalie spécifique → concentre-toi sur ce type
- Si filtre = un fichier source → mentionne la période correspondante
- Sois précis avec les chiffres exacts fournis
- Ton professionnel, factuel, concis
- Maximum 200 mots
- Langue : français
- PAS de markdown, PAS de bullet points — texte narratif fluide uniquement
"""


def build_filter_context(
    filtered_df: pd.DataFrame,
    metrics: dict,
    trend_summary: dict,
    sample_row: dict,
    active_filters: dict
) -> str:
    """
    Construit le contexte complet basé sur les filtres actifs
    et les données filtrées courantes.
    """
    # Description des filtres actifs
    filter_desc = []
    if active_filters.get("source_file") and active_filters["source_file"] != "Tous":
        filter_desc.append(f"Fichier : {active_filters['source_file']}")
    if active_filters.get("anomaly_type") and active_filters["anomaly_type"] != "Tous":
        filter_desc.append(f"Type d'anomalie : {active_filters['anomaly_type']}")
    if active_filters.get("traffic_type") and active_filters["traffic_type"] != "Tous":
        filter_desc.append(f"Type de trafic : {active_filters['traffic_type']}")
    if active_filters.get("only_anomalies"):
        filter_desc.append("Mode : anomalies uniquement")

    filter_str = " | ".join(filter_desc) if filter_desc else "Aucun filtre — vue globale complète"

    # Distribution des anomalies dans les données filtrées
    anomaly_dist = ""
    if "anomaly_type" in filtered_df.columns:
        top_anomalies = (
            filtered_df["anomaly_type"]
            .value_counts()
            .head(3)
            .to_dict()
        )
        anomaly_dist = ", ".join([f"{k}: {v}" for k, v in top_anomalies.items()])

    # Incident le plus critique dans le filtre courant
    critical_incident = "N/A"
    if sample_row:
        critical_incident = (
            f"{sample_row.get('anomaly_type', 'N/A')} "
            f"(score {sample_row.get('anomaly_score', 'N/A')}, "
            f"latence {sample_row.get('latency_ms', 'N/A')}ms)"
        )

    return f"""
FILTRES ACTIFS : {filter_str}

DONNÉES FILTRÉES ACTUELLES :
- Échantillons visibles : {len(filtered_df)}
- Incidents totaux : {metrics.get('incidents', 0)}
- Anomalies détectées : {metrics.get('anomalies', 0)}
- Latence moyenne : {metrics.get('avg_latency', 'N/A')} ms
- Latence maximale : {metrics.get('max_latency', 'N/A')} ms
- Jitter moyen : {metrics.get('avg_jitter', 'N/A')} ms
- Throughput moyen : {metrics.get('avg_throughput', 'N/A')} Mbps
- Tendance latence : {trend_summary.get('latency_trend', 'N/A')}
- Tendance jitter : {trend_summary.get('jitter_trend', 'N/A')}
- Tendance throughput : {trend_summary.get('throughput_trend', 'N/A')}
- Distribution anomalies : {anomaly_dist or 'N/A'}
- Incident le plus critique : {critical_incident}

Génère le rapport narratif adapté à ce contexte filtré.
""".strip()


def compute_filter_hash(active_filters: dict, metrics: dict) -> str:
    """
    Calcule un hash unique basé sur les filtres + métriques.
    Utilisé pour détecter si le contexte a changé et éviter
    de régénérer inutilement.
    """
    key = str(active_filters) + str(metrics.get("samples")) + \
          str(metrics.get("anomalies")) + str(metrics.get("avg_latency"))
    return hashlib.md5(key.encode()).hexdigest()[:8]


def generate_adaptive_narrative(
    filtered_df: pd.DataFrame,
    metrics: dict,
    trend_summary: dict,
    sample_row: dict,
    active_filters: dict
) -> str:
    """
    Génère le rapport narratif adapté au contexte filtré courant.
    Retourne le texte du rapport.
    """
    context = build_filter_context(
        filtered_df, metrics, trend_summary, sample_row, active_filters
    )
    return ask_llama(SYSTEM_PROMPT, context)


# ─────────────────────────────────────────────
# Widget Streamlit
# ─────────────────────────────────────────────

def render_adaptive_narrative_widget(
    filtered_df: pd.DataFrame,
    metrics: dict,
    trend_summary: dict,
    sample_row: dict,
    active_filters: dict
):
    """
    Widget Streamlit pour le rapport narratif auto-évolutif.

    Ce widget détecte automatiquement les changements de filtres
    et régénère le rapport si le contexte a changé.

    Usage dans streamlit_app.py :
        from usecase_10_adaptive_narrative import render_adaptive_narrative_widget
        render_adaptive_narrative_widget(
            filtered_df, metrics, trend_summary,
            sample_row, active_filters
        )
    """
    try:
        import streamlit as st
    except ImportError:
        return

    st.markdown(
        '<div class="ml-badge">⚡ LLM Streaming · Rapport Auto-Évolutif · Temps réel</div>',
        unsafe_allow_html=True
    )
    st.markdown("**Narrative Auto-Évolutive** — Le rapport se réécrit automatiquement selon les filtres actifs.")

    # Calcul du hash courant
    current_hash = compute_filter_hash(active_filters, metrics)
    last_hash    = st.session_state.get("adaptive_narrative_hash", "")

    # Description des filtres actifs
    filter_parts = []
    if active_filters.get("source_file", "Tous") != "Tous":
        filter_parts.append(f"📁 {active_filters['source_file']}")
    if active_filters.get("anomaly_type", "Tous") != "Tous":
        filter_parts.append(f"⚠️ {active_filters['anomaly_type']}")
    if active_filters.get("traffic_type", "Tous") != "Tous":
        filter_parts.append(f"🌐 {active_filters['traffic_type']}")
    if active_filters.get("only_anomalies"):
        filter_parts.append("🔴 Anomalies uniquement")

    filter_display = " · ".join(filter_parts) if filter_parts else "🌍 Vue globale — aucun filtre actif"

    # Bandeau contexte actif
    context_changed = current_hash != last_hash
    badge_color = "#f59e0b" if context_changed else "#10b981"
    badge_text  = "⟳ Contexte modifié — rapport à régénérer" if context_changed else "✓ Rapport à jour"

    st.markdown(f"""
    <div style="display:flex;justify-content:space-between;align-items:center;
                padding:10px 16px;background:var(--surface);
                border:1px solid var(--border);border-radius:10px;margin-bottom:12px">
        <div style="font-size:0.85rem;font-weight:600">{filter_display}</div>
        <div style="font-size:0.75rem;font-weight:700;color:{badge_color}">{badge_text}</div>
    </div>
    """, unsafe_allow_html=True)

    # Boutons
    col_auto, col_manual, col_clear = st.columns([2, 2, 1])

    with col_auto:
        auto_regen = st.toggle(
            "🔄 Régénération automatique",
            value=False,
            key="auto_regen_toggle",
            help="Régénère automatiquement à chaque changement de filtre"
        )

    with col_manual:
        manual_btn = st.button(
            "⚡ Générer le rapport",
            key="btn_adaptive_narrative",
            type="primary"
        )

    with col_clear:
        if st.button("🗑️", key="btn_clear_narrative", help="Effacer"):
            st.session_state.pop("adaptive_narrative_text", None)
            st.session_state.pop("adaptive_narrative_hash", None)
            st.rerun()

    # Déclencher la génération
    should_generate = manual_btn or (auto_regen and context_changed)

    if should_generate:
        with st.spinner("✍️ LLM en train de réécrire le rapport..."):
            narrative = generate_adaptive_narrative(
                filtered_df, metrics, trend_summary,
                sample_row, active_filters
            )
        st.session_state["adaptive_narrative_text"] = narrative
        st.session_state["adaptive_narrative_hash"] = current_hash
        if auto_regen and context_changed:
            st.rerun()

    # Affichage du rapport
    if "adaptive_narrative_text" in st.session_state:
        narrative_text = st.session_state["adaptive_narrative_text"]

        st.markdown(f"""
        <div style="background:var(--surface);border:1px solid var(--border);
                    border-left:4px solid #3b82f6;border-radius:12px;
                    padding:20px 24px;margin-top:8px;
                    font-size:0.93rem;line-height:1.85;color:var(--text)">
            {narrative_text}
        </div>
        """, unsafe_allow_html=True)

        # Métadonnées
        st.markdown(f"""
        <div style="display:flex;gap:16px;margin-top:8px;font-size:0.75rem;color:#475569">
            <span>🔑 Hash contexte : <code>{st.session_state.get('adaptive_narrative_hash','N/A')}</code></span>
            <span>📊 {len(filtered_df):,} échantillons analysés</span>
            <span>⚠️ {metrics.get('anomalies', 0)} anomalies</span>
        </div>
        """, unsafe_allow_html=True)

    else:
        st.markdown("""
        <div style="text-align:center;padding:40px;color:#475569;
                    background:var(--surface);border:1px dashed var(--border);
                    border-radius:12px;margin-top:8px">
            <div style="font-size:2rem;margin-bottom:8px">⚡</div>
            <div style="font-weight:600">Rapport non généré</div>
            <div style="font-size:0.82rem;margin-top:4px">
                Clique sur "Générer le rapport" ou active la régénération automatique
            </div>
        </div>
        """, unsafe_allow_html=True)