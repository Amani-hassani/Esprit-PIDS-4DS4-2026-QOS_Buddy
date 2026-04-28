"""
REPORTING AGENT — Usecase 9 : Anomaly Digest Email
===================================================
Génère et envoie automatiquement un digest HTML des anomalies réseau
via SendGrid (100 emails/jour gratuit).

Configuration dans .env :
    SENDGRID_API_KEY=SG.xxxxxxxxxxxxxxxxxxxxxx
    SENDGRID_FROM_EMAIL=qosbuddy@tondomaine.com
    DIGEST_TO_EMAIL=manager@entreprise.com
"""

import os
from datetime import datetime
from dotenv import load_dotenv
from llm_engine import ask_llama

load_dotenv()


# ─────────────────────────────────────────────
# Génération du contenu LLM
# ─────────────────────────────────────────────

SYSTEM_PROMPT = """
Tu es un expert réseau télécom qui rédige un digest email professionnel.
Langue : français. Style : clair, structuré, orienté action.
Génère uniquement le contenu texte brut — pas de HTML, pas de markdown.
Structure OBLIGATOIRE (respecte exactement ces 4 balises) :

OBJET: [ligne d'objet percutante de l'email]
RESUME: [2-3 phrases de synthèse de la situation réseau]
INCIDENTS: [3-5 points clés séparés par | ]
ACTION: [1 recommandation principale concrète]

Maximum 150 mots au total.
"""

USER_TEMPLATE = """
Données réseau pour le digest :
- Période : {period}
- Total incidents : {total_incidents} dont {critical_count} critiques
- Latence moyenne : {avg_latency} ms | max : {max_latency} ms
- Jitter moyen : {avg_jitter} ms
- Throughput moyen : {avg_throughput} Mbps
- Anomalies détectées : {anomalies}
- Tendance latence : {latency_trend}
- Tendance throughput : {throughput_trend}
- Incident le plus critique : {anomaly_type} (score {anomaly_score})

Génère le digest email professionnel.
"""


def generate_digest_content(metrics: dict, trend_summary: dict,
                             sample_row: dict, period: str = None) -> dict:
    """
    Génère le contenu du digest via LLM.
    Retourne un dict avec : objet, resume, incidents, action
    """
    if not period:
        period = datetime.now().strftime("%d/%m/%Y %H:%M")

    user_prompt = USER_TEMPLATE.format(
        period=period,
        total_incidents=metrics.get("incidents", 0),
        critical_count=0,
        avg_latency=metrics.get("avg_latency", "N/A"),
        max_latency=metrics.get("max_latency", "N/A"),
        avg_jitter=metrics.get("avg_jitter", "N/A"),
        avg_throughput=metrics.get("avg_throughput", "N/A"),
        anomalies=metrics.get("anomalies", 0),
        latency_trend=trend_summary.get("latency_trend", "stable"),
        throughput_trend=trend_summary.get("throughput_trend", "stable"),
        anomaly_type=sample_row.get("anomaly_type", "N/A"),
        anomaly_score=sample_row.get("anomaly_score", "N/A"),
    )

    raw = ask_llama(SYSTEM_PROMPT, user_prompt)

    # Parser les 4 sections
    content = {
        "objet":     _extract_section(raw, "OBJET"),
        "resume":    _extract_section(raw, "RESUME"),
        "incidents": _extract_section(raw, "INCIDENTS"),
        "action":    _extract_section(raw, "ACTION"),
        "raw":       raw,
        "period":    period,
    }
    return content


def _extract_section(text: str, key: str) -> str:
    """Extrait une section du texte LLM."""
    lines = text.splitlines()
    for line in lines:
        if line.strip().upper().startswith(f"{key}:"):
            return line.split(":", 1)[-1].strip()
    return "N/A"


# ─────────────────────────────────────────────
# Template HTML Email
# ─────────────────────────────────────────────

def build_html_email(content: dict, metrics: dict) -> str:
    """Construit le corps HTML de l'email digest."""

    # Points incidents
    incidents_list = content.get("incidents", "")
    incidents_html = ""
    for point in incidents_list.split("|"):
        point = point.strip()
        if point:
            incidents_html += f"""
            <tr>
                <td style="padding:8px 12px;border-bottom:1px solid #e2e8f0;font-size:14px;color:#334155">
                    🔸 {point}
                </td>
            </tr>"""

    # Couleur NHS estimée
    avg_lat = metrics.get("avg_latency") or 999
    status_color = "#10b981" if avg_lat < 150 else "#f59e0b" if avg_lat < 200 else "#ef4444"
    status_text  = "Bon" if avg_lat < 150 else "Dégradé" if avg_lat < 200 else "Critique"

    html = f"""
<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>QoS Buddy — Digest Réseau</title>
</head>
<body style="margin:0;padding:0;background:#f1f5f9;font-family:'Segoe UI',Arial,sans-serif">

<table width="100%" cellpadding="0" cellspacing="0" style="background:#f1f5f9;padding:30px 0">
<tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:16px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.08)">

  <!-- HEADER -->
  <tr>
    <td style="background:linear-gradient(135deg,#0f172a 0%,#1e3a5f 100%);padding:32px 40px">
      <table width="100%" cellpadding="0" cellspacing="0">
        <tr>
          <td>
            <div style="font-size:11px;font-weight:700;letter-spacing:0.12em;text-transform:uppercase;color:#93c5fd;margin-bottom:8px">
              📡 QoS Buddy — Reporting Agent
            </div>
            <div style="font-size:24px;font-weight:800;color:#f1f5f9;margin-bottom:4px">
              Digest Anomalies Réseau
            </div>
            <div style="font-size:13px;color:#94a3b8">{content.get("period", "")}</div>
          </td>
          <td align="right">
            <div style="background:{status_color};color:white;font-size:12px;font-weight:700;
                        padding:8px 16px;border-radius:100px;display:inline-block">
              Réseau : {status_text}
            </div>
          </td>
        </tr>
      </table>
    </td>
  </tr>

  <!-- KPI BAR -->
  <tr>
    <td style="background:#0f172a;padding:16px 40px">
      <table width="100%" cellpadding="0" cellspacing="0">
        <tr>
          <td align="center" style="color:#94a3b8;font-size:11px;text-transform:uppercase;letter-spacing:0.08em">
            Incidents<br>
            <span style="color:#f1f5f9;font-size:20px;font-weight:700">
              {metrics.get("incidents", 0)}
            </span>
          </td>
          <td align="center" style="color:#94a3b8;font-size:11px;text-transform:uppercase;letter-spacing:0.08em">
            Anomalies<br>
            <span style="color:#f59e0b;font-size:20px;font-weight:700">
              {metrics.get("anomalies", 0)}
            </span>
          </td>
          <td align="center" style="color:#94a3b8;font-size:11px;text-transform:uppercase;letter-spacing:0.08em">
            Latence moy.<br>
            <span style="color:#ef4444;font-size:20px;font-weight:700">
              {metrics.get("avg_latency", "N/A")} ms
            </span>
          </td>
          <td align="center" style="color:#94a3b8;font-size:11px;text-transform:uppercase;letter-spacing:0.08em">
            Throughput moy.<br>
            <span style="color:#10b981;font-size:20px;font-weight:700">
              {metrics.get("avg_throughput", "N/A")} Mbps
            </span>
          </td>
        </tr>
      </table>
    </td>
  </tr>

  <!-- RESUME -->
  <tr>
    <td style="padding:28px 40px 16px 40px">
      <div style="font-size:11px;font-weight:700;letter-spacing:0.1em;text-transform:uppercase;
                  color:#3b82f6;margin-bottom:10px">📋 Synthèse</div>
      <div style="font-size:15px;color:#334155;line-height:1.7;background:#f8fafc;
                  border-left:4px solid #3b82f6;padding:14px 18px;border-radius:0 8px 8px 0">
        {content.get("resume", "N/A")}
      </div>
    </td>
  </tr>

  <!-- INCIDENTS -->
  <tr>
    <td style="padding:8px 40px 16px 40px">
      <div style="font-size:11px;font-weight:700;letter-spacing:0.1em;text-transform:uppercase;
                  color:#f59e0b;margin-bottom:10px">⚠️ Points clés</div>
      <table width="100%" cellpadding="0" cellspacing="0"
             style="border:1px solid #e2e8f0;border-radius:8px;overflow:hidden">
        {incidents_html}
      </table>
    </td>
  </tr>

  <!-- ACTION -->
  <tr>
    <td style="padding:8px 40px 28px 40px">
      <div style="font-size:11px;font-weight:700;letter-spacing:0.1em;text-transform:uppercase;
                  color:#10b981;margin-bottom:10px">✅ Action recommandée</div>
      <div style="background:#f0fdf4;border:1px solid #bbf7d0;border-radius:8px;
                  padding:14px 18px;font-size:14px;color:#166534;font-weight:500">
        {content.get("action", "N/A")}
      </div>
    </td>
  </tr>

  <!-- FOOTER -->
  <tr>
    <td style="background:#f8fafc;border-top:1px solid #e2e8f0;padding:16px 40px">
      <div style="font-size:12px;color:#94a3b8;text-align:center">
        QoS Buddy · Reporting Agent · Généré automatiquement le {content.get("period", "")}
        <br>Ce rapport est généré automatiquement — ne pas répondre à cet email.
      </div>
    </td>
  </tr>

</table>
</td></tr>
</table>

</body>
</html>
"""
    return html


# ─────────────────────────────────────────────
# Envoi Email via SendGrid
# ─────────────────────────────────────────────

def send_email_sendgrid(subject: str, html_body: str, to_email: str = None) -> tuple[bool, str]:
    """
    Envoie l'email digest via SendGrid.
    Retourne (success, message).
    """
    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail
    except ImportError:
        return False, "sendgrid non installé — pip install sendgrid"

    api_key    = os.getenv("SENDGRID_API_KEY")
    from_email = os.getenv("SENDGRID_FROM_EMAIL", "qosbuddy@example.com")
    to_email   = to_email or os.getenv("DIGEST_TO_EMAIL")

    if not api_key:
        return False, "SENDGRID_API_KEY manquante dans .env"
    if not to_email:
        return False, "DIGEST_TO_EMAIL manquante dans .env"

    message = Mail(
        from_email=from_email,
        to_emails=to_email,
        subject=subject,
        html_content=html_body
    )

    try:
        sg = SendGridAPIClient(api_key)
        response = sg.send(message)
        if response.status_code in (200, 202):
            return True, f"Email envoyé avec succès à {to_email}"
        return False, f"Erreur SendGrid : status {response.status_code}"
    except Exception as e:
        return False, f"Erreur envoi : {str(e)}"


# ─────────────────────────────────────────────
# Pipeline complet
# ─────────────────────────────────────────────

def run_digest(metrics: dict, trend_summary: dict,
               sample_row: dict, to_email: str = None,
               period: str = None) -> dict:
    """
    Pipeline complet :
    1. Génère le contenu LLM
    2. Construit le HTML
    3. Envoie via SendGrid

    Retourne :
    {
        "content":  dict contenu LLM,
        "html":     str HTML de l'email,
        "sent":     bool,
        "message":  str résultat envoi
    }
    """
    content  = generate_digest_content(metrics, trend_summary, sample_row, period)
    html     = build_html_email(content, metrics)
    subject  = content.get("objet", "QoS Buddy — Digest Anomalies Réseau")
    sent, msg = send_email_sendgrid(subject, html, to_email)

    return {
        "content": content,
        "html":    html,
        "subject": subject,
        "sent":    sent,
        "message": msg,
    }


# ─────────────────────────────────────────────
# Widget Streamlit
# ─────────────────────────────────────────────

def render_digest_widget(metrics: dict, trend_summary: dict, sample_row: dict):
    """
    Widget Streamlit pour le digest email.
    Usage dans streamlit_app.py :
        from usecase_9_digest_email import render_digest_widget
        render_digest_widget(metrics, trend_summary, sample_row)
    """
    try:
        import streamlit as st
    except ImportError:
        return

    st.markdown(
        '<div class="ml-badge">📧 SendGrid · Digest automatique · HTML professionnel</div>',
        unsafe_allow_html=True
    )
    st.markdown("**Anomaly Digest Email** — Génère et envoie un email HTML professionnel avec le résumé des anomalies.")

    # Config
    with st.expander("⚙️ Configuration SendGrid"):
        col1, col2 = st.columns(2)
        with col1:
            to_email = st.text_input(
                "Email destinataire",
                value=os.getenv("DIGEST_TO_EMAIL", ""),
                placeholder="manager@entreprise.com",
                key="digest_to_email"
            )
        with col2:
            period_label = st.text_input(
                "Période du rapport",
                value=datetime.now().strftime("%d/%m/%Y %H:%M"),
                key="digest_period"
            )
        st.info(
            "Configure SENDGRID_API_KEY et SENDGRID_FROM_EMAIL dans ton fichier .env "
            "pour activer l'envoi réel. Sans configuration, tu peux prévisualiser l'email."
        )

    col_prev, col_send = st.columns([1, 1])

    with col_prev:
        if st.button("👁️ Prévisualiser l'email", key="btn_digest_preview"):
            with st.spinner("Génération du contenu LLM..."):
                content = generate_digest_content(
                    metrics, trend_summary, sample_row, period_label
                )
                html = build_html_email(content, metrics)
            st.session_state["digest_content"] = content
            st.session_state["digest_html"]    = html

    with col_send:
        if st.button("📧 Générer + Envoyer", key="btn_digest_send", type="primary"):
            with st.spinner("Génération et envoi en cours..."):
                result = run_digest(
                    metrics, trend_summary, sample_row,
                    to_email=to_email or None,
                    period=period_label
                )
            st.session_state["digest_content"] = result["content"]
            st.session_state["digest_html"]    = result["html"]
            if result["sent"]:
                st.success(f"✅ {result['message']}")
            else:
                st.warning(f"⚠️ Email non envoyé : {result['message']}")
                st.info("L'email est prévisualisé ci-dessous. Configure SendGrid dans .env pour l'envoi réel.")

    # Affichage résultat
    if "digest_content" in st.session_state:
        content = st.session_state["digest_content"]
        html    = st.session_state["digest_html"]

        st.markdown("---")

        # Infos générées
        col_a, col_b = st.columns([1, 2])
        with col_a:
            st.markdown("**📋 Contenu généré**")
            st.markdown(f"**Objet :** {content.get('objet', 'N/A')}")
            st.markdown(f"**Résumé :** {content.get('resume', 'N/A')}")
            st.markdown(f"**Action :** {content.get('action', 'N/A')}")

            # Télécharger HTML
            st.download_button(
                label="⬇️ Télécharger l'email HTML",
                data=html,
                file_name=f"digest_email_{datetime.now().strftime('%Y%m%d_%H%M')}.html",
                mime="text/html",
                key="dl_digest_html"
            )

        with col_b:
            st.markdown("**🖥️ Aperçu de l'email**")
            st.components.v1.html(html, height=520, scrolling=True)