from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from ..core.settings import get_settings


SCHEMA_FILE = Path(__file__).resolve().parent / "schema.sql"


_LOCAL = threading.local()
_INIT_LOCK = threading.Lock()
_initialized = False


def _ensure_initialized() -> None:
    global _initialized
    if _initialized:
        return
    with _INIT_LOCK:
        if _initialized:
            return
        settings = get_settings()
        settings.paths.store_dir.mkdir(parents=True, exist_ok=True)
        schema = SCHEMA_FILE.read_text(encoding="utf-8")
        with sqlite3.connect(settings.paths.store_db, timeout=5.0) as conn:
            conn.executescript(schema)
            conn.commit()
        _initialized = True


def _connect() -> sqlite3.Connection:
    settings = get_settings()
    conn = sqlite3.connect(settings.paths.store_db, timeout=5.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def _get_conn() -> sqlite3.Connection:
    _ensure_initialized()
    conn = getattr(_LOCAL, "conn", None)
    if conn is None:
        conn = _connect()
        _LOCAL.conn = conn
    return conn


@contextmanager
def cursor() -> Iterator[sqlite3.Cursor]:
    conn = _get_conn()
    cur = conn.cursor()
    try:
        cur.execute("BEGIN IMMEDIATE")
        yield cur
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        cur.close()


@contextmanager
def read_cursor() -> Iterator[sqlite3.Cursor]:
    conn = _get_conn()
    cur = conn.cursor()
    try:
        yield cur
    finally:
        cur.close()


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    return {k: row[k] for k in row.keys()}


def rows_to_list(rows) -> list[dict]:
    return [row_to_dict(r) for r in rows if r is not None]


def reset_for_tests() -> None:
    """Reset the SQLite store for tests."""
    global _initialized
    _initialized = False
    conn = getattr(_LOCAL, "conn", None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass
        delattr(_LOCAL, "conn")

    import gc
    import time

    gc.collect()
    db = get_settings().paths.store_db
    for suffix in ("", "-journal", "-wal", "-shm"):
        path = Path(str(db) + suffix)
        if not path.exists():
            continue
        try:
            path.unlink()
        except PermissionError:
            time.sleep(0.05)
            try:
                path.unlink(missing_ok=True)
            except PermissionError:
                if suffix:
                    continue
                _truncate_for_tests(db)
                break


def _truncate_for_tests(db: Path) -> None:
    with sqlite3.connect(db, timeout=5.0) as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        for row in rows:
            conn.execute(f'DELETE FROM "{row[0]}"')
        conn.execute("PRAGMA foreign_keys = ON")
        conn.commit()
