"""
REPORTING AGENT — Usecase 7 : Benchmark Sectoriel Automatique
==============================================================
Compare automatiquement les KPIs mesurés aux standards ITU-T et 3GPP,
puis génère une narrative via ask_llama() du llm_engine existant.

Standards intégrés :
  ITU-T G.114   — latence one-way < 150ms (voix)
  ITU-T Y.1541  — jitter < 50ms (temps réel)
  ITU-T E.501   — packet loss < 0.5%
  ITU-T P.10    — MOS > 3.6 (qualité voix)
  3GPP TS 22.261— throughput min LTE
  3GPP TS 36.214— SINR, RSRP seuils LTE
  3GPP TS 36.321— CQI minimum
"""

import pandas as pd
from dataclasses import dataclass
from typing import Optional
from llm_engine import ask_llama


SYSTEM_PROMPT = """
Tu es un expert qualité réseau télécom spécialisé en conformité aux standards ITU-T et 3GPP.
Tu analyses les KPIs d'un réseau mobile et génères un rapport de benchmark normatif.
Tu réponds uniquement en français.
Tes analyses sont précises, factuelles, orientées action.
Tu cites toujours la référence normative complète (ex: ITU-T G.114).
Style : professionnel, structuré, adapté à un rapport technique.
"""


# ─────────────────────────────────────────────
# Référentiel des standards
# ─────────────────────────────────────────────

@dataclass
class Standard:
    reference: str          # ex: "ITU-T G.114"
    metric_key: str         # clé dans le dict KPIs
    description: str        # description humaine
    green_threshold: float  # valeur = conformité totale
    yellow_threshold: float # valeur = zone limite
    unit: str
    higher_is_better: bool = False


STANDARDS = [
    Standard("ITU-T G.114",    "avg_latency",   "Latence one-way (voix sur IP)",
              150,  200,   "ms"),
    Standard("ITU-T Y.1541",   "avg_jitter",    "Gigue max services temps réel",
              50,   80,    "ms"),
    Standard("ITU-T E.501",    "packet_loss",   "Taux de perte de paquets max",
              0.5,  1.0,   "%"),
    Standard("ITU-T P.10",     "mos_score",     "MOS qualité voix (1-5)",
              4.0,  3.6,   "",    higher_is_better=True),
    Standard("3GPP TS 22.261", "avg_throughput","Débit minimum LTE zone couverte",
              10,   5,     "Mbps", higher_is_better=True),
    Standard("3GPP TS 36.214", "avg_sinr",      "SINR minimum LTE (bonne modulation)",
              10,   0,     "dB",  higher_is_better=True),
    Standard("3GPP TS 36.214", "avg_rsrp",      "RSRP minimum couverture LTE",
              -80,  -100,  "dBm", higher_is_better=True),
    Standard("3GPP TS 36.321", "avg_cqi",       "CQI minimum débit satisfaisant (0-15)",
              9,    6,     "",    higher_is_better=True),
]

STATUS_GREEN  = "✅ Conforme"
STATUS_YELLOW = "⚠️  Limite"
STATUS_RED    = "🔴 Non conforme"


# ─────────────────────────────────────────────
# Extraction des KPIs depuis le DataFrame
# ─────────────────────────────────────────────

def extract_kpis_from_df(df: pd.DataFrame) -> dict:
    """
    Calcule les KPIs moyens depuis le DataFrame timeseries.
    Appelé avec df (le DataFrame déjà chargé et filtré dans streamlit_app.py).
    """
    kpis = {}

    def mean_col(col):
        if col in df.columns:
            s = pd.to_numeric(df[col], errors="coerce").dropna()
            return round(s.mean(), 2) if not s.empty else None
        return None

    kpis["avg_latency"]    = mean_col("latency_ms")
    kpis["avg_jitter"]     = mean_col("jitter_ms")
    kpis["avg_throughput"] = mean_col("throughput_mbps")
    kpis["packet_loss"]    = mean_col("packet_loss_pct")
    kpis["avg_sinr"]       = mean_col("sinr_db")
    kpis["avg_rsrp"]       = mean_col("rsrp_dbm")
    kpis["avg_cqi"]        = mean_col("cqi")
    kpis["mos_score"]      = mean_col("mos_estimate")

    return kpis


# ─────────────────────────────────────────────
# Moteur d'évaluation
# ─────────────────────────────────────────────

def evaluate_kpis(kpis: dict) -> list[dict]:
    """
    Évalue chaque KPI disponible contre son standard.
    Retourne une liste de résultats enrichis.
    """
    results = []
    for std in STANDARDS:
        value = kpis.get(std.metric_key)
        if value is None:
            continue  # métrique absente des données

        # Calcul du statut
        if std.higher_is_better:
            if value >= std.green_threshold:
                status = STATUS_GREEN
            elif value >= std.yellow_threshold:
                status = STATUS_YELLOW
            else:
                status = STATUS_RED
            deviation = round(((value - std.green_threshold) / abs(std.green_threshold)) * 100, 1)
        else:
            if value <= std.green_threshold:
                status = STATUS_GREEN
            elif value <= std.yellow_threshold:
                status = STATUS_YELLOW
            else:
                status = STATUS_RED
            deviation = round(((value - std.green_threshold) / abs(std.green_threshold)) * 100, 1)

        results.append({
            "reference":   std.reference,
            "metric":      std.metric_key,
            "description": std.description,
            "measured":    value,
            "unit":        std.unit,
            "threshold":   std.green_threshold,
            "direction":   "≥" if std.higher_is_better else "≤",
            "status":      status,
            "deviation":   deviation,
        })
    return results


def compute_compliance_score(results: list[dict]) -> dict:
    """Calcule le score global de conformité en %."""
    total   = len(results)
    if total == 0:
        return {"score": 0, "green": 0, "yellow": 0, "red": 0, "total": 0}
    green   = sum(1 for r in results if r["status"] == STATUS_GREEN)
    yellow  = sum(1 for r in results if r["status"] == STATUS_YELLOW)
    red     = total - green - yellow
    score   = round(((green + yellow * 0.5) / total) * 100, 1)
    return {"score": score, "green": green, "yellow": yellow, "red": red, "total": total}


# ─────────────────────────────────────────────
# Génération narrative LLM
# ─────────────────────────────────────────────

def build_benchmark_prompt(results: list[dict], compliance: dict) -> str:
    lines = ["Tableau de benchmark réseau :"]
    lines.append(f"{'Référence':<20} {'Métrique':<18} {'Mesuré':>10} {'Seuil':>10}  {'Statut'}")
    lines.append("-" * 80)
    for r in results:
        seuil_str = f"{r['direction']}{r['threshold']}{r['unit']}"
        lines.append(
            f"{r['reference']:<20} {r['description'][:17]:<18} "
            f"{r['measured']:>8.1f}{r['unit']:<3} "
            f"{seuil_str:>10}  {r['status']}"
        )

    lines.append("")
    lines.append(
        f"Score de conformité global : {compliance['score']}% "
        f"({compliance['green']} conformes, {compliance['yellow']} limites, "
        f"{compliance['red']} non conformes / {compliance['total']} métriques évaluées)"
    )

    user_prompt = f"""
{chr(10).join(lines)}

Génère une analyse benchmark structurée avec exactement ces 4 sections :

## 🔴 Non-conformités critiques
Pour chaque métrique en rouge : valeur mesurée exacte, seuil normatif dépassé,
référence complète, impact concret sur les utilisateurs finaux.

## ⚠️ Métriques en zone limite
Pour chaque métrique en orange : risque si la tendance se dégrade.

## ✅ Points conformes
Synthèse courte des métriques respectant les normes.

## 📊 Verdict global
Score de conformité, positionnement par rapport aux standards du secteur télécom,
et recommandation prioritaire en 1 phrase.

Utilise les valeurs numériques exactes. Cite les références normatives complètes.
"""
    return user_prompt


def generate_benchmark_narrative(results: list[dict], compliance: dict) -> str:
    """Génère la narrative LLM du benchmark."""
    if not results:
        return "Aucune métrique disponible pour le benchmark sectoriel."
    user_prompt = build_benchmark_prompt(results, compliance)
    return ask_llama(SYSTEM_PROMPT, user_prompt)


# ─────────────────────────────────────────────
# Fonction principale (pipeline complet)
# ─────────────────────────────────────────────

def run_benchmark(df: pd.DataFrame) -> dict:
    """
    Pipeline complet : extraction KPIs → évaluation → score → narrative.
    À appeler avec le DataFrame filtré du dashboard.

    Retourne :
    {
        "kpis":       dict des KPIs calculés,
        "results":    liste des évaluations par standard,
        "compliance": dict du score global,
        "narrative":  texte LLM généré
    }
    """
    kpis       = extract_kpis_from_df(df)
    results    = evaluate_kpis(kpis)
    compliance = compute_compliance_score(results)
    narrative  = generate_benchmark_narrative(results, compliance)

    return {
        "kpis":       kpis,
        "results":    results,
        "compliance": compliance,
        "narrative":  narrative,
    }