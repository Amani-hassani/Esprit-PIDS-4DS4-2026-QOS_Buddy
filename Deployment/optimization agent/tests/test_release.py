from __future__ import annotations

import json

from deployment.api import create_app
from deployment.release import FrontendBuildStatus, frontend_build_status, write_build_meta


def test_frontend_build_status_requires_meta(tmp_path):
    frontend_dir = tmp_path / "frontend"
    build_dir = tmp_path / "build"
    (frontend_dir / "src").mkdir(parents=True)
    (frontend_dir / "src" / "app.ts").write_text("export const value = 1;\n", encoding="utf-8")
    (frontend_dir / "package.json").write_text('{"name":"demo"}\n', encoding="utf-8")
    build_dir.mkdir(parents=True)
    (build_dir / "index.html").write_text("<html></html>\n", encoding="utf-8")

    status = frontend_build_status(frontend_dir=frontend_dir, build_dir=build_dir)

    assert status.ok is False
    assert status.meta_exists is False
    assert "metadata is missing" in status.detail


def test_frontend_build_status_detects_stale_digest(tmp_path):
    frontend_dir = tmp_path / "frontend"
    build_dir = tmp_path / "build"
    (frontend_dir / "src").mkdir(parents=True)
    (frontend_dir / "src" / "app.ts").write_text("export const value = 1;\n", encoding="utf-8")
    (frontend_dir / "package.json").write_text('{"name":"demo"}\n', encoding="utf-8")
    build_dir.mkdir(parents=True)
    (build_dir / "index.html").write_text("<html></html>\n", encoding="utf-8")
    write_build_meta(frontend_dir=frontend_dir, build_dir=build_dir)
    (frontend_dir / "src" / "app.ts").write_text("export const value = 2;\n", encoding="utf-8")

    status = frontend_build_status(frontend_dir=frontend_dir, build_dir=build_dir)

    assert status.ok is False
    assert status.meta_exists is True
    assert "stale" in status.detail


def test_create_app_skips_stale_frontend_mount(monkeypatch):
    monkeypatch.setattr(
        "deployment.api.app.frontend_build_status",
        lambda build_dir=None: FrontendBuildStatus(
            ok=False,
            detail="stale build",
            build_exists=True,
            index_exists=True,
            meta_exists=True,
            source_digest="a",
            built_digest="b",
        ),
    )

    app = create_app()

    mount_names = [route.name for route in app.routes]
    assert "frontend" not in mount_names


def test_create_app_mounts_fresh_frontend(monkeypatch):
    monkeypatch.setattr(
        "deployment.api.app.frontend_build_status",
        lambda build_dir=None: FrontendBuildStatus(
            ok=True,
            detail="fresh build",
            build_exists=True,
            index_exists=True,
            meta_exists=True,
            source_digest="a",
            built_digest="a",
        ),
    )

    app = create_app()

    mount_names = [route.name for route in app.routes]
    assert "frontend" in mount_names
