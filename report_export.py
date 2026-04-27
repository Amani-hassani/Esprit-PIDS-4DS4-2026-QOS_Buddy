from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas


def build_report_text(metrics: dict, trend_summary: dict, narrative: str, root_cause: str, incidents_preview: str) -> str:
    lines = []
    lines.append("QOS BUDDY - RAPPORT D'ANALYSE")
    lines.append("=" * 50)
    lines.append("")
    lines.append("1. KPI GLOBAUX")
    lines.append(f"- Nombre de samples : {metrics.get('samples')}")
    lines.append(f"- Nombre d'incidents : {metrics.get('incidents')}")
    lines.append(f"- Nombre d'anomalies : {metrics.get('anomalies')}")
    lines.append(f"- Latence moyenne : {metrics.get('avg_latency')} ms")
    lines.append(f"- Jitter moyen : {metrics.get('avg_jitter')} ms")
    lines.append(f"- Throughput moyen : {metrics.get('avg_throughput')} Mbps")
    lines.append(f"- Latence maximale : {metrics.get('max_latency')} ms")
    lines.append(f"- Jitter maximal : {metrics.get('max_jitter')} ms")
    lines.append("")
    lines.append("2. TENDANCES")
    lines.append(f"- Tendance latence : {trend_summary.get('latency_trend')}")
    lines.append(f"- Tendance jitter : {trend_summary.get('jitter_trend')}")
    lines.append(f"- Tendance throughput : {trend_summary.get('throughput_trend')}")
    lines.append("")
    lines.append("3. NARRATIVE LLM")
    lines.append(narrative or "N/A")
    lines.append("")
    lines.append("4. CAUSE RACINE")
    lines.append(root_cause or "N/A")
    lines.append("")
    lines.append("5. INCIDENTS PRINCIPAUX")
    lines.append(incidents_preview or "N/A")
    lines.append("")
    return "\n".join(lines)


def build_report_pdf(report_text: str) -> BytesIO:
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    x = 40
    y = height - 40
    line_height = 14

    for line in report_text.splitlines():
        if y < 40:
            pdf.showPage()
            y = height - 40
        pdf.drawString(x, y, line[:110])
        y -= line_height

    pdf.save()
    buffer.seek(0)
    return buffer