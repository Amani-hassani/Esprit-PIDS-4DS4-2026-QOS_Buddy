"""Launch the MLflow UI against the QoS Buddy tracking store.

The agent loop logs every decision to the SQLite tracking DB at
`~/.codex/memories/pi-v1/mlflow.db` with artifacts under
`~/.codex/memories/pi-v1/mlartifacts`. Running `mlflow ui` from the project
root would default to `./mlruns`, which is empty — that's why the dashboard
appeared to show "no experiments". Run this script instead.

Usage:
    python scripts/launch_mlflow_ui.py            # binds 127.0.0.1:5000
    python scripts/launch_mlflow_ui.py --port 5050
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from deployment.core.settings import get_settings  # noqa: E402
from deployment.mlops import configure_mlflow  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    mlflow_config = configure_mlflow()
    artifact_location = str(mlflow_config.get("artifact_location") or "")
    artifact_root_default = (
        artifact_location.replace("file:///", "").replace("file://", "")
        if artifact_location.startswith("file:")
        else str(settings.paths.mlflow_dir)
    )
    parser = argparse.ArgumentParser(description="Launch MLflow UI on the QoS Buddy tracking store.")
    parser.add_argument("--host", default=os.getenv("MLFLOW_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("MLFLOW_PORT", "5000")))
    parser.add_argument("--tracking-uri", default=str(mlflow_config.get("tracking_uri") or settings.mlflow_tracking_uri))
    parser.add_argument("--artifacts-root", default=artifact_root_default)
    args = parser.parse_args(argv)

    settings.paths.mlflow_dir.mkdir(parents=True, exist_ok=True)
    settings.paths.mlflow_db.parent.mkdir(parents=True, exist_ok=True)

    mlflow_bin = shutil.which("mlflow")
    if mlflow_bin is None:
        print("error: 'mlflow' is not on PATH. install with `pip install mlflow`.", file=sys.stderr)
        return 1

    artifacts_uri = Path(args.artifacts_root).resolve().as_uri()
    cmd = [
        mlflow_bin,
        "ui",
        "--backend-store-uri",
        args.tracking_uri,
        "--default-artifact-root",
        artifacts_uri,
        "--host",
        args.host,
        "--port",
        str(args.port),
    ]

    print(f"tracking_uri = {args.tracking_uri}")
    print(f"artifacts    = {artifacts_uri}")
    print(f"binding to   = http://{args.host}:{args.port}")
    print("running:", " ".join(cmd))

    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
