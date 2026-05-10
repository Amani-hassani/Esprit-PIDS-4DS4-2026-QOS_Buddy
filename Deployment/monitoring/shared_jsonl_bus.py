from __future__ import annotations
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Generator, Iterable, Optional


class JSONLBus:
    """Bus partagé simple via fichier JSONL."""

    def __init__(self, bus_file: str = "network_stream.jsonl") -> None:
        self.bus_file = Path(bus_file)
        self.bus_file.parent.mkdir(parents=True, exist_ok=True)
        self.bus_file.touch(exist_ok=True)

    def publish(self, message: Dict) -> None:
        envelope = dict(message)
        envelope["published_at"] = datetime.utcnow().isoformat()
        with self.bus_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(envelope, ensure_ascii=False, default=str) + "\n")
            f.flush()

    def tail(self, poll_interval: float = 1.0, start_at_end: bool = False) -> Generator[Dict, None, None]:
        with self.bus_file.open("r", encoding="utf-8") as f:
            if start_at_end:
                f.seek(0, os.SEEK_END)
            while True:
                position = f.tell()
                line = f.readline()
                if not line:
                    f.seek(position)
                    time.sleep(poll_interval)
                    continue
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue

    def read_all(self) -> Iterable[Dict]:
        with self.bus_file.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
