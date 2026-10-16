"""
Пути к файлам данных не зависят от рабочей директории (TODO P0, ревью 2026-10-16).

Раньше пути были относительными ("data/day_master.json"): запуск из корня брал
data/ (в проде — заниженная кривая веса), запуск из backend/ — backend/data/.
Один и тот же код считал по разным профилям роста.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# Переменные, которые conftest выставляет для изоляции тестов, —
# в «чистом» процессе их быть не должно
_DATA_ENV_VARS = ("DAY_MASTER_JSON", "APP_CONFIG_JSON", "THERMAL_CONFIG_JSON", "FLOCKS_DATA_DIR")


def _run_clean(code: str, cwd: Path, extra_env: dict | None = None) -> str:
    """Выполнить код в отдельном процессе: без env-переменных данных и из чужого каталога."""
    env = {k: v for k, v in os.environ.items() if k not in _DATA_ENV_VARS}
    env["PYTHONPATH"] = str(REPO_ROOT)
    env.update(extra_env or {})
    return subprocess.run(
        [sys.executable, "-c", code], cwd=cwd, env=env,
        capture_output=True, text=True, check=True,
    ).stdout.strip()


@pytest.mark.parametrize(
    "module, attr, expected",
    [
        ("backend.app.core.day_master", "DAY_MASTER_PATH", "data/day_master.json"),
        ("backend.app.core.app_config", "APP_CONFIG_PATH", "data/app_config.json"),
        ("backend.app.core.building_thermal", "THERMAL_CONFIG_PATH", "data/thermal_config.json"),
        ("backend.app.core.flock_storage", "FLOCKS_DATA_DIR", "data/flocks"),
    ],
)
def test_default_path_points_to_project_data_from_any_cwd(module, attr, expected, tmp_path):
    out = _run_clean(f"import {module} as m; print(m.{attr})", cwd=tmp_path)
    assert Path(out) == (REPO_ROOT / expected).resolve()


def test_relative_env_path_resolves_from_project_root(tmp_path):
    """Относительный путь в env тоже считается от корня проекта, а не от CWD."""
    out = _run_clean(
        "import backend.app.core.day_master as m; print(m.DAY_MASTER_PATH)",
        cwd=tmp_path, extra_env={"DAY_MASTER_JSON": "data/other.json"},
    )
    assert Path(out) == (REPO_ROOT / "data/other.json").resolve()


def test_profile_loader_reads_day_master_from_env():
    """
    get_profile_from_day_master() раньше хардкодил "data/day_master.json" и
    игнорировал DAY_MASTER_JSON. conftest подставляет синтетический профиль:
    день 21 = 1012 г — значение, которого нет ни в одном реальном файле data/.
    """
    from backend.app.core.profile_loader import get_profile_from_day_master

    profile = get_profile_from_day_master()
    assert profile is not None
    day21 = next(p for p in profile.points["winter"] if p.day == 21)
    assert day21.body_weight_g == 1012
