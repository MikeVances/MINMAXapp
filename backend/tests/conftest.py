"""
Общая подготовка тестов.

ВАЖНО: пути к данным (GROWTH_PROFILES_DIR, APP_CONFIG_JSON, ...) читаются из окружения
в момент ИМПОРТА модулей и запекаются в значения аргументов по умолчанию.
Поэтому окружение выставляется здесь, на верхнем уровне conftest, — до того,
как какой-либо тест импортирует `backend.app`.

Тесты работают на синтетическом профиле во временном каталоге:
  - не зависят от встроенных профилей кроссов в data/growth_profiles;
  - не зависят от рабочего каталога запуска (см. TODO.md, P0 «данные зависят от CWD»);
  - никогда не перезаписывают рабочие данные проекта.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest


# ─── Синтетический профиль роста ──────────────────────────────────────────────
# Веса опорных дней 21/35/42 — Ross 308 as-hatched (Performance Objectives 2022),
# остальные поля подобраны так, чтобы ручной расчёт эталонов был прозрачным.
# Промежуточные дни заполняет штатная линейная интерполяция библиотеки профилей.
FIXTURE_PROFILE_ID = "test-breed"
FIXTURE_PROFILE = {
    "name": "Тестовый кросс",
    "breed": "Test",
    "source": {"weight": "Ross 308 as-hatched 2022 (дни 21/35/42), синтетика для тестов"},
    "points": [
        {"day": 1,  "body_weight_g": 50.0,   "min_temp_c": 33.0, "rv_percent": 60.0},
        {"day": 21, "body_weight_g": 1012.0, "min_temp_c": 25.0, "rv_percent": 60.0},
        {"day": 35, "body_weight_g": 2296.0, "min_temp_c": 20.0, "rv_percent": 60.0},
        {"day": 42, "body_weight_g": 2998.0, "min_temp_c": 19.0, "rv_percent": 60.0},
    ],
}

# Падёж 0 % — тогда birds_eff == birds, и эталоны не зависят от модели выживаемости.
# Модель выживаемости проверяется отдельным тестом через monkeypatch.
FIXTURE_APP_CONFIG = {
    "total_mortality_pct": 0.0,
    "cycle_days": 42,
    "tunnel_min_day": 14,
    "tunnel_min_temp_c": 18.0,
    "default_growth_profile": FIXTURE_PROFILE_ID,
}


_DATA_DIR = Path(tempfile.mkdtemp(prefix="minmax_tests_"))
(_DATA_DIR / "growth_profiles" / "builtin").mkdir(parents=True)
(_DATA_DIR / "growth_profiles" / "builtin" / f"{FIXTURE_PROFILE_ID}.json").write_text(
    json.dumps(FIXTURE_PROFILE), encoding="utf-8"
)
(_DATA_DIR / "app_config.json").write_text(json.dumps(FIXTURE_APP_CONFIG), encoding="utf-8")
# thermal_config.json намеренно НЕ создаётся: базовые эталоны считаются без калибровки UA
# и без горелок (UA = 0 → стены не участвуют в балансе Qmax).

os.environ["GROWTH_PROFILES_DIR"] = str(_DATA_DIR / "growth_profiles")
os.environ["APP_CONFIG_JSON"] = str(_DATA_DIR / "app_config.json")
os.environ["THERMAL_CONFIG_JSON"] = str(_DATA_DIR / "thermal_config.json")
# Тема площадки в тестах не создаётся: проверяем и «нет файла», и подмену пути
os.environ["THEME_CSS"] = str(_DATA_DIR / "theme.css")
# Журнал вызовов API v1 — во временный каталог, не в рабочий data/
os.environ["API_AUDIT_LOG"] = str(_DATA_DIR / "api_audit.jsonl")


@pytest.fixture(scope="session")
def client():
    """
    HTTP-клиент к приложению без запуска сервера.

    raise_server_exceptions=False: необработанное исключение превращается в ответ 500,
    как у живого сервера. Иначе тест «ждём 422» падал бы на самом исключении,
    не дойдя до проверки статуса, и проверял бы не то, что заявлено.
    """
    from fastapi.testclient import TestClient
    from backend.app.main import app

    return TestClient(app, raise_server_exceptions=False)
