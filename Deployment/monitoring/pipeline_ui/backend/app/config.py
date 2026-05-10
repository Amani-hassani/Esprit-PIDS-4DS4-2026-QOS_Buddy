from __future__ import annotations

from pathlib import Path
from pydantic import BaseModel


class Settings(BaseModel):
    project_root: Path
    network_stream_file: Path
    monitoring_events_file: Path
    workflow_actions_file: Path


def get_settings() -> Settings:
    project_root = Path(__file__).resolve().parents[3]
    return Settings(
        project_root=project_root,
        network_stream_file=project_root / 'network_stream.jsonl',
        monitoring_events_file=project_root / 'monitoring_events.jsonl',
        workflow_actions_file=project_root / 'workflow_actions.jsonl',
    )
