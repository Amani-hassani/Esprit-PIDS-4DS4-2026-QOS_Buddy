"""LLM-backed NOC synthesis for standalone prediction records."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List

import requests

from config import OLLAMA_DEFAULT_MODEL, OLLAMA_DEFAULT_URL

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


def _load_text(name: str) -> str:
    path = PROMPTS_DIR / name
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


SYSTEM_PROMPT = _load_text("system.txt")

RADIO_FEATURE_HINTS = ("rsrp", "rsrq", "sinr", "cqi", "bler", "handover", "radio", "signal")
QOS_FEATURE_HINTS = ("latency", "jitter", "throughput", "packet_loss", "mos", "congestion", "cpu", "queue")


class LLMExplainer:
    def __init__(
        self,
        ollama_url: str | None = None,
        ollama_model: str | None = None,
        backend: str | None = None,
    ) -> None:
        self.ollama_url = (ollama_url or os.getenv("OLLAMA_URL", OLLAMA_DEFAULT_URL)).rstrip("/")
        self.ollama_model = ollama_model or os.getenv("OLLAMA_MODEL", OLLAMA_DEFAULT_MODEL)

    def generate_prediction_brief(
        self,
        *,
        node_id: str,
        timestamp: str,
        severity_band: str,
        primary_metric: str,
        primary_probability: float,
        capacity_eta_min: float,
        primary_metric_eta_min: float,
        eta_per_target: Dict[str, float],
        eta_notes: Dict[str, str],
        decision_thresholds: Dict[str, float],
        confidence_score: float,
        domain_hints: List[Dict[str, Any]],
        risk_probs: Dict[str, float],
        shap_features: Dict[str, List[Dict[str, Any]]] | List[Dict[str, Any]],
        temporal_signals: Dict[str, Any],
        trust_signals: Dict[str, Any],
        retrieved_incidents: List[Dict[str, Any]],
    ) -> str:
        prepared_shap = self._prepare_shap_features(shap_features)
        prepared_incidents = self._prepare_incidents(retrieved_incidents)
        layer_hint = self._infer_layer_from_shap(prepared_shap)
        top_domain = domain_hints[0]["domain"] if domain_hints else "unknown"

        shap_formatted = "\n".join(
            f"- {row['target'] or primary_metric}: {row['feature']} -> {row['value']:+.4f} ({row['direction']})"
            for row in prepared_shap[:5]
        ) or "- none"
        incidents_formatted = "\n".join(
            f"- {inc['incident_type']} ({inc['severity']}), similarity={inc['similarity_pct']}%, {inc['summary']}"
            for inc in prepared_incidents[:3]
        ) or "- none"
        tte_formatted = "\n".join(
            f"- {target}: {self._format_eta_minutes(value)} [{eta_notes.get(target, 'n/a')}]"
            for target, value in sorted(eta_per_target.items())
        ) or "- none"
        urgency = self._urgency_label(primary_metric_eta_min)

        prompt = (
            f"Node: {node_id}\n"
            f"Timestamp: {timestamp}\n"
            f"Severity: {severity_band}\n"
            f"Primary metric: {primary_metric} ({primary_probability:.2f})\n"
            f"Capacity ETA: {capacity_eta_min:.1f}\n"
            f"Primary time-to-event ETA: {self._format_eta_minutes(primary_metric_eta_min)}\n"
            f"Urgency window: {urgency}\n"
            f"Confidence: {confidence_score:.2f}\n"
            f"Predicted domain: {top_domain}\n"
            f"Layer hint: {layer_hint}\n"
            f"Decision thresholds: {decision_thresholds}\n"
            f"Temporal signals: {temporal_signals}\n"
            f"Trust signals: {trust_signals}\n"
            f"Risk probabilities: {risk_probs}\n"
            f"Per-target time-to-event:\n{tte_formatted}\n"
            f"Top drivers:\n{shap_formatted}\n"
            f"Similar incidents:\n{incidents_formatted}\n"
            "Write a concise NOC-oriented brief in 3 sentences: risk, time-to-event urgency, likely cause domain, and what to inspect next."
        )

        text = self._ollama_generate(prompt)
        if text:
            return self._normalize_alert_text(text)
        return self._fallback_brief(
            node_id=node_id,
            severity_band=severity_band,
            primary_metric=primary_metric,
            primary_probability=primary_probability,
            capacity_eta_min=capacity_eta_min,
            primary_metric_eta_min=primary_metric_eta_min,
            confidence_score=confidence_score,
            domain_hints=domain_hints,
            temporal_signals=temporal_signals,
            prepared_incidents=prepared_incidents,
        )

    def generate_alert(
        self,
        risk_probs: Dict[str, float],
        shap_features: Dict[str, List[Dict[str, Any]]] | List[Dict[str, Any]],
        retrieved_incidents: List[Dict[str, Any]],
        node_id: str,
        timestamp: str,
        capacity_eta_min: float,
        severity_band: str = "UNKNOWN",
        margin_to_critical: float = 0.0,
        primary_metric: str = "unknown",
    ) -> str:
        return self.generate_prediction_brief(
            node_id=node_id,
            timestamp=timestamp,
            severity_band=severity_band,
            primary_metric=primary_metric,
            primary_probability=max(risk_probs.values()) if risk_probs else 0.0,
            capacity_eta_min=capacity_eta_min,
            primary_metric_eta_min=capacity_eta_min,
            eta_per_target={primary_metric: capacity_eta_min},
            eta_notes={primary_metric: "alert_path"},
            decision_thresholds={},
            confidence_score=max(0.0, min(1.0, 0.5 + margin_to_critical)),
            domain_hints=[],
            risk_probs=risk_probs,
            shap_features=shap_features,
            temporal_signals={"margin_to_critical": margin_to_critical},
            trust_signals={},
            retrieved_incidents=retrieved_incidents,
        )

    def _fallback_brief(
        self,
        *,
        node_id: str,
        severity_band: str,
        primary_metric: str,
        primary_probability: float,
        capacity_eta_min: float,
        primary_metric_eta_min: float,
        confidence_score: float,
        domain_hints: List[Dict[str, Any]],
        temporal_signals: Dict[str, Any],
        prepared_incidents: List[Dict[str, Any]],
    ) -> str:
        domain = domain_hints[0]["domain"] if domain_hints else "unknown"
        eta_text = "no near-term threshold crossing" if capacity_eta_min == float("inf") else f"ETA {capacity_eta_min:.0f} min"
        tte_text = self._format_eta_minutes(primary_metric_eta_min)
        urgency = self._urgency_label(primary_metric_eta_min)
        incident_text = prepared_incidents[0]["incident_type"] if prepared_incidents else "no close historical incident"
        velocity = temporal_signals.get("risk_velocity", 0.0)
        direction = "rising" if float(velocity) > 0.03 else "stable" if abs(float(velocity)) <= 0.03 else "cooling"
        return (
            f"{severity_band.upper()} risk on {node_id}: {primary_metric} is at {primary_probability:.0%} with primary TTE {tte_text} and {eta_text}. "
            f"Urgency is {urgency}; likely domain is {domain} and the risk trend is {direction}; confidence is {confidence_score:.0%}. "
            f"Closest supporting memory is {incident_text}."
        )

    def _format_eta_minutes(self, value: float) -> str:
        try:
            eta = float(value)
        except Exception:
            return "n/a"
        if eta == float("inf") or eta != eta:
            return "no near-term crossing"
        return f"{eta:.1f} min"

    def _urgency_label(self, primary_metric_eta_min: float) -> str:
        try:
            eta = float(primary_metric_eta_min)
        except Exception:
            return "MONITORING"
        if eta == float("inf") or eta != eta:
            return "MONITORING"
        if eta < 5.0:
            return "IMMEDIATE"
        if eta < 15.0:
            return "URGENT"
        if eta < 30.0:
            return "SOON"
        return "MONITORING"

    def _prepare_shap_features(
        self, shap_features: Dict[str, List[Dict[str, Any]]] | List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        if isinstance(shap_features, dict):
            flat_list: List[Dict[str, Any]] = []
            for target, features in shap_features.items():
                for feat in features or []:
                    flat_list.append({**feat, "target": feat.get("target", target)})
            shap_list = flat_list
        else:
            shap_list = shap_features or []

        cleaned: List[Dict[str, Any]] = []
        for row in shap_list:
            try:
                value = float(row.get("value", 0.0))
            except Exception:
                value = 0.0
            cleaned.append(
                {
                    "feature": str(row.get("feature", "")),
                    "value": value,
                    "direction": str(row.get("direction", "")),
                    "target": str(row.get("target", "")),
                }
            )
        cleaned.sort(key=lambda item: abs(item["value"]), reverse=True)
        return cleaned[:6]

    def _prepare_incidents(self, retrieved_incidents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        compact: List[Dict[str, Any]] = []
        for incident in (retrieved_incidents or [])[:3]:
            meta = incident.get("metadata", incident)
            distance = incident.get("distance")
            similarity = 0.0 if distance is None else max(0.0, min(100.0, (1.0 - float(distance)) * 100.0))
            compact.append(
                {
                    "incident_type": str(meta.get("incident_type", incident.get("incident_type", "unknown"))),
                    "severity": str(meta.get("severity", incident.get("severity", "unknown"))),
                    "similarity_pct": round(similarity, 1),
                    "summary": str(incident.get("document", ""))[:280],
                }
            )
        return compact

    def _infer_layer_from_shap(self, shap_rows: List[Dict[str, Any]]) -> str:
        text = " ".join(str(item.get("feature", "")).lower() for item in shap_rows)
        has_radio = any(token in text for token in RADIO_FEATURE_HINTS)
        has_qos = any(token in text for token in QOS_FEATURE_HINTS)
        if has_radio and has_qos:
            return "RADIO + QOS"
        if has_radio:
            return "RADIO"
        if has_qos:
            return "QOS"
        return "UNKNOWN"

    def _normalize_alert_text(self, text: str) -> str:
        raw = (text or "").strip()
        if not raw:
            return ""
        raw = raw.replace("**", "").replace("__", "")
        raw = re.sub(r"`+", "", raw)
        raw = re.sub(r"\s+", " ", raw).strip()
        parts = [segment.strip() for segment in re.split(r"(?<=[.!?])\s+", raw) if segment.strip()]
        return " ".join(parts[:4]).strip() if parts else raw

    def _ollama_generate(self, prompt: str) -> str:
        timeout = 20
        try:
            response = requests.post(
                f"{self.ollama_url}/api/chat",
                json={
                    "model": self.ollama_model,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT or "You are a telecom NOC prediction analyst."},
                        {"role": "user", "content": prompt},
                    ],
                    "stream": False,
                },
                timeout=timeout,
            )
            if response.ok:
                payload = response.json() or {}
                message = payload.get("message") or {}
                content = str(message.get("content", "")).strip()
                if content:
                    return content
        except requests.RequestException as exc:
            logger.warning("Ollama synthesis failed: %s", exc)
        return ""
