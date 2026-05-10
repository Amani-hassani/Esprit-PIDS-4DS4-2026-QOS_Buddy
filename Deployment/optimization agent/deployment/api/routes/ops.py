from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from ...core.access import Principal
from ...llmops import drift_report
from ...llmops.client import LLMCall
from ...llmops.prompts import register_all
from ...mlops import mlops_status, recent_runs, recent_traces
from ...preflight import run_preflight
from ...store.repos import LLMCacheRepo, PromptRegistryRepo
from ..deps import engineer_required, get_reasoner, viewer_required


router = APIRouter(prefix="/api/ops", tags=["ops"])
logger = logging.getLogger("qos_buddy.api.ops")


@router.get("/health")
def health(principal: Principal = Depends(viewer_required)):
    reasoner = get_reasoner()
    ok, err = reasoner._probe()
    return {
        "llm": {"available": ok, "model": reasoner.model, "url": reasoner.url, "error": err},
        "mlops": mlops_status(),
        "store": "ok",
    }


@router.get("/mlops")
def mlops(principal: Principal = Depends(viewer_required)):
    return {
        "status": mlops_status(),
        "recent_runs": recent_runs(limit=15),
        "recent_traces": recent_traces(limit=15),
    }


@router.get("/drift")
def drift(
    window: int = 300,
    principal: Principal = Depends(viewer_required),
):
    try:
        return drift_report(window=window)
    except Exception as exc:
        logger.warning("drift report failed: %s", exc)
        return {
            "columns": [],
            "overall_drift": 0.0,
            "window_rows": 0,
            "baseline_missing": True,
            "baseline_unavailable": True,
            "scored_columns": 0,
            "error": str(exc),
        }


@router.get("/llm-cache")
def cache_stats(principal: Principal = Depends(viewer_required)):
    return LLMCacheRepo.stats()


@router.get("/prompts")
def prompts(principal: Principal = Depends(viewer_required)):
    register_all()
    return {"items": PromptRegistryRepo.all()}


@router.get("/preflight")
def preflight(principal: Principal = Depends(viewer_required)):
    return run_preflight()


@router.post("/llm-healthcheck")
def llm_healthcheck(principal: Principal = Depends(engineer_required)):
    reasoner = get_reasoner()
    call = LLMCall(prompt_name="llm.healthcheck", variables={}, kind="healthcheck", bypass_cache=True)
    response = reasoner.call(call)
    return {
        "available": response.available,
        "model": response.model,
        "latency_ms": response.latency_ms,
        "error": response.error,
        "reasoning_id": response.reasoning_id,
    }
