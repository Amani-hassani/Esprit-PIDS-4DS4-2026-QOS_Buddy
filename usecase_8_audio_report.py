"""
REPORTING AGENT — Usecase 8 : Rapport Audio TTS
================================================
Génère un briefing audio de 60 secondes du rapport réseau.
- Ingénieur  : français, ton technique, métriques brutes
- Manager    : français, ton business, synthèse
- Directeur  : anglais, ton exécutif, stratégique

Moteur : gTTS (Google Text-to-Speech, gratuit)
Output : fichier .mp3 jouable directement dans Streamlit
"""

import os
import re
from io import BytesIO
from pathlib import Path

from gtts import gTTS
from llm_engine import ask_llama


OUTPUT_DIR = Path("outputs/audio_reports")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ── Langues par audience ──
AUDIENCE_CONFIG = {
    "engineer":  {"lang": "fr", "label": "👷 Ingénieur",  "flag": "🇫🇷"},
    "manager":   {"lang": "fr", "label": "📊 Manager",    "flag": "🇫🇷"},
    "director":  {"lang": "en", "label": "🏢 Directeur",  "flag": "🇬🇧"},
}

# ── Prompts système par audience ──
SYSTEM_PROMPTS = {
    "engineer": """
Tu es un expert réseau télécom. Génère un briefing audio ORAL de 60 secondes en français
pour un ingénieur terrain. Style : direct, technique, métriques précises.
IMPORTANT : Texte parlé uniquement. Pas de puces, pas de titres, pas de markdown.
Commence directement par les faits. Maximum 120 mots.
""",
    "manager": """
Tu es un expert réseau télécom. Génère un briefing audio ORAL de 60 secondes en français
pour un responsable opérationnel. Style : clair, impact business, recommandation finale.
IMPORTANT : Texte parlé uniquement. Pas de puces, pas de titres, pas de markdown.
Commence par une phrase d'accroche. Maximum 120 mots.
""",
    "director": """
You are a senior network telecom expert. Generate a 60-second ORAL audio briefing in English
for the technical director. Style: executive, strategic, key numbers only.
IMPORTANT: Spoken text only. No bullets, no titles, no markdown.
Start with the overall network status. Maximum 120 words.
""",
}

USER_PROMPT_TEMPLATE = {
    "engineer": """
Données réseau :
- Incidents : {total_incidents} total | {critical_count} critiques | {high_count} hauts
- Latence moyenne : {avg_latency} ms | max : {max_latency} ms
- Jitter moyen : {avg_jitter} ms
- Throughput moyen : {avg_throughput} Mbps
- Anomalies : {anomalies}
- Tendance latence : {latency_trend}
- Incident le plus critique : {anomaly_type} (score {anomaly_score})
- Cause principale : {top_root_cause}

Génère le briefing audio oral en français pour l'ingénieur.
""",
    "manager": """
Données réseau :
- Total incidents : {total_incidents} dont {critical_count} critiques
- Score santé réseau estimé : {nhs_estimate}/100
- Latence moyenne : {avg_latency} ms (seuil ITU-T : 150ms)
- Throughput moyen : {avg_throughput} Mbps
- Tendances : latence {latency_trend}, throughput {throughput_trend}
- Incident dominant : {anomaly_type}
- Action recommandée : {top_root_cause}

Génère le briefing audio oral en français pour le manager.
""",
    "director": """
Network data:
- Total incidents: {total_incidents} ({critical_count} critical, {high_count} high)
- Average latency: {avg_latency} ms | Average throughput: {avg_throughput} Mbps
- Anomalies detected: {anomalies}
- Network health estimate: {nhs_estimate}/100
- Latency trend: {latency_trend}
- Main issue: {anomaly_type}
- Root cause: {top_root_cause}

Generate the executive audio briefing in English for the director.
""",
}


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def clean_for_tts(text: str) -> str:
    """Nettoie le texte pour la synthèse vocale — supprime markdown, symboles."""
    text = re.sub(r"[#*_`>\-]+", "", text)
    text = re.sub(r"\n{2,}", ". ", text)
    text = re.sub(r"\n", " ", text)
    text = re.sub(r"\s{2,}", " ", text)
    text = re.sub(r"[^\w\s\.,;:!?'éèêëàâùûüîïôœçÉÈÊËÀÂÙÛÜÎÏÔŒÇ%-]", "", text)
    return text.strip()


def estimate_nhs(metrics: dict) -> int:
    """Estime un NHS simplifié pour le contexte audio."""
    avg_lat = metrics.get("avg_latency") or 150
    avg_thr = metrics.get("avg_throughput") or 5
    anomalies = metrics.get("anomalies") or 0
    samples = max(metrics.get("samples") or 1, 1)

    lat_score = max(0, 100 - (avg_lat / 5))
    thr_score = min(100, avg_thr * 10)
    anom_ratio = (anomalies / samples) * 100
    anom_score = max(0, 100 - anom_ratio * 2)

    return int((lat_score * 0.4 + thr_score * 0.3 + anom_score * 0.3))


def build_prompt_context(audience: str, metrics: dict,
                          trend_summary: dict, sample_row: dict) -> str:
    """Remplit le template de prompt avec les données réelles."""
    ctx = {
        "total_incidents":  metrics.get("incidents", 0),
        "critical_count":   0,
        "high_count":       0,
        "avg_latency":      metrics.get("avg_latency", "N/A"),
        "max_latency":      metrics.get("max_latency", "N/A"),
        "avg_jitter":       metrics.get("avg_jitter", "N/A"),
        "avg_throughput":   metrics.get("avg_throughput", "N/A"),
        "anomalies":        metrics.get("anomalies", 0),
        "latency_trend":    trend_summary.get("latency_trend", "stable"),
        "throughput_trend": trend_summary.get("throughput_trend", "stable"),
        "anomaly_type":     sample_row.get("anomaly_type", "N/A"),
        "anomaly_score":    sample_row.get("anomaly_score", "N/A"),
        "top_root_cause":   "En cours d'analyse",
        "nhs_estimate":     estimate_nhs(metrics),
    }
    return USER_PROMPT_TEMPLATE[audience].format(**ctx)


# ─────────────────────────────────────────────
# Génération LLM + TTS
# ─────────────────────────────────────────────

def generate_audio_script(audience: str, metrics: dict,
                           trend_summary: dict, sample_row: dict) -> str:
    """Génère le script texte via LLM."""
    system  = SYSTEM_PROMPTS[audience]
    user    = build_prompt_context(audience, metrics, trend_summary, sample_row)
    script  = ask_llama(system, user)
    return clean_for_tts(script)


def text_to_audio(text: str, lang: str) -> BytesIO:
    """Convertit le texte en audio MP3 via gTTS. Retourne un BytesIO."""
    tts = gTTS(text=text, lang=lang, slow=False)
    audio_buffer = BytesIO()
    tts.write_to_fp(audio_buffer)
    audio_buffer.seek(0)
    return audio_buffer


def generate_audio_report(audience: str, metrics: dict,
                           trend_summary: dict, sample_row: dict) -> tuple[BytesIO, str]:
    """
    Pipeline complet : LLM script → nettoyage → gTTS → MP3.
    Retourne (audio_buffer, script_text).
    """
    config = AUDIENCE_CONFIG[audience]
    script = generate_audio_script(audience, metrics, trend_summary, sample_row)
    audio  = text_to_audio(script, lang=config["lang"])

    # Sauvegarde locale optionnelle
    save_path = OUTPUT_DIR / f"audio_report_{audience}.mp3"
    with open(save_path, "wb") as f:
        f.write(audio.getvalue())
    audio.seek(0)

    return audio, script


def generate_all_audio_reports(metrics: dict, trend_summary: dict,
                                sample_row: dict) -> dict:
    """
    Génère les 3 rapports audio.
    Retourne : { "engineer": (buffer, script), "manager": ..., "director": ... }
    """
    results = {}
    for audience in ["engineer", "manager", "director"]:
        results[audience] = generate_audio_report(
            audience, metrics, trend_summary, sample_row
        )
    return results


# ─────────────────────────────────────────────
# Widget Streamlit
# ─────────────────────────────────────────────

def render_audio_report_widget(metrics: dict, trend_summary: dict, sample_row: dict):
    """
    Widget Streamlit complet pour le rapport audio.
    Coller dans streamlit_app.py dans la section Intelligence LLM Avancée.

    Usage :
        from usecase_8_audio_report import render_audio_report_widget
        render_audio_report_widget(metrics, trend_summary, sample_row)
    """
    try:
        import streamlit as st
    except ImportError:
        return

    st.markdown(
        '<div class="ml-badge">🎙️ TTS · Google Text-to-Speech · Bilingue</div>',
        unsafe_allow_html=True
    )
    st.markdown("**Rapport Audio** — Briefing vocal de 60 secondes adapté à chaque destinataire.")

    col_info, col_btn = st.columns([3, 1])
    with col_info:
        st.info(
            "Le LLM génère un script oral optimisé pour la synthèse vocale, "
            "puis gTTS le convertit en MP3. "
            "Ingénieur & Manager → 🇫🇷 Français | Directeur → 🇬🇧 English."
        )
    with col_btn:
        gen_all = st.button("🎙️ Générer les 3 audios", key="btn_audio_all")

    if gen_all:
        results = {}
        for audience, cfg in AUDIENCE_CONFIG.items():
            with st.spinner(f"Génération audio {cfg['label']}..."):
                try:
                    audio_buf, script = generate_audio_report(
                        audience, metrics, trend_summary, sample_row
                    )
                    results[audience] = {"audio": audio_buf, "script": script, "ok": True}
                except Exception as e:
                    results[audience] = {"error": str(e), "ok": False}
        st.session_state["audio_results"] = results

    if "audio_results" in st.session_state:
        results = st.session_state["audio_results"]

        tabs = st.tabs([
            f"{AUDIENCE_CONFIG[a]['flag']} {AUDIENCE_CONFIG[a]['label']}"
            for a in ["engineer", "manager", "director"]
        ])

        for tab, audience in zip(tabs, ["engineer", "manager", "director"]):
            cfg = AUDIENCE_CONFIG[audience]
            with tab:
                res = results.get(audience, {})
                if not res.get("ok"):
                    st.error(f"Erreur : {res.get('error', 'Inconnue')}")
                    continue

                # Player audio
                st.markdown(f"**{cfg['flag']} Langue : {'Français' if cfg['lang'] == 'fr' else 'English'}**")
                audio_buf = res["audio"]
                audio_buf.seek(0)
                st.audio(audio_buf.read(), format="audio/mp3")

                # Script généré
                with st.expander("📝 Voir le script généré"):
                    st.markdown(
                        f'<div style="background:var(--surface2);border:1px solid var(--border);'
                        f'border-radius:10px;padding:14px 18px;font-size:0.88rem;'
                        f'line-height:1.8;font-style:italic">{res["script"]}</div>',
                        unsafe_allow_html=True
                    )

                # Téléchargement
                audio_buf.seek(0)
                st.download_button(
                    label=f"⬇️ Télécharger MP3 ({cfg['label']})",
                    data=audio_buf.read(),
                    file_name=f"qos_buddy_audio_{audience}.mp3",
                    mime="audio/mp3",
                    key=f"dl_audio_{audience}"
                )