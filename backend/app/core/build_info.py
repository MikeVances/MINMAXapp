"""
Версия запущенного приложения — чтобы по интерфейсу было видно, какой код стоит.

Раньше /version знал только RENDER_GIT_COMMIT и везде, кроме Render, отвечал
"local": на копии в локальной сети (AGR Deploy, git clone в /srv/minmax) нельзя
было понять, обновилась ли она. Теперь, без переменных площадки, коммит, дата и
ветка берутся у самого git в каталоге приложения — один раз при старте: деплой
всё равно перезапускает процесс.
"""
from __future__ import annotations

import os
import subprocess
from functools import lru_cache
from pathlib import Path

# Семантическая версия продукта — меняется вручную на заметных выпусках
APP_VERSION = "0.3.0"

_REPO = Path(__file__).resolve().parents[3]


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(["git", "-C", str(_REPO), *args], capture_output=True, text=True, timeout=3)
        if out.returncode != 0:
            return None
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None   # git нет (контейнер без .git) — версия «unknown», не падение


@lru_cache(maxsize=1)
def build_info() -> dict:
    commit = (os.environ.get("RENDER_GIT_COMMIT") or _git("rev-parse", "HEAD") or "unknown")[:7]
    branch = os.environ.get("RENDER_GIT_BRANCH") or _git("rev-parse", "--abbrev-ref", "HEAD")
    date = _git("log", "-1", "--format=%cs")
    # Незакоммиченные правки — только при локальной разработке; на площадке их быть не должно
    dirty = bool(_git("status", "--porcelain", "--untracked-files=no"))
    return {"version": APP_VERSION, "commit": commit + ("+dirty" if dirty else ""),
            "branch": branch, "date": date}
