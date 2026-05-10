from __future__ import annotations

from ..core.access import optional_principal, require_role
from ..llmops.client import ReasonerClient


viewer_required = require_role("viewer")
engineer_required = require_role("engineer")
lead_required = require_role("lead")
optional_principal_dep = optional_principal


# Singleton ReasonerClient — registers prompts once, shares cache lookups across requests.
_reasoner_singleton: ReasonerClient | None = None


def get_reasoner() -> ReasonerClient:
    global _reasoner_singleton
    if _reasoner_singleton is None:
        _reasoner_singleton = ReasonerClient()
    return _reasoner_singleton


def reset_reasoner_for_tests() -> None:
    global _reasoner_singleton
    _reasoner_singleton = None
