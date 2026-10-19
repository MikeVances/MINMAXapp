"""
scripts/deploy_lan.sh — обновление копии на внутреннем сервере. Поведение
(обновление, «уже актуально», ручные правки в stash, откат при сбое, не та
ветка) проверено на копии репозитория с заглушкой службы 2026-10-19; здесь —
то, что не должно сломаться незаметно.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "deploy_lan.sh"


def test_script_is_valid_bash_and_executable():
    assert os.access(SCRIPT, os.X_OK)
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)


def test_body_runs_from_a_function():
    """git pull перезаписывает скрипт во время работы: код должен быть разобран заранее."""
    lines = [l for l in SCRIPT.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert lines[-1].startswith('main "$@"')


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="нет shellcheck")
def test_shellcheck_is_clean():
    subprocess.run(["shellcheck", str(SCRIPT)], check=True)
