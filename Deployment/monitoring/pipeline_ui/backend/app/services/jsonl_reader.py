from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from dateutil import parser as date_parser


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return date_parser.parse(value)
    except Exception:
        return None


def read_jsonl(file_path: Path, limit: int | None = None) -> list[dict[str, Any]]:
    if not file_path.exists():
        return []

    rows: list[dict[str, Any]] = []
    with file_path.open('r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    rows.append(obj)
            except json.JSONDecodeError:
                continue

    if limit is None or limit <= 0:
        return rows
    return rows[-limit:]


def tail_jsonl_raw(file_path: Path, limit: int = 100) -> list[str]:
    if not file_path.exists():
        return []
    with file_path.open('r', encoding='utf-8') as f:
        lines = [line.rstrip('\n') for line in f]
    return lines[-limit:]
