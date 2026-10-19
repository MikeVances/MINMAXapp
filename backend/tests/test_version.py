"""
Версия в интерфейсе (2026-10-19): /version отвечал "local" везде, кроме Render,
и по копии в локальной сети нельзя было понять, какой код на ней стоит.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from backend.app.core import build_info as bi

ROOT = Path(__file__).resolve().parents[2]


def test_version_names_the_git_commit(client):
    v = client.get("/version").json()
    head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short=7", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    assert v["version"] == bi.APP_VERSION
    assert v["commit"].split("+")[0] == head
    assert v["date"] and v["branch"]


def test_platform_variable_wins(monkeypatch):
    monkeypatch.setenv("RENDER_GIT_COMMIT", "0123456789abcdef")
    bi.build_info.cache_clear()
    try:
        assert bi.build_info()["commit"].startswith("0123456")
    finally:
        bi.build_info.cache_clear()


def test_every_page_shows_the_version():
    ui = (ROOT / "backend" / "app" / "static" / "ui.js").read_text(encoding="utf-8")
    assert "fetch('./version')" in ui and "appVersion" in ui
    for page in ("index.html", "calculators.html", "settings.html"):
        assert "./ui.js" in (ROOT / "backend" / "app" / "static" / page).read_text(encoding="utf-8"), page
