"""
REPORTING AGENT — Usecase 6 : Tone Adaptation
==============================================
Génère le même rapport en 3 versions adaptées au destinataire,
en utilisant ask_llama() du llm_engine existant.

- ENGINEER  : Notification SMS technique (3 lignes max, métriques brutes)
- MANAGER   : Email exécutif (impact business, synthèse)
- DIRECTOR  : Rapport structuré complet (stratégique, analytique)
"""

from llm_engine import ask_llama


# ─────────────────────────────────────────────
# Prompts système par audience
# ─────────────────────────────────────────────

SYSTEM_ENGINEER = """
Tu es un expert réseau télécom qui envoie une alerte technique à un ingénieur terrain.
Style : ultra-concis, direct, métriques brutes.
Format : 3 lignes maximum, comme un SMS ou une notification push.
Inclure : nœud affecté, métriques critiques, action immédiate.
Langue : français. Pas de politesse, pas d'introduction. Texte brut uniquement.
"""

SYSTEM_MANAGER = """
Tu es un expert réseau télécom qui rédige un email pour un responsable opérationnel.
Style : professionnel, synthétique, orienté impact business.
Format : email court (5-7 lignes) avec une ligne d'objet, un corps, une action requise.
Inclure : synthèse de la situation, impact service client, recommandation priorisée.
Langue : français. Pas de jargon radio, traduis en impact métier (clients impactés, SLA).
"""

SYSTEM_DIRECTOR = """
Tu es un expert réseau télécom qui présente un rapport au directeur technique.
Style : structuré, analytique, stratégique. Ton confiant et factuel.
Format : rapport structuré avec 4 sections : Situation / Analyse / Risques / Recommandations.
Inclure : contexte, tendances observées, risques à court terme, actions prioritaires chiffrées.
Langue : français. Adapté à un décideur, pas un technicien. Maximum 15 lignes.
"""


# ─────────────────────────────────────────────
# Construction du contexte partagé
# ─────────────────────────────────────────────

def build_report_context(metrics: dict, trend_summary: dict, sample_row: dict,
                          cluster_summary_df=None, top_atypical_df=None) -> str:
    """
    Construit le contexte commun à partir des données déjà calculées
    par les modules existants du Reporting Agent.
    """
    anomalies = metrics.get("anomalies", "N/A")
    samples   = metrics.get("samples", "N/A")
    incidents = metrics.get("incidents", "N/A")

    avg_lat  = metrics.get("avg_latency", "N/A")
    avg_jit  = metrics.get("avg_jitter", "N/A")
    avg_thr  = metrics.get("avg_throughput", "N/A")
    max_lat  = metrics.get("max_latency", "N/A")
    max_jit  = metrics.get("max_jitter", "N/A")

    lat_trend = trend_summary.get("latency_trend", "N/A")
    jit_trend = trend_summary.get("jitter_trend", "N/A")
    thr_trend = trend_summary.get("throughput_trend", "N/A")

    # Mesure la plus critique (sample_row)
    anomaly_type  = sample_row.get("anomaly_type", "N/A")
    anomaly_score = sample_row.get("anomaly_score", "N/A")
    timestamp     = sample_row.get("timestamp", "N/A")
    node          = sample_row.get("node_id", sample_row.get("source_file", "N/A"))

    # Cluster dominant
    cluster_context = "Non disponible"
    if cluster_summary_df is not None and not cluster_summary_df.empty:
        if "cluster_label" in cluster_summary_df.columns and "cluster_size" in cluster_summary_df.columns:
            dominant = cluster_summary_df.sort_values("cluster_size", ascending=False).iloc[0]
            cluster_context = (
                f"{dominant.get('cluster_label', 'N/A')} "
                f"({int(dominant.get('cluster_size', 0))} incidents, "
                f"score moyen {round(float(dominant.get('max_score', 0)), 2)})"
            )

    # Incident atypique le plus critique
    atypical_context = "Non disponible"
    if top_atypical_df is not None and not top_atypical_df.empty:
        worst = top_atypical_df.iloc[0]
        atypical_context = (
            f"{worst.get('incident_type', 'N/A')} — "
            f"sévérité {worst.get('severity', 'N/A')} — "
            f"durée {worst.get('duration_sec', 'N/A')}s — "
            f"score isolation {round(float(worst.get('isolation_score', 0)), 3)}"
        )

    return f"""
DONNÉES DU RAPPORT QoS BUDDY

Période analysée : données en cours
Samples collectés : {samples}
Incidents détectés : {incidents}
Anomalies flaggées : {anomalies}

KPIs réseau :
- Latence moyenne : {avg_lat} ms | max : {max_lat} ms | tendance : {lat_trend}
- Jitter moyen    : {avg_jit} ms | max : {max_jit} ms | tendance : {jit_trend}
- Throughput moyen: {avg_thr} Mbps | tendance : {thr_trend}

Incident le plus critique :
- Timestamp     : {timestamp}
- Type anomalie : {anomaly_type}
- Score         : {anomaly_score}
- Nœud          : {node}

Profil de cluster dominant : {cluster_context}
Incident le plus atypique  : {atypical_context}
""".strip()


# ─────────────────────────────────────────────
# Fonctions de génération par audience
# ─────────────────────────────────────────────

def generate_engineer_report(context: str) -> str:
    user_prompt = f"""
{context}

Génère une alerte SMS technique pour l'ingénieur terrain.
Maximum 3 lignes. Métriques clés + nœud + action immédiate.
"""
    return ask_llama(SYSTEM_ENGINEER, user_prompt)


def generate_manager_report(context: str) -> str:
    user_prompt = f"""
{context}

Rédige un email exécutif pour le responsable opérationnel.
Format : ligne d'objet sur la 1ère ligne, puis le corps du message.
Synthèse impact business + recommandation.
"""
    return ask_llama(SYSTEM_MANAGER, user_prompt)


def generate_director_report(context: str) -> str:
    user_prompt = f"""
{context}

Génère un rapport structuré pour le directeur technique.
Sections : Situation / Analyse / Risques / Recommandations.
Ton stratégique et analytique.
"""
    return ask_llama(SYSTEM_DIRECTOR, user_prompt)


def generate_all_tones(metrics: dict, trend_summary: dict, sample_row: dict,
                        cluster_summary_df=None, top_atypical_df=None) -> dict:
    """
    Génère les 3 versions du rapport.
    Retourne : { "engineer": "...", "manager": "...", "director": "..." }
    """
    context = build_report_context(
        metrics, trend_summary, sample_row,
        cluster_summary_df, top_atypical_df
    )
    return {
        "engineer" : generate_engineer_report(context),
        "manager"  : generate_manager_report(context),
        "director" : generate_director_report(context),
    }
