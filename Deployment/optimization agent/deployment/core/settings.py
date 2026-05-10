from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOCAL_STATE_ROOT = Path.home() / ".codex" / "memories" / "pi-v1"
VALID_APP_MODES = {"demo", "dev", "prod"}


def _load_env_file(path: Path) -> None:
    """Tiny `.env` loader — no third-party dep.

    Loads `KEY=VALUE` lines (ignoring `#` comments and blank lines) into the
    process env, but does not override variables already set in the real
    environment. Quoted values have their outer quotes stripped.
    """
    if not path.exists() or not path.is_file():
        return
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if not key or key in os.environ:
                continue
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            os.environ[key] = value
    except OSError:
        # Best-effort; missing/unreadable .env should never crash the app.
        return


# Load `.env` once at module import — before any dataclass defaults are read.
_load_env_file(PROJECT_ROOT / ".env")


def _env_list(name: str, default: str) -> tuple[str, ...]:
    raw = os.getenv(name, default)
    return tuple(token.strip() for token in raw.split(",") if token.strip())


def _env_str(name: str) -> str | None:
    raw = os.getenv(name)
    if raw is None:
        return None
    value = raw.strip()
    return value or None


def _default_mlflow_tracking_uri() -> str:
    db_path = (LOCAL_STATE_ROOT / "mlflow.db").as_posix()
    return f"sqlite:///{db_path}"


def _app_mode() -> str:
    raw = (_env_str("QOS_APP_MODE") or "dev").lower()
    if raw not in VALID_APP_MODES:
        return "dev"
    return raw


def _mode_default_list(name: str, default_by_mode: dict[str, str]) -> tuple[str, ...]:
    raw = _env_str(name)
    if raw is not None:
        return tuple(token.strip() for token in raw.split(",") if token.strip())
    return _env_list(name, default_by_mode.get(_app_mode(), ""))


def _mode_default_bool(name: str, default_by_mode: dict[str, bool]) -> bool:
    raw = os.getenv(name)
    if raw is not None:
        return raw.strip().lower() not in {"0", "false", "no", "off"}
    return default_by_mode.get(_app_mode(), False)


@dataclass(frozen=True)
class AccessSettings:
    viewer_tokens: tuple[str, ...] = field(
        default_factory=lambda: _mode_default_list(
            "QOS_TOKENS_VIEWER",
            {"demo": "viewer-dev-token", "dev": "viewer-dev-token", "prod": ""},
        )
    )
    engineer_tokens: tuple[str, ...] = field(
        default_factory=lambda: _mode_default_list(
            "QOS_TOKENS_ENGINEER",
            {"demo": "engineer-dev-token", "dev": "engineer-dev-token", "prod": ""},
        )
    )
    lead_tokens: tuple[str, ...] = field(
        default_factory=lambda: _mode_default_list(
            "QOS_TOKENS_LEAD",
            {"demo": "lead-dev-token", "dev": "lead-dev-token", "prod": ""},
        )
    )

    def role_for(self, token: str | None) -> str | None:
        if not token:
            return None
        if token in self.lead_tokens:
            return "lead"
        if token in self.engineer_tokens:
            return "engineer"
        if token in self.viewer_tokens:
            return "viewer"
        return None


@dataclass(frozen=True)
class LLMSettings:
    url: str = os.getenv("QOS_OLLAMA_URL", "http://localhost:11434/api/generate")
    tags_url: str = os.getenv("QOS_OLLAMA_TAGS_URL", "http://localhost:11434/api/tags")
    model: str = os.getenv("QOS_LLM_MODEL", "qwen2.5:3b")
    timeout_s: float = float(os.getenv("QOS_LLM_TIMEOUT_S", "45"))
    probe_timeout_s: float = float(os.getenv("QOS_LLM_PROBE_TIMEOUT_S", "2"))
    temperature: float = float(os.getenv("QOS_LLM_TEMPERATURE", "0.1"))
    top_p: float = float(os.getenv("QOS_LLM_TOP_P", "0.9"))


@dataclass(frozen=True)
class AlertSettings:
    poll_interval_s: float = float(os.getenv("QOS_ALERT_POLL_S", "15"))
    # Flat SLA: any pending approval untouched longer than this becomes an alert.
    pending_alert_s: int = int(os.getenv("QOS_PENDING_ALERT_S", "300"))
    # Kept for callers that still want a per-risk SLA deadline on the approval row.
    sla_low_s: int = int(os.getenv("QOS_SLA_LOW_S", "900"))
    sla_medium_s: int = int(os.getenv("QOS_SLA_MEDIUM_S", "600"))
    sla_high_s: int = int(os.getenv("QOS_SLA_HIGH_S", "300"))
    sla_critical_s: int = int(os.getenv("QOS_SLA_CRITICAL_S", "180"))


@dataclass(frozen=True)
class ApiSettings:
    cors_allowed_origins: tuple[str, ...] = field(
        default_factory=lambda: _mode_default_list(
            "QOS_CORS_ALLOW_ORIGINS",
            {
                "demo": "http://localhost:5173,http://127.0.0.1:5173",
                "dev": "http://localhost:5173,http://127.0.0.1:5173",
                "prod": "",
            },
        )
    )
    session_cookie_name: str = field(default_factory=lambda: os.getenv("QOS_SESSION_COOKIE_NAME", "qos_session"))
    session_cookie_secure: bool = field(
        default_factory=lambda: _mode_default_bool(
            "QOS_SESSION_COOKIE_SECURE",
            {"demo": False, "dev": False, "prod": True},
        )
    )
    session_ttl_s: int = field(default_factory=lambda: int(os.getenv("QOS_SESSION_TTL_S", "28800")))


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


@dataclass(frozen=True)
class AgentRuntimeSettings:
    autostart: bool = field(
        default_factory=lambda: _mode_default_bool(
            "QOS_AGENT_AUTOSTART",
            {"demo": False, "dev": False, "prod": False},
        )
    )
    startup_run: bool = field(
        default_factory=lambda: _mode_default_bool(
            "QOS_AGENT_STARTUP_RUN",
            {"demo": False, "dev": False, "prod": False},
        )
    )
    interval_s: float = field(default_factory=lambda: float(os.getenv("QOS_AGENT_INTERVAL_S", "30")))
    startup_cell_id: str | None = field(default_factory=lambda: os.getenv("QOS_AGENT_STARTUP_CELL_ID") or None)


@dataclass(frozen=True)
class JiraSettings:
    url: str = field(default_factory=lambda: os.getenv("JIRA_URL", "").rstrip("/"))
    email: str = field(default_factory=lambda: os.getenv("JIRA_EMAIL", ""))
    token: str = field(default_factory=lambda: os.getenv("JIRA_TOKEN", ""))
    project_key: str = field(default_factory=lambda: os.getenv("JIRA_PROJECT_KEY", ""))
    issue_type: str = field(default_factory=lambda: os.getenv("JIRA_ISSUE_TYPE", "Task"))
    # Transition names tried in order when closing a ticket; first match wins.
    done_transitions: tuple[str, ...] = field(
        default_factory=lambda: _env_list("JIRA_DONE_TRANSITIONS", "Done,Close,Closed,Resolve,Resolve Issue")
    )
    timeout_s: float = field(default_factory=lambda: float(os.getenv("JIRA_TIMEOUT_S", "10")))

    @property
    def configured(self) -> bool:
        return bool(self.url and self.email and self.token and self.project_key)


@dataclass(frozen=True)
class Paths:
    root: Path = PROJECT_ROOT
    samples_dir: Path = PROJECT_ROOT / "data" / "samples"
    interim_dir: Path = PROJECT_ROOT / "data" / "interim"
    config_dir: Path = PROJECT_ROOT / "deployment" / "config"
    action_contracts: Path = PROJECT_ROOT / "deployment" / "config" / "action_contracts.json"
    models_dir: Path = PROJECT_ROOT / "artifacts" / "models"
    figures_dir: Path = PROJECT_ROOT / "reports" / "figures"
    mlflow_dir: Path = LOCAL_STATE_ROOT / "mlartifacts"
    mlflow_db: Path = LOCAL_STATE_ROOT / "mlflow.db"
    store_dir: Path = LOCAL_STATE_ROOT / "store"
    store_db: Path = LOCAL_STATE_ROOT / "store" / "qos_buddy.db"
    frontend_build: Path = PROJECT_ROOT / "deployment" / "static" / "app"


@dataclass(frozen=True)
class Settings:
    app_mode: str = field(default_factory=_app_mode)
    access: AccessSettings = field(default_factory=AccessSettings)
    llm: LLMSettings = field(default_factory=LLMSettings)
    alerts: AlertSettings = field(default_factory=AlertSettings)
    api: ApiSettings = field(default_factory=ApiSettings)
    agent: AgentRuntimeSettings = field(default_factory=AgentRuntimeSettings)
    jira: JiraSettings = field(default_factory=JiraSettings)
    paths: Paths = field(default_factory=Paths)
    replay_speed: int = field(default_factory=lambda: int(os.getenv("QOS_REPLAY_SPEED", "8")))
    mlflow_tracking_uri: str = field(default_factory=lambda: os.getenv("QOS_MLFLOW_TRACKING_URI", _default_mlflow_tracking_uri()))
    mlflow_registry_uri: str | None = field(default_factory=lambda: os.getenv("QOS_MLFLOW_REGISTRY_URI") or None)
    mlflow_experiment: str = field(default_factory=lambda: os.getenv("QOS_MLFLOW_EXPERIMENT", "qos_phase3_deployment"))


_SETTINGS_CACHE: Settings | None = None
_SETTINGS_SIGNATURE: tuple[str | None] | None = None


def _settings_signature() -> tuple[str | None]:
    return (os.getenv("QOS_APP_MODE"),)


def get_settings() -> Settings:
    global _SETTINGS_CACHE, _SETTINGS_SIGNATURE
    signature = _settings_signature()
    if _SETTINGS_CACHE is None or _SETTINGS_SIGNATURE != signature:
        _SETTINGS_CACHE = Settings()
        _SETTINGS_SIGNATURE = signature
    return _SETTINGS_CACHE


def _clear_settings_cache() -> None:
    global _SETTINGS_CACHE, _SETTINGS_SIGNATURE
    _SETTINGS_CACHE = None
    _SETTINGS_SIGNATURE = None


get_settings.cache_clear = _clear_settings_cache  # type: ignore[attr-defined]


def reload_settings() -> Settings:
    """Refresh `.env`-backed config and rebuild the cached Settings object."""
    _load_env_file(PROJECT_ROOT / ".env")
    _clear_settings_cache()
    return get_settings()
