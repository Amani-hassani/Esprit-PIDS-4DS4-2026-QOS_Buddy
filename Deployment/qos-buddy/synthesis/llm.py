"""
Thin async client for the local Ollama runtime (Qwen2.5-3B by default).

The synthesis agent calls this to turn structured alert context into a
NOC-language one-paragraph brief. The client is intentionally tolerant:
on any failure (timeout, connection, model unloaded) it returns a
deterministic fallback so the pipeline never stalls.

Hardware budget — GTX 1050 4GB / 16GB RAM:
  • Qwen2.5-3B q4  → ~2.5GB VRAM
  • Llama 3.2-3B q4 fallback already pre-pulled by ollama-init
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import httpx

log = logging.getLogger("qos.synthesis.llm")

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
PRIMARY_MODEL = os.getenv("LLM_PRIMARY", "qwen2.5:3b-instruct-q4_K_M")
FALLBACK_MODEL = os.getenv("LLM_FALLBACK", "llama3.2:3b-instruct-q4_K_M")
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT_SECONDS", "8.0"))

_NOC_SYSTEM = (
    "You are a network operations assistant. Write ONE concise paragraph "
    "(max 60 words) in plain NOC language for a non-technical operator. "
    "Forbidden words: anomaly, LSTM, model, embedding, FAISS, drift, SHAP, "
    "ML, AI, prophet, neural, vector. Use plain terms like 'round-trip "
    "delay', 'packet loss', 'throughput', 'similar past incidents'. "
    "End with a one-line recommendation."
)


class LlmClient:
    def __init__(self) -> None:
        self._http = httpx.AsyncClient(base_url=OLLAMA_URL, timeout=LLM_TIMEOUT)
        self._models_warmed: set[str] = set()

    async def close(self) -> None:
        await self._http.aclose()

    async def brief(self, context: dict[str, Any]) -> str:
        """Return a NOC-language paragraph for the given alert context.

        On any failure returns a deterministic fallback derived from the
        context so the pipeline always produces an InsightEvent.
        """
        prompt = _build_prompt(context)
        for model in (PRIMARY_MODEL, FALLBACK_MODEL):
            text = await self._generate(model, prompt)
            if text:
                return text
        return _fallback_brief(context)

    async def sentence(self, system: str, user: str, fallback: str) -> str:
        """Return one short sentence, with deterministic fallback."""
        prompt = f"<|system|>\n{system}\n<|user|>\n{user}\n<|assistant|>\n"
        for model in (PRIMARY_MODEL, FALLBACK_MODEL):
            text = await self._generate_with_prompt(model, prompt, num_predict=80)
            if text:
                return " ".join(text.split())[:280]
        return fallback

    async def _generate(self, model: str, prompt: str) -> str:
        full_prompt = f"<|system|>\n{_NOC_SYSTEM}\n<|user|>\n{prompt}\n<|assistant|>\n"
        return await self._generate_with_prompt(model, full_prompt, num_predict=160)

    async def _generate_with_prompt(self, model: str, prompt: str, *, num_predict: int) -> str:
        body = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.3,
                "num_predict": num_predict,
                "top_p": 0.9,
            },
        }
        try:
            resp = await self._http.post("/api/generate", json=body)
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, asyncio.TimeoutError) as exc:
            log.debug("llm call failed model=%s: %s", model, exc)
            return ""
        return (data.get("response") or "").strip()


def _build_prompt(ctx: dict[str, Any]) -> str:
    factors = ctx.get("top_factors") or []
    factor_lines = "\n".join(
        f"- {f['display_label']}: impact {f['impact_pct']:.0f}% ({f['direction']})"
        for f in factors[:4]
    ) or "- (none ranked)"
    similar = ctx.get("similar") or []
    similar_lines = "\n".join(
        f"- {s['summary']} → {s['resolution']}" for s in similar[:2]
    ) or "- (no historical match)"
    kpis = ctx.get("kpis") or {}
    kpi_lines = "\n".join(f"- {k}: {v}" for k, v in kpis.items())

    return (
        f"Alert: {ctx.get('display_label', 'Network event')} "
        f"(severity {ctx.get('severity', 'medium')}).\n"
        f"Cell: {ctx.get('cell_id') or 'unknown'}.\n\n"
        f"Live KPIs:\n{kpi_lines}\n\n"
        f"Top contributing factors:\n{factor_lines}\n\n"
        f"Similar past incidents:\n{similar_lines}\n"
    )


def _fallback_brief(ctx: dict[str, Any]) -> str:
    label = ctx.get("display_label", "Network event")
    cell = ctx.get("cell_id") or "the affected cell"
    sev = ctx.get("severity", "medium")
    factors = ctx.get("top_factors") or []
    leading = factors[0]["display_label"] if factors else "live KPIs"
    return (
        f"{label} on {cell} at {sev} severity. {leading} is the leading "
        f"contributor. Recommendation: review the proposed action and approve "
        f"if the safety checks pass."
    )
