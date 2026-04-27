from llm_engine import ask_llama


SYSTEM_PROMPT = """
Tu es un assistant expert en analyse QoS réseau.
Tu réponds uniquement en français.
Tu dois te baser uniquement sur le contexte fourni.
Si une information manque, dis-le clairement.
Ne pas inventer.
"""


def build_qa_context(df, incidents_df, top_rows=None) -> str:
    total_samples = len(df)
    total_incidents = len(incidents_df)

    avg_latency = round(df["latency_ms"].dropna().mean(), 2) if "latency_ms" in df.columns else "N/A"
    avg_jitter = round(df["jitter_ms"].dropna().mean(), 2) if "jitter_ms" in df.columns else "N/A"
    avg_throughput = round(df["throughput_mbps"].dropna().mean(), 2) if "throughput_mbps" in df.columns else "N/A"

    max_latency = round(df["latency_ms"].dropna().max(), 2) if "latency_ms" in df.columns else "N/A"
    max_jitter = round(df["jitter_ms"].dropna().max(), 2) if "jitter_ms" in df.columns else "N/A"

    anomaly_count = 0
    if "anomaly_flag" in df.columns:
        anomaly_count = (df["anomaly_flag"].astype(str).str.lower() == "true").sum()

    top_incidents = []
    if not incidents_df.empty and "max_score" in incidents_df.columns:
        cols = [c for c in ["incident_type", "severity", "max_score", "start_timestamp"] if c in incidents_df.columns]
        top_incidents = (
            incidents_df.sort_values("max_score", ascending=False, na_position="last")
            .head(5)[cols]
            .to_dict(orient="records")
        )

    interesting_rows = []
    if top_rows:
        for row in top_rows[:5]:
            interesting_rows.append({
                "timestamp": str(row.get("timestamp")),
                "anomaly_type": row.get("anomaly_type"),
                "anomaly_score": row.get("anomaly_score"),
                "latency_ms": row.get("latency_ms"),
                "jitter_ms": row.get("jitter_ms"),
                "throughput_mbps": row.get("throughput_mbps"),
                "traffic_type": row.get("traffic_type"),
                "source_file": row.get("source_file"),
            })

    return f"""
Contexte global QoS Buddy :
- Nombre total d'échantillons : {total_samples}
- Nombre total d'incidents : {total_incidents}
- Nombre total d'échantillons marqués anomalie : {anomaly_count}
- Latence moyenne : {avg_latency} ms
- Jitter moyen : {avg_jitter} ms
- Throughput moyen : {avg_throughput} Mbps
- Latence maximale : {max_latency} ms
- Jitter maximal : {max_jitter} ms

Top incidents :
{top_incidents}

Mesures les plus intéressantes :
{interesting_rows}
""".strip()


def answer_question(question: str, df, incidents_df, top_rows=None) -> str:
    context = build_qa_context(df, incidents_df, top_rows=top_rows)

    user_prompt = f"""
Contexte :
{context}

Question utilisateur :
{question}
"""
    return ask_llama(SYSTEM_PROMPT, user_prompt)