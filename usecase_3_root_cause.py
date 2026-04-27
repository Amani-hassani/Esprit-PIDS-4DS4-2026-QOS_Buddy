from llm_engine import ask_llama
from prompt_builder import timeseries_row_to_context


def preclassify_root_cause(row: dict) -> str:
    def to_float(value, default=None):
        try:
            if value is None or value == "N/A":
                return default
            return float(value)
        except Exception:
            return default

    throughput = to_float(row.get("throughput_mbps"))
    bandwidth_util = to_float(row.get("bandwidth_util_pct"))
    rssi = to_float(row.get("rssi_dbm"))
    rsrp = to_float(row.get("rsrp_dbm"))
    sinr = to_float(row.get("sinr_db"))
    channel_util = to_float(row.get("channel_util_pct"))
    packet_loss = to_float(row.get("packet_loss_pct"))
    anomaly_type = str(row.get("anomaly_type", "")).lower()

    if throughput is not None and throughput == 0:
        if bandwidth_util is not None and bandwidth_util == 0:
            return "D) Probleme applicatif"

    if packet_loss is not None and packet_loss > 5:
        return "C) Defaillance transport"

    if rssi is not None and rssi < -85:
        return "A) Probleme de couverture radio"

    if rsrp is not None and rsrp < -120:
        return "A) Probleme de couverture radio"

    if sinr is not None and sinr < 5:
        return "E) Interference canal"

    if channel_util is not None and channel_util > 85:
        return "B) Congestion reseau"

    if "low_throughput" in anomaly_type:
        return "D) Probleme applicatif"

    return "C) Defaillance transport"


SYSTEM_PROMPT = """
Tu es un classifieur de cause racine réseau.

Tu dois choisir UNE seule classe parmi :
A) Probleme de couverture radio
B) Congestion reseau
C) Defaillance transport
D) Probleme applicatif
E) Interference canal

Tu reçois aussi une hypothèse initiale calculée par des règles réseau.
Tu dois t'appuyer fortement dessus sauf si les données la contredisent clairement.

Tu réponds STRICTEMENT au format JSON suivant :
{
  "classe": "...",
  "confiance": 0,
  "explication": "..."
}

Règles :
- confiance = entier entre 0 et 100
- pas d'invention
- pas de markdown
"""


def classify_root_cause(row: dict) -> str:
    context = timeseries_row_to_context(row)
    initial_guess = preclassify_root_cause(row)

    user_prompt = f"""
Mesure réseau :
{context}

Hypothèse initiale fondée sur règles métier :
{initial_guess}

Choisis la cause racine finale la plus probable.
"""
    return ask_llama(SYSTEM_PROMPT, user_prompt)