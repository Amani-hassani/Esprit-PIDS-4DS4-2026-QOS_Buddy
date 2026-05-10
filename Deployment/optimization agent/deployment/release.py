from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .core.settings import PROJECT_ROOT, get_settings


FRONTEND_SOURCE_FILES = (
    "package.json",
    "package-lock.json",
    "svelte.config.js",
    "tsconfig.json",
    "vite.config.ts",
)
FRONTEND_SOURCE_DIRS = ("src", "static")
BUILD_META_FILENAME = "build-meta.json"


def _iter_frontend_source_files(frontend_dir: Path) -> list[Path]:
    files: list[Path] = []
    for name in FRONTEND_SOURCE_FILES:
        path = frontend_dir / name
        if path.exists() and path.is_file():
            files.append(path)
    for dirname in FRONTEND_SOURCE_DIRS:
        root = frontend_dir / dirname
        if not root.exists():
            continue
        files.extend(path for path in root.rglob("*") if path.is_file())
    return sorted(files, key=lambda path: path.relative_to(frontend_dir).as_posix())


def frontend_source_digest(frontend_dir: Path | None = None) -> str:
    root = frontend_dir or (PROJECT_ROOT / "frontend")
    digest = hashlib.sha256()
    for path in _iter_frontend_source_files(root):
        rel = path.relative_to(root).as_posix()
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def build_meta_path(build_dir: Path | None = None) -> Path:
    target = build_dir or get_settings().paths.frontend_build
    return target / BUILD_META_FILENAME


def build_meta_payload(frontend_dir: Path | None = None, build_dir: Path | None = None) -> dict[str, Any]:
    source_root = frontend_dir or (PROJECT_ROOT / "frontend")
    target = build_dir or get_settings().paths.frontend_build
    return {
        "frontend_dir": str(source_root),
        "build_dir": str(target),
        "source_digest": frontend_source_digest(source_root),
    }


def write_build_meta(frontend_dir: Path | None = None, build_dir: Path | None = None) -> Path:
    target = build_meta_path(build_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(build_meta_payload(frontend_dir, build_dir), indent=2) + "\n", encoding="utf-8")
    return target


def read_build_meta(build_dir: Path | None = None) -> dict[str, Any] | None:
    path = build_meta_path(build_dir)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


@dataclass(frozen=True)
class FrontendBuildStatus:
    ok: bool
    detail: str
    build_exists: bool
    index_exists: bool
    meta_exists: bool
    source_digest: str
    built_digest: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "detail": self.detail,
            "build_exists": self.build_exists,
            "index_exists": self.index_exists,
            "meta_exists": self.meta_exists,
            "source_digest": self.source_digest,
            "built_digest": self.built_digest,
        }


def frontend_build_status(frontend_dir: Path | None = None, build_dir: Path | None = None) -> FrontendBuildStatus:
    source_root = frontend_dir or (PROJECT_ROOT / "frontend")
    target = build_dir or get_settings().paths.frontend_build
    meta = read_build_meta(target)
    source_digest = frontend_source_digest(source_root)
    build_exists = target.exists()
    index_exists = (target / "index.html").exists()
    built_digest = str(meta.get("source_digest")) if isinstance(meta, dict) and meta.get("source_digest") else None
    meta_exists = meta is not None

    if not build_exists or not index_exists:
        return FrontendBuildStatus(
            ok=False,
            detail="frontend build is missing",
            build_exists=build_exists,
            index_exists=index_exists,
            meta_exists=meta_exists,
            source_digest=source_digest,
            built_digest=built_digest,
        )
    if not meta_exists:
        return FrontendBuildStatus(
            ok=False,
            detail="frontend build metadata is missing; rebuild the static bundle",
            build_exists=build_exists,
            index_exists=index_exists,
            meta_exists=False,
            source_digest=source_digest,
            built_digest=None,
        )
    if built_digest != source_digest:
        return FrontendBuildStatus(
            ok=False,
            detail="frontend build is stale relative to frontend source",
            build_exists=build_exists,
            index_exists=index_exists,
            meta_exists=True,
            source_digest=source_digest,
            built_digest=built_digest,
        )
    return FrontendBuildStatus(
        ok=True,
        detail="frontend build matches current source",
        build_exists=build_exists,
        index_exists=index_exists,
        meta_exists=True,
        source_digest=source_digest,
        built_digest=built_digest,
    )


def _main() -> int:
    parser = argparse.ArgumentParser(description="QoS Buddy frontend release helpers")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("write-build-meta", help="Write frontend build metadata into the static bundle")
    sub.add_parser("check-build", help="Check whether the static frontend bundle matches current source")

    args = parser.parse_args()

    if args.command == "write-build-meta":
        path = write_build_meta()
        print(path)
        return 0

    status = frontend_build_status()
    print(json.dumps(status.to_dict(), indent=2))
    return 0 if status.ok else 1


if __name__ == "__main__":
    raise SystemExit(_main())
