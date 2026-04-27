import pandas as pd
from llm_engine import ask_llama


SYSTEM_PROMPT = """
Tu es un expert reseau telecom integre au Reporting Agent de QoS Buddy.
Tu expliques des anomalies reseau detectees par un modele Deep Learning.
Tu reponds uniquement en francais.
Tu dois produire une reponse courte, claire, professionnelle et exploitable dans un dashboard.

Structure obligatoire :
1. Resume de l'anomalie
2. Cause probable
3. Impact possible
4. Recommandation

Contraintes :
- Ne pas inventer d'informations absentes
- Rester coherent avec les valeurs fournies
- Ne pas utiliser un ton vague
- Maximum 8 lignes
"""


def build_dl_context(row: pd.Series) -> str:
    fields = [
        f"Timestamp: {row.get('timestamp', 'N/A')}",
        f"Latency ms: {row.get('latency_ms', 'N/A')}",
        f"Jitter ms: {row.get('jitter_ms', 'N/A')}",
        f"Packet loss pct: {row.get('packet_loss_pct', 'N/A')}",
        f"Throughput mbps: {row.get('throughput_mbps', 'N/A')}",
        f"RSRP dBm: {row.get('rsrp_dbm', 'N/A')}",
        f"SINR dB: {row.get('sinr_db', 'N/A')}",
        f"Channel util pct: {row.get('channel_util_pct', 'N/A')}",
        f"Anomaly type: {row.get('anomaly_type', 'N/A')}",
        f"Anomaly score: {row.get('anomaly_score', 'N/A')}",
        f"Reconstruction error: {row.get('reconstruction_error', 'N/A')}",
        f"DL label: {row.get('dl_label', 'N/A')}",
        f"Source file: {row.get('source_file', 'N/A')}",
    ]
    return "\n".join(fields)


def explain_dl_anomaly(row: pd.Series) -> str:
    context = build_dl_context(row)

    user_prompt = f"""
Voici une anomalie detectee par l'Autoencoder Deep Learning :

{context}

Explique cette anomalie pour le dashboard du Reporting Agent.
"""

    return ask_llama(SYSTEM_PROMPT, user_prompt)


def generate_global_dl_summary(top_dl_df: pd.DataFrame, metadata: dict | None = None) -> str:
    if top_dl_df is None or top_dl_df.empty:
        return "Aucune anomalie Deep Learning n'est disponible pour le moment."

    cols = [c for c in [
        "timestamp",
        "latency_ms",
        "jitter_ms",
        "packet_loss_pct",
        "throughput_mbps",
        "anomaly_type",
        "reconstruction_error",
        "dl_label"
    ] if c in top_dl_df.columns]

    context = top_dl_df[cols].head(10).to_string(index=False)

    metadata_text = ""
    if metadata:
        metadata_text = (
            f"Nombre total de mesures: {metadata.get('n_total_samples', 'N/A')}\n"
            f"Nombre anomalies DL: {metadata.get('n_dl_anomalies', 'N/A')}\n"
            f"Ratio anomalies DL: {metadata.get('dl_anomaly_ratio', 'N/A')}\n"
            f"Seuil 95: {metadata.get('threshold_95', 'N/A')}\n"
            f"Seuil 99: {metadata.get('threshold_99', 'N/A')}\n"
        )

    user_prompt = f"""
Voici un resume des principales anomalies detectees par l'Autoencoder Deep Learning.

Statistiques globales :
{metadata_text}

Top anomalies :
{context}

Genere :
1. Un constat global
2. Les patterns les plus visibles
3. Le niveau de criticite
4. Une recommandation globale

Maximum 10 lignes.
"""

    return ask_llama(SYSTEM_PROMPT, user_prompt)