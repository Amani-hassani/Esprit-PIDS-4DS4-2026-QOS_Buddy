from __future__ import annotations

import pytest
from fastapi import HTTPException

from deployment.core.access import require_role, resolve_principal
from deployment.core import settings as settings_mod


def test_resolve_principal_accepts_engineer_default_token():
    principal = resolve_principal("Bearer engineer-dev-token")
    assert principal is not None
    assert principal.role == "engineer"
    assert principal.at_least("engineer") is True
    assert principal.at_least("lead") is False


def test_resolve_principal_rejects_unknown_token():
    assert resolve_principal("Bearer junk") is None
    assert resolve_principal(None) is None
    assert resolve_principal("Basic engineer-dev-token") is None


def test_require_role_enforces_minimum():
    viewer_dep = require_role("viewer")
    lead_dep = require_role("lead")

    assert viewer_dep("Bearer viewer-dev-token").role == "viewer"

    with pytest.raises(HTTPException) as exc_info:
        viewer_dep(None)
    assert exc_info.value.status_code == 401

    with pytest.raises(HTTPException) as exc_info:
        lead_dep("Bearer engineer-dev-token")
    assert exc_info.value.status_code == 403


def test_dev_mode_keeps_local_dev_tokens(monkeypatch):
    for name in (
        "QOS_APP_MODE",
        "QOS_TOKENS_VIEWER",
        "QOS_TOKENS_ENGINEER",
        "QOS_TOKENS_LEAD",
    ):
        monkeypatch.delenv(name, raising=False)
    settings_mod.get_settings.cache_clear()

    cfg = settings_mod.get_settings()

    assert cfg.app_mode == "dev"
    assert "viewer-dev-token" in cfg.access.viewer_tokens
    assert "engineer-dev-token" in cfg.access.engineer_tokens
    assert "lead-dev-token" in cfg.access.lead_tokens


def test_prod_mode_disables_default_dev_tokens_and_hardens_api(monkeypatch):
    monkeypatch.setenv("QOS_APP_MODE", "prod")
    for name in (
        "QOS_TOKENS_VIEWER",
        "QOS_TOKENS_ENGINEER",
        "QOS_TOKENS_LEAD",
        "QOS_CORS_ALLOW_ORIGINS",
        "QOS_SESSION_COOKIE_SECURE",
    ):
        monkeypatch.delenv(name, raising=False)
    settings_mod.get_settings.cache_clear()

    cfg = settings_mod.get_settings()

    assert cfg.app_mode == "prod"
    assert cfg.access.viewer_tokens == ()
    assert cfg.access.engineer_tokens == ()
    assert cfg.access.lead_tokens == ()
    assert cfg.api.cors_allowed_origins == ()
    assert cfg.api.session_cookie_secure is True
    assert cfg.agent.autostart is False
    assert cfg.agent.startup_run is False


def test_explicit_env_overrides_mode_defaults(monkeypatch):
    monkeypatch.setenv("QOS_APP_MODE", "prod")
    monkeypatch.setenv("QOS_TOKENS_VIEWER", "custom-viewer")
    monkeypatch.setenv("QOS_CORS_ALLOW_ORIGINS", "https://ops.example")
    monkeypatch.setenv("QOS_SESSION_COOKIE_SECURE", "false")
    settings_mod.get_settings.cache_clear()

    cfg = settings_mod.get_settings()

    assert cfg.access.viewer_tokens == ("custom-viewer",)
    assert cfg.api.cors_allowed_origins == ("https://ops.example",)
    assert cfg.api.session_cookie_secure is False
