"""LLM-backed NOC alert generation (Ollama)."""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List

import requests

from config import OLLAMA_DEFAULT_MODEL, OLLAMA_DEFAULT_URL

logger = logging.getLogger(__name__)

# Get the directory where this file is located
PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


def _load_system_prompt() -> str:
    """Load system prompt from system.txt file."""
    system_file = PROMPTS_DIR / "system.txt"
    if not system_file.exists():
        logger.warning(f"System prompt file not found at {system_file}")
        return ""
    return system_file.read_text(encoding="utf-8").strip()


def _load_user_template() -> str:
    """Load user prompt template from user_template.txt file."""
    template_file = PROMPTS_DIR / "user_template.txt"
    if not template_file.exists():
        logger.warning(f"User template file not found at {template_file}")
        return ""
    return template_file.read_text(encoding="utf-8").strip()


SYSTEM_PROMPT = _load_system_prompt()
USER_TEMPLATE = _load_user_template()



RADIO_FEATURE_HINTS = (
    "rsrp",
    "rsrq",
    "sinr",
    "cqi",
    "bler",
    "handover",
    "weak_signal",
    "radio",
)

QOS_FEATURE_HINTS = (
    "latency",
    "jitter",
    "throughput",
    "packet_loss",
    "mos",
    "congestion",
    "cpu",
    "queue",
    "qos",
)


class LLMExplainer:
    def __init__(
        self,
        ollama_url: str | None = None,
        ollama_model: str | None = None,
        backend: str | None = None,  # For compatibility with tests (no-op)
    ) -> None:
        self.ollama_url = (ollama_url or os.getenv("OLLAMA_URL", OLLAMA_DEFAULT_URL)).rstrip("/")
        self.ollama_model = ollama_model or os.getenv("OLLAMA_MODEL", OLLAMA_DEFAULT_MODEL)

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
        try:
            prepared_shap = self._prepare_shap_features(shap_features)
            prepared_incidents = self._prepare_incidents(retrieved_incidents)
            layer_hint = self._infer_layer_from_shap(prepared_shap)

            # Format SHAP features for display
            shap_formatted = "\n".join(
                f"  {row['feature']} → {row['value']:+.4f} ({row['direction']})"
                for row in prepared_shap
            ) or "  (None available)"

            # Format incidents for display
            incidents_formatted = "\n".join(
                f"  {inc['incident_type'].upper()} | Severity: {inc['severity']} | "
                f"Similarity: {(1 - (inc.get('distance') or 1)) * 100:.0f}% | "
                f"Summary: {inc['summary'][:200]}"
                for inc in prepared_incidents
            ) or "  (None available)"

            # Build user prompt by formatting the template
            if not USER_TEMPLATE:
                logger.warning("User template is empty or not loaded")
                return ""
            
            max_prob = max(risk_probs.values()) if risk_probs else 0.0
            user_prompt = USER_TEMPLATE.format(
                node_id=node_id,
                timestamp=timestamp,
                capacity_exhaustion_eta_min=f"{capacity_eta_min:.0f}",
                max_risk_probability=max_prob,
                layer_hint=layer_hint,
                call_drop_risk=risk_probs.get("call_drop_risk", 0.0),
                latency_breach_risk=risk_probs.get("latency_breach_risk", 0.0),
                throughput_risk=risk_probs.get("throughput_risk", 0.0),
                jitter_risk=risk_probs.get("jitter_risk", 0.0),
                congestion_risk=risk_probs.get("congestion_risk", 0.0),
                mos_risk=risk_probs.get("mos_risk", 0.0),
                shap_features_formatted=shap_formatted,
                incidents_formatted=incidents_formatted,
                severity_band=severity_band,
                margin_to_critical=margin_to_critical,
                primary_metric=primary_metric,
            )

            text = self._ollama_generate(user_prompt)
            return self._normalize_alert_text(text)
        except Exception as e:
            logger.error(f"Error in generate_alert: {e}", exc_info=True)
            return ""

    def _prepare_shap_features(
        self, shap_features: Dict[str, List[Dict[str, Any]]] | List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        # Handle both target-grouped dict format and flat list format
        if isinstance(shap_features, dict):
            # Convert dict to flat list
            flat_list = []
            for target, features in shap_features.items():
                for feat in (features or []):
                    flat_list.append({
                        **feat,
                        "target": feat.get("target", target),
                    })
            shap_list = flat_list
        else:
            shap_list = shap_features or []
        
        cleaned: List[Dict[str, Any]] = []
        for row in shap_list:
            try:
                val = float(row.get("value", 0.0))
            except Exception:
                val = 0.0
            cleaned.append(
                {
                    "feature": str(row.get("feature", "")),
                    "value": val,
                    "direction": str(row.get("direction", "")),
                    "target": str(row.get("target", "")),
                }
            )
        cleaned.sort(key=lambda r: abs(float(r.get("value", 0.0))), reverse=True)
        return cleaned[:6]

    def _prepare_incidents(self, retrieved_incidents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        compact: List[Dict[str, Any]] = []
        for inc in (retrieved_incidents or [])[:3]:
            meta = inc.get("metadata", inc)
            compact.append(
                {
                    "incident_type": str(meta.get("incident_type", inc.get("incident_type", "unknown"))),
                    "severity": str(meta.get("severity", inc.get("severity", "unknown"))),
                    "distance": inc.get("distance"),
                    "summary": str(inc.get("document", ""))[:320],
                }
            )
        return compact

    def _infer_layer_from_shap(self, shap_rows: List[Dict[str, Any]]) -> str:
        text = " ".join(str(r.get("feature", "")).lower() for r in shap_rows)
        has_radio = any(k in text for k in RADIO_FEATURE_HINTS)
        has_qos = any(k in text for k in QOS_FEATURE_HINTS)
        if has_radio and has_qos:
            return "RADIO + QoS LAYER"
        if has_radio:
            return "RADIO LAYER"
        if has_qos:
            return "QoS LAYER"
        return "UNKNOWN"

    def _normalize_alert_text(self, text: str) -> str:
        raw = (text or "").strip()
        if not raw:
            return ""

        # Remove markdown-like artifacts and compact whitespace.
        raw = raw.replace("**", "").replace("__", "")
        raw = re.sub(r"`+", "", raw)
        raw = re.sub(r"\s+", " ", raw).strip()

        # Keep a maximum of 4 sentences.
        parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", raw) if p.strip()]
        if not parts:
            return raw
        return " ".join(parts[:4]).strip()

    def _ollama_generate(self, user_prompt: str) -> str:
        """
        Generate alert via Ollama LLM.
        
        Tries /api/chat first, then /api/generate.
        Gracefully handles errors by returning empty string.
        """
        base = self.ollama_url
        timeout = 30

        try:
            # Try chat endpoint first (preferred)
            try:
                logger.info(f"Attempting Ollama /api/chat to {base} with model {self.ollama_model}")
                chat_resp = requests.post(
                    f"{base}/api/chat",
                    json={
                        "model": self.ollama_model,
                        "messages": [
                            {"role": "system", "content": SYSTEM_PROMPT or "You are a NOC engineer."},
                            {"role": "user", "content": user_prompt},
                        ],
                        "stream": False,
                    },
                    timeout=timeout,
                )
                if chat_resp.ok:
                    data = chat_resp.json() or {}
                    msg = data.get("message") or {}
                    text = str(msg.get("content", "")).strip()
                    if text:
                        logger.info("Ollama chat succeeded")
                        return text
                else:
                    logger.warning(f"Ollama /api/chat returned {chat_resp.status_code}")
            except requests.exceptions.Timeout:
                logger.warning(f"Ollama /api/chat timed out after {timeout}s")
            except requests.exceptions.RequestException as e:
                logger.warning(f"Ollama /api/chat failed: {e}")

            # Fallback to generate endpoint
            try:
                logger.info(f"Attempting Ollama /api/generate to {base}")
                gen_resp = requests.post(
                    f"{base}/api/generate",
                    json={
                        "model": self.ollama_model,
                        "prompt": user_prompt,
                        "system": SYSTEM_PROMPT or "You are a NOC engineer.",
                        "stream": False,
                    },
                    timeout=timeout,
                )
                if gen_resp.ok:
                    data = gen_resp.json() or {}
                    text = str(data.get("response", "")).strip()
                    if text:
                        logger.info("Ollama generate succeeded")
                        return text
                else:
                    logger.warning(f"Ollama /api/generate returned {gen_resp.status_code}")
            except requests.exceptions.Timeout:
                logger.warning(f"Ollama /api/generate timed out after {timeout}s")
            except requests.exceptions.RequestException as e:
                logger.warning(f"Ollama /api/generate failed: {e}")

            # Both endpoints failed or returned empty - return empty alert
            logger.warning(
                f"Both Ollama endpoints failed. "
                f"Start Ollama: 'ollama serve' and pull model: 'ollama pull {self.ollama_model}'"
            )
            return ""
            
        except Exception as e:
            logger.error(f"Unexpected error in _ollama_generate: {e}", exc_info=True)
            return ""
