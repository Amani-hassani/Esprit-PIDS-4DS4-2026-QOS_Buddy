"""
Diagnostic bridge.

Subscribes to `qos.alerts`, forwards each alert to the *real* diagnostic
agent's `/api/detection-agent/events` endpoint (Random-Forest + GRU + FAISS),
and republishes the resulting incident as a `DiagnosisEvent` on
`qos.diagnosis`.

The diagnostic agent maintains its own incident store internally; we
intentionally only publish a thin pointer event on the bus so downstream
consumers can fetch the full incident detail by id when needed.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

import httpx

from contracts.schemas import (
    DiagnosisEvent,
    SimilarIncident,
    StreamName,
)

from .graceful import install_sigterm_handler
from .otel import flush_tracer, init_tracer
from .redis_streams import RedisStreamsBus, run_consumer

log = logging.getLogger("qos.bridge.diagnostic")

DIAGNOSTIC_URL = os.getenv("DIAGNOSTIC_URL", "http://diagnostic:8000")
RAG_URL = os.getenv("RAG_URL", "http://rag:8000")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
LLM_PRIMARY = os.getenv("LLM_PRIMARY", "qwen2.5:3b-instruct-q4_K_M")
LLM_FALLBACK = os.getenv("LLM_FALLBACK", "llama3.2:3b-instruct-q4_K_M")
LLM_TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT_SECONDS", "30"))
GROUP = os.getenv("DIAGNOSTIC_GROUP", "diagnostic")
CONSUMER = os.getenv("DIAGNOSTIC_CONSUMER", "diagnostic-1")


def _build_payload(alert: dict[str, Any]) -> dict[str, Any]:
    """Convert an AlertEvent dict into the agent's IngestRequest shape.

    The diagnostic agent rejects events whose `monitoring` block is empty
    with `status="waiting_for_monitoring"`, so we forward the raw KPI row
    that was attached to the alert by the detection bridge.
    """
    return {
        "event_id": alert.get("event_id"),
        "timestamp": alert.get("occurred_at"),
        "node_id": alert.get("node_id"),
        "cell_id": alert.get("cell_id"),
        "zone_id": alert.get("zone_id"),
        "monitoring": dict(alert.get("monitoring_features") or {}),
        "detection": {
            "severity": alert.get("severity"),
            "confidence": alert.get("confidence"),
            "display_label": alert.get("display_label"),
            "technical_label": alert.get("technical_label"),
            "top_factors": alert.get("top_factors", []),
        },
        "prediction": {},
        "metadata": {
            "correlation_id": alert.get("correlation_id"),
            "source_alert_id": alert.get("event_id"),
        },
    }


_HUMAN_LABELS = {
    "RC_CAPACITY_OVERLOAD": "Capacity overload",
    "RC_TRANSPORT_DELAY": "Transport delay",
    "RC_JITTER_INSTABILITY": "Jitter instability",
    "RC_PACKET_LOSS": "Packet loss",
    "RC_RETRANSMISSION": "TCP retransmission storm",
    "RC_RADIO_SIGNAL_WEAK": "Weak radio signal",
    "RC_HANDOVER_INSTABILITY": "Handover instability",
    "RC_CQI_MISMATCH": "Radio quality mismatch (CQI)",
}

_NOC_TERM_REPLACEMENTS = {
    "LSTM": "forecasting model",
    "SHAP values": "top contributing factors",
    "SHAP": "top contributing factors",
    "FAISS results": "similar past incidents",
    "FAISS": "similar past incidents",
    "MAB arm score": "recommendation confidence",
    "MAB": "recommended action engine",
    "Prophet forecast": "forecast",
    "Prophet": "forecast",
    "embedding": "operator memory match",
    "drift": "network behavior shift",
    "KS-test": "network behavior shift check",
    "confusion matrix": "accuracy table",
    "autoencoder anomaly": "behavioral anomaly",
    "autoencoder": "behavioral anomaly detector",
    "neural network": "model",
    "XGBoost": "ranking model",
    "encoder": "model",
    "decoder": "model",
}


def _to_diagnosis(alert: dict[str, Any], incident: dict[str, Any], enhancement: dict[str, Any]) -> DiagnosisEvent:
    rc_id = str(
        incident.get("root_cause")
        or incident.get("primary_root_cause")
        or incident.get("actual_root_cause")
        or "unknown"
    )
    rc_label = (
        _HUMAN_LABELS.get(rc_id)
        or incident.get("anomaly_type")
        or rc_id.replace("RC_", "").replace("_", " ").title()
    )

    similar: list[SimilarIncident] = []
    rag_similar = enhancement.get("similar_incidents") if isinstance(enhancement.get("similar_incidents"), list) else []
    for item in rag_similar[:3]:
        lesson = _noc_text(item.get("lesson") or "")
        relevance = int(item.get("relevance_pct") or 0)
        days_ago = int(item.get("occurred_days_ago") or 0)
        similar.append(
            SimilarIncident(
                incident_id=str(item.get("incident_id") or lesson[:32] or "memory"),
                similarity_pct=float(relevance),
                summary=lesson,
                resolution=lesson,
                lesson=lesson,
                relevance_pct=max(0, min(100, relevance)),
                occurred_days_ago=max(0, days_ago),
            )
        )
    neighbors = incident.get("prototype_neighbors") or incident.get("nearest_neighbors") or []
    for n in neighbors[: max(0, 5 - len(similar))]:
        try:
            sim = float(n.get("similarity") or n.get("similarity_pct") or n.get("score") or 0.0)
            if sim <= 1.0:
                sim *= 100.0
            n_rc = str(n.get("root_cause") or n.get("label") or rc_id)
            similar.append(
                SimilarIncident(
                    incident_id=str(n.get("incident_id") or n.get("id") or n_rc),
                    similarity_pct=max(0.0, min(100.0, sim)),
                    summary=_noc_text(_HUMAN_LABELS.get(n_rc) or n.get("summary") or n_rc),
                    resolution=_noc_text(n.get("resolution") or "-"),
                )
            )
        except Exception:  # noqa: BLE001
            continue

    return DiagnosisEvent(
        correlation_id=alert.get("correlation_id") or f"corr-{alert.get('event_id','')}",
        causation_id=alert.get("event_id"),
        tenant_id=alert.get("tenant_id", "default"),
        zone_id=alert.get("zone_id"),
        cell_id=alert.get("cell_id"),
        node_id=alert.get("node_id"),
        producer="diagnostic",
        producer_version="1.0",
        alert_id=alert.get("event_id", ""),
        pattern_id=rc_id,
        pattern_label=str(rc_label),
        similar_incidents=similar,
        contributing_kpis=enhancement.get("contributing_kpis") or [],
        causal_edges=enhancement.get("causal_edges") or [],
        llm_summary=_noc_text(enhancement.get("llm_summary") or ""),
    )


async def _enhance_diagnosis(
    client: httpx.AsyncClient,
    alert: dict[str, Any],
    incident: dict[str, Any],
) -> dict[str, Any]:
    pattern_label = str(
        incident.get("anomaly_type")
        or incident.get("root_cause")
        or incident.get("primary_root_cause")
        or "Network condition"
    )
    contributing = _contributing_kpis(alert, incident)
    top_kpi = contributing[0]["display_label"] if contributing else "network KPI"
    similar = await _similar_incidents(client, f"{pattern_label} {top_kpi}")
    summary = await _root_cause_summary(client, pattern_label, contributing, alert.get("cell_id"))
    return {
        "contributing_kpis": contributing,
        "causal_edges": _causal_edges(contributing),
        "llm_summary": summary,
        "similar_incidents": similar,
    }


def _contributing_kpis(alert: dict[str, Any], incident: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in alert.get("top_factors") or []:
        label = str(item.get("display_label") or item.get("technical_name") or "KPI")
        name = str(item.get("technical_name") or label.lower().replace(" ", "_"))
        impact = _as_float(item.get("impact_pct"), 0.0)
        direction = -1.0 if item.get("direction") == "down" else 1.0
        out.append({"name": name, "display_label": label, "z_score": round(direction * max(0.1, impact / 25.0), 2)})
    if out:
        return out[:5]
    for item in incident.get("feature_contributions") or []:
        name = str(item.get("feature") or item.get("field") or "kpi")
        label = name.replace("_", " ").title()
        score = abs(_as_float(item.get("impact") or item.get("score") or item.get("value"), 1.0))
        out.append({"name": name, "display_label": label, "z_score": round(min(5.0, max(0.1, score)), 2)})
    return out[:5]


def _causal_edges(contributing: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(contributing) < 2:
        return []
    edges: list[dict[str, Any]] = []
    for idx, current in enumerate(contributing[:-1]):
        nxt = contributing[idx + 1]
        strength = min(1.0, max(0.1, (abs(float(current["z_score"])) + abs(float(nxt["z_score"]))) / 8.0))
        edges.append(
            {
                "from_kpi": str(current["name"]),
                "to_kpi": str(nxt["name"]),
                "lag_seconds": 30 * (idx + 1),
                "strength": round(strength, 2),
            }
        )
    return edges[:4]


async def _similar_incidents(client: httpx.AsyncClient, query: str) -> list[dict[str, Any]]:
    try:
        resp = await client.post(f"{RAG_URL}/api/memory/search", json={"q": query, "top_k": 3}, timeout=5.0)
        resp.raise_for_status()
        hits = resp.json().get("hits") or []
    except Exception as exc:  # noqa: BLE001
        log.debug("rag similar search failed: %s", exc)
        return []
    out: list[dict[str, Any]] = []
    for hit in hits[:3]:
        distance = hit.get("distance")
        relevance = 0 if distance is None else int(round(max(0.0, min(100.0, (1.0 - float(distance) / 2.0) * 100.0))))
        metadata = hit.get("metadata") if isinstance(hit.get("metadata"), dict) else {}
        out.append(
            {
                "incident_id": str(hit.get("id") or metadata.get("event_id") or "memory"),
                "lesson": str(hit.get("lesson") or ""),
                "relevance_pct": relevance,
                "occurred_days_ago": _days_ago(metadata.get("closed_at") or metadata.get("resolved_at")),
            }
        )
    return out


async def _root_cause_summary(
    client: httpx.AsyncClient,
    pattern_label: str,
    contributing: list[dict[str, Any]],
    cell_id: Any,
) -> str:
    top = ", ".join(item["display_label"] for item in contributing[:3]) or "network KPIs"
    prompt = (
        "Root cause: {root}. Affected KPIs: {top}. Cell: {cell}. "
        "Explain what happened and what it means operationally."
    ).format(root=pattern_label, top=top, cell=cell_id or "unknown")
    system = "You explain network root causes to NOC engineers in plain language. No technical jargon. Two sentences max."
    for model in (LLM_PRIMARY, LLM_FALLBACK):
        try:
            resp = await client.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    "model": model,
                    "prompt": f"<|system|>\n{system}\n<|user|>\n{prompt}\n<|assistant|>\n",
                    "stream": False,
                    "options": {"temperature": 0.2, "num_predict": 90},
                },
                timeout=min(15.0, LLM_TIMEOUT_SECONDS),
            )
            resp.raise_for_status()
            text = str(resp.json().get("response") or "").strip()
            if text:
                return _noc_text(" ".join(text.split())[:420])
        except Exception as exc:  # noqa: BLE001
            log.debug("diagnostic llm summary failed model=%s: %s", model, exc)
    return _noc_text(
        f"{pattern_label} is affecting {top} on cell {cell_id or 'unknown'}. "
        "Operators should confirm the KPI trend is recovering before closing the incident."
    )


def _noc_text(value: Any) -> str:
    text = str(value or "")
    for banned, replacement in _NOC_TERM_REPLACEMENTS.items():
        pattern = re.escape(banned)
        if banned[:1].isalnum():
            pattern = rf"(?<![A-Za-z0-9]){pattern}"
        if banned[-1:].isalnum():
            pattern = rf"{pattern}(?![A-Za-z0-9])"
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text


def _days_ago(value: Any) -> int:
    if not value:
        return 0
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return max(0, (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).days)
    except Exception:
        return 0


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


async def _handle(
    client: httpx.AsyncClient, bus: RedisStreamsBus, _msg_id: str, alert: dict[str, Any]
) -> None:
    try:
        resp = await client.post(
            f"{DIAGNOSTIC_URL}/api/detection-agent/events",
            json=_build_payload(alert),
            timeout=10.0,
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        log.warning("diagnostic call failed: %s", exc)
        return

    incident = resp.json() or {}
    if incident.get("status") == "waiting_for_monitoring":
        # Agent didn't have enough data to diagnose — drop silently rather
        # than emit a placeholder "unknown" diagnosis.
        return
    enhancement = await _enhance_diagnosis(client, alert, incident)
    diagnosis = _to_diagnosis(alert, incident, enhancement)
    await bus.publish(StreamName.DIAGNOSIS, diagnosis)


async def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    install_sigterm_handler(log)
    init_tracer(os.getenv("OTEL_SERVICE_NAME", "diagnostic-bridge"))
    bus = RedisStreamsBus()
    await bus.connect()
    client = httpx.AsyncClient()

    for _ in range(60):
        try:
            r = await client.get(f"{DIAGNOSTIC_URL}/api/health", timeout=2.0)
            if r.status_code == 200:
                log.info("diagnostic agent ready: %s", r.json())
                break
        except httpx.HTTPError:
            pass
        await asyncio.sleep(2.0)

    async def handler(msg_id: str, payload: dict[str, Any]) -> None:
        await _handle(client, bus, msg_id, payload)

    try:
        await run_consumer(
            bus,
            StreamName.ALERTS,
            group=GROUP,
            consumer=CONSUMER,
            handler=handler,
        )
    finally:
        await client.aclose()
        await bus.close()
        flush_tracer()
        log.info("Shutdown complete")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
