from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any

import requests

from ..core.settings import get_settings
from ..store.repos import LLMCacheRepo, ReasoningsRepo
from ..tracing import llm_span, set_outputs, set_token_usage
from .prompts import PROMPTS, PromptTemplate, register_all


@dataclass
class LLMCall:
    prompt_name: str
    variables: dict[str, Any]
    kind: str  # agent | review | healthcheck
    decision_id: str | None = None
    bypass_cache: bool = False
    timeout_s: float | None = None


@dataclass
class LLMResponse:
    available: bool
    model: str
    content: dict[str, Any]
    prompt_hash: str
    prompt_version: str
    cached: bool = False
    latency_ms: float | None = None
    error: str | None = None
    reasoning_id: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("{") and text.endswith("}"):
        return json.loads(text)
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return json.loads(text[start : end + 1])
    raise ValueError("response did not contain a JSON object")


def _cache_key(prompt_hash: str, model: str, rendered: str) -> str:
    key = hashlib.sha256(f"{prompt_hash}|{model}|{rendered}".encode("utf-8")).hexdigest()
    return key[:32]


class ReasonerClient:
    """Thin client that owns prompt rendering, response caching, and reasoning persistence."""

    _registered = False
    _probe_cache: tuple[float, bool, str | None] | None = None
    _probe_ttl_s = 15.0

    def __init__(self) -> None:
        settings = get_settings()
        self.url = settings.llm.url
        self.tags_url = settings.llm.tags_url
        self.model = settings.llm.model
        self.timeout_s = settings.llm.timeout_s
        self.probe_timeout_s = settings.llm.probe_timeout_s
        self.temperature = settings.llm.temperature
        self.top_p = settings.llm.top_p
        self._ensure_registered()

    @classmethod
    def _ensure_registered(cls) -> None:
        if cls._registered:
            return
        try:
            register_all()
        except Exception:
            # Registry writes are best-effort — don't block calls on a store hiccup.
            pass
        cls._registered = True

    def _prompt(self, name: str) -> PromptTemplate:
        if name not in PROMPTS:
            raise KeyError(f"unknown prompt: {name}")
        return PROMPTS[name]

    def _probe(self) -> tuple[bool, str | None]:
        now = time.monotonic()
        cached = self.__class__._probe_cache
        if cached is not None and (now - cached[0]) < self.__class__._probe_ttl_s:
            return cached[1], cached[2]
        try:
            probe = requests.get(self.tags_url, timeout=self.probe_timeout_s)
            probe.raise_for_status()
            models = probe.json().get("models", [])
            names = {str(m.get("name", "")) for m in models if isinstance(m, dict)}
            if names and self.model not in names:
                available = ", ".join(sorted(names)) or "none"
                result = (False, f"model {self.model} not present in local Ollama (have: {available})")
                self.__class__._probe_cache = (now, result[0], result[1])
                return result
            result = (True, None)
            self.__class__._probe_cache = (now, result[0], result[1])
            return result
        except Exception as exc:
            result = (False, str(exc))
            self.__class__._probe_cache = (now, result[0], result[1])
            return result

    def _post(self, rendered: str, *, timeout_s: float | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
        """POST the prompt to Ollama and return (parsed_json_content, raw_outer).

        Ollama's /api/generate response contains `prompt_eval_count` and
        `eval_count` — we surface them so MLflow's Token Usage chart populates.
        """
        payload = {
            "model": self.model,
            "prompt": rendered,
            "stream": False,
            "format": "json",
            "options": {"temperature": self.temperature, "top_p": self.top_p},
        }
        response = requests.post(self.url, json=payload, timeout=timeout_s if timeout_s is not None else self.timeout_s)
        response.raise_for_status()
        outer = response.json()
        content = _extract_json(str(outer.get("response", "")))
        return content, outer if isinstance(outer, dict) else {}

    def call(self, call: LLMCall) -> LLMResponse:
        prompt = self._prompt(call.prompt_name)
        rendered = prompt.render(**call.variables)
        key = _cache_key(prompt.hash, self.model, rendered)
        started = time.perf_counter()
        span_attrs = {
            "qos.prompt_name": prompt.name,
            "qos.prompt_version": prompt.version,
            "qos.prompt_hash": prompt.hash,
            "qos.kind": call.kind,
            "qos.bypass_cache": bool(call.bypass_cache),
        }
        if call.decision_id:
            span_attrs["qos.decision_id"] = call.decision_id
        with llm_span(
            f"llm.{prompt.name}",
            model=self.model,
            inputs={"prompt": rendered, "variables": call.variables},
            attributes=span_attrs,
        ) as span:
            cached_entry: dict[str, Any] | None = None
            if not call.bypass_cache:
                cached_entry = LLMCacheRepo.get(key)
            if cached_entry is not None:
                content = cached_entry.get("response", {})
                latency_ms = (time.perf_counter() - started) * 1000.0
                reasoning_id = self._persist(call, prompt, True, content, latency_ms, cached=True)
                if span is not None:
                    set_outputs(span, {"content": content, "cached": True})
                    span.set_attribute("qos.cached", True)
                    span.set_attribute("qos.latency_ms", latency_ms)
                return LLMResponse(
                    available=True,
                    model=self.model,
                    content=content,
                    prompt_hash=prompt.hash,
                    prompt_version=prompt.version,
                    cached=True,
                    latency_ms=latency_ms,
                    reasoning_id=reasoning_id,
                )
            ok, probe_err = self._probe()
            if not ok:
                latency_ms = (time.perf_counter() - started) * 1000.0
                reasoning_id = self._persist(call, prompt, False, {"error": probe_err}, latency_ms, error=probe_err)
                if span is not None:
                    set_outputs(span, {"error": probe_err, "available": False})
                    span.set_attribute("qos.available", False)
                return LLMResponse(
                    available=False,
                    model=self.model,
                    content={},
                    prompt_hash=prompt.hash,
                    prompt_version=prompt.version,
                    latency_ms=latency_ms,
                    error=probe_err,
                    reasoning_id=reasoning_id,
                )
            try:
                content, raw_outer = self._post(rendered, timeout_s=call.timeout_s)
            except Exception as exc:
                latency_ms = (time.perf_counter() - started) * 1000.0
                err = str(exc)
                reasoning_id = self._persist(call, prompt, False, {"error": err}, latency_ms, error=err)
                if span is not None:
                    set_outputs(span, {"error": err, "available": False})
                    span.set_attribute("qos.available", False)
                return LLMResponse(
                    available=False,
                    model=self.model,
                    content={},
                    prompt_hash=prompt.hash,
                    prompt_version=prompt.version,
                    latency_ms=latency_ms,
                    error=err,
                    reasoning_id=reasoning_id,
                )
            latency_ms = (time.perf_counter() - started) * 1000.0
            input_tokens = raw_outer.get("prompt_eval_count")
            output_tokens = raw_outer.get("eval_count")
            input_tokens = int(input_tokens) if isinstance(input_tokens, int) else None
            output_tokens = int(output_tokens) if isinstance(output_tokens, int) else None
            total_tokens = (input_tokens or 0) + (output_tokens or 0) if (input_tokens or output_tokens) else None
            try:
                LLMCacheRepo.put(key=key, prompt_hash=prompt.hash, model=self.model, response=content)
            except Exception:
                pass
            reasoning_id = self._persist(call, prompt, True, content, latency_ms, cached=False)
            if span is not None:
                set_outputs(span, {"content": content, "cached": False})
                set_token_usage(
                    span,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=total_tokens,
                )
                span.set_attribute("qos.latency_ms", latency_ms)
                span.set_attribute("qos.available", True)
            return LLMResponse(
                available=True,
                model=self.model,
                content=content,
                prompt_hash=prompt.hash,
                prompt_version=prompt.version,
                cached=False,
                latency_ms=latency_ms,
                reasoning_id=reasoning_id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
            )

    def _persist(
        self,
        call: LLMCall,
        prompt: PromptTemplate,
        available: bool,
        content: dict[str, Any],
        latency_ms: float,
        cached: bool = False,
        error: str | None = None,
    ) -> str:
        reasoning_text = ""
        if isinstance(content, dict):
            reasoning_text = str(content.get("reasoning") or content.get("verdict") or content.get("status") or "")
        chosen_action = None
        if isinstance(content, dict):
            chosen_action = content.get("chosen") or content.get("winner")
            if isinstance(chosen_action, str):
                chosen_action = chosen_action
            else:
                chosen_action = None
        confidence = None
        if isinstance(content, dict):
            raw_conf = content.get("confidence")
            if isinstance(raw_conf, (int, float)):
                confidence = float(raw_conf)
        try:
            return ReasoningsRepo.insert(
                decision_id=call.decision_id,
                kind=call.kind,
                prompt_hash=prompt.hash,
                prompt_version=prompt.version,
                model=self.model,
                available=available,
                chosen_action=chosen_action,
                confidence=confidence,
                reasoning_text=reasoning_text or ("cached" if cached else (error or "")),
                raw={"content": content, "cached": cached, "variables_preview": list(call.variables.keys())},
                latency_ms=latency_ms,
                error=error,
            )
        except Exception as exc:
            # Persistence failures should never break the call path.
            return f"persist_failed:{exc}"

    def healthcheck(self) -> LLMResponse:
        return self.call(LLMCall(prompt_name="llm.healthcheck", variables={}, kind="healthcheck", bypass_cache=True))
