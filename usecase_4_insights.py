from llm_engine import ask_llama


SYSTEM_PROMPT = """
Tu es un expert reseau telecom integre au Reporting Agent de QoS Buddy.
Tu analyses des resultats de clustering, des incidents atypiques et des metriques reseau.
Tu ne fais pas de detection principale ni de prediction future : tu enrichis le reporting.
Tu reponds uniquement en francais.
Tu dois produire une reponse claire, professionnelle, structuree et concise.

Structure obligatoire :
1. Insight principal
2. Lecture des clusters
3. Lecture des incidents atypiques
4. Recommandation

Contraintes :
- Ne pas inventer d'informations absentes
- Rester coherent avec les donnees fournies
- Si une information manque, le signaler clairement
- Style professionnel, adapte a un dashboard ou un rapport
"""


def build_cluster_context(cluster_summary_df) -> str:
    if cluster_summary_df is None or cluster_summary_df.empty:
        return "Aucun resultat de clustering disponible."

    cols = [c for c in [
        "cluster_id",
        "duration_sec",
        "max_score",
        "severity_rank",
        "incident_weight",
        "cluster_size",
        "dominant_incident_type",
        "dominant_severity",
        "cluster_label"
    ] if c in cluster_summary_df.columns]

    return cluster_summary_df[cols].to_string(index=False)


def build_isolation_context(top_atypical_df) -> str:
    if top_atypical_df is None or top_atypical_df.empty:
        return "Aucun incident atypique disponible."

    cols = [c for c in [
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
    ] if c in top_atypical_df.columns]

    return top_atypical_df[cols].head(10).to_string(index=False)


def build_sample_context(sample_row: dict) -> str:
    if not sample_row:
        return "Aucune mesure reseau selectionnee."

    lines = [
        f"Timestamp: {sample_row.get('timestamp', 'N/A')}",
        f"Latency ms: {sample_row.get('latency_ms', 'N/A')}",
        f"Jitter ms: {sample_row.get('jitter_ms', 'N/A')}",
        f"Packet loss pct: {sample_row.get('packet_loss_pct', 'N/A')}",
        f"Throughput mbps: {sample_row.get('throughput_mbps', 'N/A')}",
        f"Traffic type: {sample_row.get('traffic_type', 'N/A')}",
        f"Anomaly type: {sample_row.get('anomaly_type', 'N/A')}",
        f"Anomaly score: {sample_row.get('anomaly_score', 'N/A')}",
        f"Source file: {sample_row.get('source_file', 'N/A')}",
    ]
    return "\n".join(lines)


def generate_ai_insights(sample_row: dict, cluster_summary_df=None, top_atypical_df=None) -> str:
    cluster_context = build_cluster_context(cluster_summary_df)
    isolation_context = build_isolation_context(top_atypical_df)
    sample_context = build_sample_context(sample_row)

    user_prompt = f"""
Contexte de la mesure reseau selectionnee :
{sample_context}

Resume du clustering K-Means :
{cluster_context}

Resume des incidents atypiques (Isolation Forest) :
{isolation_context}

Genere une analyse intelligente pour le dashboard du Reporting Agent.
La reponse doit contenir :
1. Insight principal
2. Lecture des clusters
3. Lecture des incidents atypiques
4. Recommandation
"""

    return ask_llama(SYSTEM_PROMPT, user_prompt)