"""
Reporting Service — FastAPI wrapper around the QoS-Buddy reporting agent.

Exposes three endpoints:
  GET  /health
  POST /api/postmortem   — AI lesson + root-cause + recommendations
  POST /api/insights     — NOC narrative for a single metric snapshot

Uses the containerised Ollama runtime; falls back gracefully on LLM failure.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

import asyncpg
import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

log = logging.getLogger("qos.reporting")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

OLLAMA_URL    = os.getenv("OLLAMA_URL",    "http://ollama:11434")
PRIMARY_MODEL = os.getenv("LLM_PRIMARY",   "qwen2.5:3b-instruct-q4_K_M")
FALLBACK_MODEL= os.getenv("LLM_FALLBACK",  "llama3.2:3b-instruct-q4_K_M")
LLM_TIMEOUT   = float(os.getenv("LLM_TIMEOUT_SECONDS", "12.0"))
RAG_URL       = os.getenv("RAG_URL", "http://rag:8000")
DATABASE_URL  = os.getenv("DATABASE_URL", "postgresql://qos:qos@postgres:5432/qos")

app = FastAPI(title="QoS-Buddy Reporting Service", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── HTTP client lifecycle ────────────────────────────────────────────────────

_client: httpx.AsyncClient | None = None

@app.on_event("startup")
async def startup() -> None:
    global _client
    _client = httpx.AsyncClient(base_url=OLLAMA_URL, timeout=LLM_TIMEOUT)

@app.on_event("shutdown")
async def shutdown() -> None:
    if _client:
        await _client.aclose()
    log.info("Shutdown complete")

# ─── Schemas ──────────────────────────────────────────────────────────────────

class Features(BaseModel):
    latency_ms:        Optional[float] = None
    jitter_ms:         Optional[float] = None
    packet_loss_pct:   Optional[float] = None
    throughput_mbps:   Optional[float] = None
    bandwidth_util_pct:Optional[float] = None
    cpu_pct:           Optional[float] = None
    memory_pct:        Optional[float] = None
    mos_estimate:      Optional[float] = None
    rssi_dbm:          Optional[float] = None
    rsrp_dbm:          Optional[float] = None
    sinr_db:           Optional[float] = None
    channel_util_pct:  Optional[float] = None
    queue_length:      Optional[float] = None
    anomaly_rate_recent: Optional[float] = None

class TopFactor(BaseModel):
    display_label: str
    impact_pct:    float
    direction:     str

class PostMortemRequest(BaseModel):
    event_id:      Optional[str] = None
    severity:      str = "medium"
    display_label: str = "Network event"
    detector:      str = "behavioral"
    cell_id:       Optional[str] = None
    features:      Features = Field(default_factory=Features)
    top_factors:   list[TopFactor] = Field(default_factory=list)
    # Optional enrichment from diagnostic agent
    root_cause:    Optional[str] = None
    diagnosis_summary: Optional[str] = None

class PostMortemResponse(BaseModel):
    lesson:       str
    root_cause_class: str
    confidence:   int
    recommendations: list[str]
    save_to_memory: bool = False

class CloseIncidentRequest(BaseModel):
    event_id: str
    lesson: str

class CloseIncidentResponse(BaseModel):
    closed: bool
    saved_to_memory: bool

class InsightsRequest(BaseModel):
    features:      Features
    severity:      str = "medium"
    display_label: str = "Network event"
    detector:      str = "behavioral"

class InsightsResponse(BaseModel):
    narrative:    str

# ─── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/postmortem", response_model=PostMortemResponse)
async def postmortem(req: PostMortemRequest) -> PostMortemResponse:
    rc_class, confidence = _preclassify(req.features)
    response = await _llm_postmortem(req, rc_class, confidence)
    if response.save_to_memory:
        asyncio.create_task(
            auto_save_lesson(
                response.lesson,
                {
                    "event_id": req.event_id or "",
                    "cell_id": req.cell_id or "",
                    "severity": req.severity,
                    "root_cause_class": response.root_cause_class,
                    "source": "postmortem",
                },
            )
        )
    return response


@app.post("/api/postmortem/close", response_model=CloseIncidentResponse)
async def close_postmortem(req: CloseIncidentRequest) -> CloseIncidentResponse:
    await auto_save_lesson(
        req.lesson,
        {"event_id": req.event_id, "source": "incident_close", "closed_at": datetime.now(timezone.utc).isoformat()},
    )
    await _mark_alert_resolved(req.event_id, req.lesson)
    return CloseIncidentResponse(closed=True, saved_to_memory=True)


@app.post("/api/insights", response_model=InsightsResponse)
async def insights(req: InsightsRequest) -> InsightsResponse:
    narrative = await _llm_narrative(req)
    return InsightsResponse(narrative=narrative)


# ─── Rule-based pre-classifier (adapted from reporting agent) ─────────────────

def _preclassify(f: Features) -> tuple[str, int]:
    """Return (root_cause_class, confidence_pct) from KPI heuristics."""
    if f.packet_loss_pct is not None and f.packet_loss_pct > 5:
        return ("transport_failure", 82)
    if f.rssi_dbm is not None and f.rssi_dbm < -85:
        return ("radio_coverage", 78)
    if f.rsrp_dbm is not None and f.rsrp_dbm < -120:
        return ("radio_coverage", 75)
    if f.sinr_db is not None and f.sinr_db < 5:
        return ("radio_coverage", 74)
    if f.channel_util_pct is not None and f.channel_util_pct > 85:
        return ("congestion", 80)
    if f.bandwidth_util_pct is not None and f.bandwidth_util_pct > 85:
        return ("congestion", 76)
    if f.throughput_mbps is not None and f.throughput_mbps < 2:
        if f.latency_ms is not None and f.latency_ms < 50:
            return ("misconfiguration", 65)
    if f.latency_ms is not None and f.latency_ms > 200:
        return ("transport_failure", 72)
    return ("transport_failure", 55)


# ─── LLM prompts ─────────────────────────────────────────────────────────────

_POSTMORTEM_SYSTEM = (
    "You are a NOC post-mortem analyst. Return ONLY valid JSON matching this schema: "
    "{\"lesson\":\"one NOC-language sentence summarising the incident and resolution\","
    "\"root_cause_class\":\"one of: radio_coverage|congestion|transport_failure|power_issue|misconfiguration|unknown\","
    "\"confidence\":0-100,"
    "\"recommendations\":[\"up to 4 action items, each under 100 chars\"],"
    "\"save_to_memory\":true}"
)

_NARRATIVE_SYSTEM = (
    "You are a network operations assistant. Write ONE concise paragraph "
    "(max 60 words) in plain NOC language for a non-technical operator. "
    "Describe the current network condition based on the KPIs provided. "
    "End with a one-line recommended action."
)


async def _llm_postmortem(req: PostMortemRequest, rc_class: str, confidence: int) -> PostMortemResponse:
    f = req.features
    kpi_lines = "\n".join([
        f"- Latency: {f.latency_ms:.1f} ms"         if f.latency_ms        is not None else "",
        f"- Jitter: {f.jitter_ms:.1f} ms"            if f.jitter_ms         is not None else "",
        f"- Packet loss: {f.packet_loss_pct:.2f}%"   if f.packet_loss_pct   is not None else "",
        f"- Throughput: {f.throughput_mbps:.1f} Mbps" if f.throughput_mbps  is not None else "",
        f"- CPU: {f.cpu_pct:.1f}%"                   if f.cpu_pct           is not None else "",
        f"- MOS: {f.mos_estimate:.2f}"               if f.mos_estimate       is not None else "",
    ]).strip()

    factors = "\n".join(
        f"- {tf.display_label}: {tf.impact_pct:.0f}% ({tf.direction})"
        for tf in req.top_factors[:4]
    ) or "- (none available)"

    diag = req.diagnosis_summary or req.root_cause or rc_class.replace("_", " ")

    prompt = (
        f"Incident: {req.display_label} (severity: {req.severity}, cell: {req.cell_id or 'unknown'}).\n"
        f"Root cause class: {diag}.\n\n"
        f"KPIs at time of incident:\n{kpi_lines}\n\n"
        f"Top contributing factors:\n{factors}\n\n"
        f"Write the post-incident lesson."
    )
    text = await _generate(_POSTMORTEM_SYSTEM, prompt)
    if text:
        parsed = _parse_postmortem_json(text)
        if parsed is not None:
            return parsed
    return _fallback_postmortem(req, rc_class, confidence, diag)


async def _llm_narrative(req: InsightsRequest) -> str:
    f = req.features
    kpi_lines = "\n".join(filter(None, [
        f"- Latency: {f.latency_ms:.1f} ms"          if f.latency_ms        is not None else "",
        f"- Jitter: {f.jitter_ms:.1f} ms"            if f.jitter_ms         is not None else "",
        f"- Packet loss: {f.packet_loss_pct:.2f}%"   if f.packet_loss_pct   is not None else "",
        f"- Throughput: {f.throughput_mbps:.1f} Mbps" if f.throughput_mbps  is not None else "",
        f"- MOS: {f.mos_estimate:.2f}"               if f.mos_estimate       is not None else "",
    ]))
    prompt = (
        f"Event: {req.display_label} (severity: {req.severity}).\n\n"
        f"Current KPIs:\n{kpi_lines}\n\n"
        f"Describe the network condition for the NOC operator."
    )
    text = await _generate(_NARRATIVE_SYSTEM, prompt)
    if text:
        return text
    return (
        f"{req.display_label} detected at {req.severity} severity. "
        f"Review live KPIs and escalate if the condition persists beyond 5 minutes."
    )


def _parse_postmortem_json(text: str) -> PostMortemResponse | None:
    try:
        payload = json.loads(_json_object(text))
    except (json.JSONDecodeError, ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    allowed = {"radio_coverage", "congestion", "transport_failure", "power_issue", "misconfiguration", "unknown"}
    lesson = str(payload.get("lesson") or "").strip()
    if not lesson:
        return None
    root_cause = str(payload.get("root_cause_class") or "unknown").strip()
    if root_cause not in allowed:
        root_cause = "unknown"
    try:
        confidence = int(float(payload.get("confidence", 60)))
    except (TypeError, ValueError):
        confidence = 60
    raw_recs = payload.get("recommendations") if isinstance(payload.get("recommendations"), list) else []
    recs = [str(item).strip()[:100] for item in raw_recs if str(item).strip()][:4]
    return PostMortemResponse(
        lesson=lesson,
        root_cause_class=root_cause,
        confidence=max(0, min(100, confidence)),
        recommendations=recs or ["Monitor KPI recovery for 15 minutes before closing."],
        save_to_memory=bool(payload.get("save_to_memory", False)),
    )


def _json_object(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no json object")
    return stripped[start : end + 1]


def _fallback_postmortem(
    req: PostMortemRequest,
    rc_class: str,
    confidence: int,
    diag: str,
) -> PostMortemResponse:
    lesson = (
        f"{req.display_label} on {req.cell_id or 'cell'} was classified as "
        f"{diag.replace('_', ' ')} at {req.severity} severity; verify KPI recovery "
        "and confirm the remediation cleared the condition before closing."
    )
    return PostMortemResponse(
        lesson=lesson,
        root_cause_class=rc_class,
        confidence=confidence,
        recommendations=_build_recommendations(req, rc_class),
        save_to_memory=confidence >= 70 or req.severity in {"high", "critical"},
    )


async def _generate(system: str, user: str) -> str:
    if _client is None:
        return ""
    for model in (PRIMARY_MODEL, FALLBACK_MODEL):
        try:
            body = {
                "model": model,
                "prompt": f"<|system|>\n{system}\n<|user|>\n{user}\n<|assistant|>\n",
                "stream": False,
                "options": {
                    "temperature": 0.25,
                    "num_predict": 200,
                    "top_p": 0.9,
                },
            }
            resp = await _client.post("/api/generate", json=body, timeout=min(LLM_TIMEOUT, 15.0))
            resp.raise_for_status()
            text = (resp.json().get("response") or "").strip()
            if text:
                return text
        except (httpx.HTTPError, asyncio.TimeoutError) as exc:
            log.debug("llm call failed model=%s: %s", model, exc)
    return ""


async def auto_save_lesson(lesson: str, metadata: dict) -> None:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(
                f"{RAG_URL}/api/memory/save",
                json={"lesson": lesson, "metadata": metadata},
            )
    except Exception as exc:  # noqa: BLE001
        log.warning("operator memory save failed: %s", exc)


async def _mark_alert_resolved(event_id: str, lesson: str) -> None:
    conn: asyncpg.Connection | None = None
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS incident_closures (
                event_id TEXT PRIMARY KEY,
                lesson TEXT NOT NULL,
                status TEXT NOT NULL,
                resolved_at TIMESTAMPTZ NOT NULL
            )
            """
        )
        await conn.execute(
            """
            INSERT INTO incident_closures(event_id, lesson, status, resolved_at)
            VALUES($1, $2, 'resolved', NOW())
            ON CONFLICT(event_id) DO UPDATE
            SET lesson = EXCLUDED.lesson,
                status = 'resolved',
                resolved_at = EXCLUDED.resolved_at
            """,
            event_id,
            lesson,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("postgres incident close failed event_id=%s: %s", event_id, exc)
    finally:
        if conn is not None:
            await conn.close()


# ─── Deterministic recommendations ───────────────────────────────────────────

def _build_recommendations(req: PostMortemRequest, rc_class: str) -> list[str]:
    recs: list[str] = []
    f = req.features

    if rc_class == "congestion":
        recs.append("Review traffic shaping policies and increase buffer allocation on congested links.")
        if f.bandwidth_util_pct is not None and f.bandwidth_util_pct > 90:
            recs.append("Utilisation exceeded 90% — consider load balancing to adjacent cells.")
    elif rc_class == "transport_failure":
        recs.append("Check physical and logical transport layer for CRC errors or link flaps.")
        if f.packet_loss_pct is not None and f.packet_loss_pct > 3:
            recs.append("Packet loss above 3% — validate routing table convergence and interface health.")
    elif rc_class == "radio_coverage":
        recs.append("Audit antenna tilt and transmit power for coverage improvement.")
        recs.append("Check for neighbouring cell interference using RSRQ/SINR trends.")
    elif rc_class == "channel_interference":
        recs.append("Run spectrum scan and reassign channel to reduce co-channel interference.")
    elif rc_class == "application_issue":
        recs.append("Trace application-layer sessions — low throughput with normal latency suggests server-side bottleneck.")

    if f.mos_estimate is not None and f.mos_estimate < 3.5:
        recs.append(f"MOS {f.mos_estimate:.2f} is below acceptable voice quality threshold (3.6) — prioritise VoIP traffic class.")
    if f.latency_ms is not None and f.latency_ms > 150:
        recs.append("Round-trip delay above 150 ms — check QoS queue depths and DSCP markings.")

    if not recs:
        recs.append("Monitor KPI trends for 15 minutes; escalate if severity does not reduce.")

    return [rec[:100] for rec in recs[:4]]
