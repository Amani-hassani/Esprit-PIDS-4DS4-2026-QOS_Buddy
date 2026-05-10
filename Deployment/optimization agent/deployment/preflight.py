from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .core.settings import get_settings
from .mlops import configure_mlflow
from .release import frontend_build_status
from .store.repos import MonitoringSnapshotsRepo


@dataclass(frozen=True)
class PreflightCheck:
    name: str
    ok: bool
    detail: str
    severity: str = "error"
    meta: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "name": self.name,
            "ok": self.ok,
            "detail": self.detail,
            "severity": self.severity,
        }
        if self.meta:
            payload["meta"] = self.meta
        return payload


def _path_writable(path: Path) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    probe = path.parent / ".qos-buddy-write-check"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def run_preflight() -> dict[str, Any]:
    settings = get_settings()
    checks: list[PreflightCheck] = []

    frontend = frontend_build_status()
    checks.append(
        PreflightCheck(
            name="frontend_build",
            ok=frontend.ok,
            detail=frontend.detail,
            severity="error" if settings.app_mode == "prod" else "warning",
            meta=frontend.to_dict(),
        )
    )

    store_ok = _path_writable(settings.paths.store_db)
    checks.append(
        PreflightCheck(
            name="store_path",
            ok=store_ok,
            detail="sqlite state path is writable" if store_ok else "sqlite state path is not writable",
            meta={"path": str(settings.paths.store_db)},
        )
    )

    mlflow_ok = _path_writable(settings.paths.mlflow_db)
    checks.append(
        PreflightCheck(
            name="mlflow_path",
            ok=mlflow_ok,
            detail="MLflow state path is writable" if mlflow_ok else "MLflow state path is not writable",
            meta={"path": str(settings.paths.mlflow_db)},
        )
    )

    access_tokens = (
        len(settings.access.viewer_tokens) + len(settings.access.engineer_tokens) + len(settings.access.lead_tokens)
    )
    checks.append(
        PreflightCheck(
            name="access_bootstrap",
            ok=access_tokens > 0,
            detail=(
                "authentication bootstrap tokens configured"
                if access_tokens > 0
                else "no authentication bootstrap tokens configured"
            ),
            severity="error" if settings.app_mode == "prod" else "warning",
            meta={"token_count": access_tokens, "app_mode": settings.app_mode},
        )
    )

    live_snapshot = MonitoringSnapshotsRepo.latest()
    live_required = settings.app_mode == "prod"
    checks.append(
        PreflightCheck(
            name="telemetry_source",
            ok=live_snapshot is not None or not live_required,
            detail=(
                "live monitoring snapshot available"
                if live_snapshot is not None
                else "live telemetry is required in prod mode but no monitoring snapshots are present"
                if live_required
                else "no live monitoring snapshot yet; sample fallback is still allowed in this mode"
            ),
            severity="error" if live_required else "warning",
        )
    )

    checks.append(
        PreflightCheck(
            name="jira_provider",
            ok=settings.jira.configured,
            detail="Jira provider configured" if settings.jira.configured else "Jira provider not configured; tickets will stay local-only",
            severity="warning",
        )
    )

    mlflow = configure_mlflow()
    checks.append(
        PreflightCheck(
            name="mlflow_backend",
            ok=bool(mlflow.get("available")),
            detail=str(mlflow.get("error") or "MLflow configured"),
            severity="warning",
            meta={
                "tracking_uri": mlflow.get("tracking_uri"),
                "experiment_name": mlflow.get("experiment_name"),
                "available": mlflow.get("available"),
            },
        )
    )

    ok = all(check.ok or check.severity != "error" for check in checks)
    return {
        "ok": ok,
        "app_mode": settings.app_mode,
        "checks": [check.to_dict() for check in checks],
    }


def _main() -> int:
    payload = run_preflight()
    print(json.dumps(payload, indent=2))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(_main())
