"""
GET/PUT /settings/app-config — функционально, через API (аудит 2026-10-18:
эндпоинт был покрыт только проверкой токена записи).

Настройки — общий файл на всех посетителей, и их ошибка ломает расчёты у всех
сразу. Поэтому проверяется не только «сохранилось», но и что неверная запись
отклоняется, не трогая файл, и что сохранённое реально доходит до расчёта.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from conftest import FIXTURE_PROFILE_ID

CFG_PATH = Path(os.environ["APP_CONFIG_JSON"])
CALC = {"house": "1", "birds": 30000, "age_days": 21, "outside_t": 10}
CUSTOM = {
    "name": "Своя кривая", "breed": "Test",
    "points": [{"day": 1, "body_weight_g": 50.0, "min_temp_c": 33.0},
               {"day": 42, "body_weight_g": 3000.0, "min_temp_c": 19.0}],
}


@pytest.fixture(autouse=True)
def restore_config():
    """Файл общий для всей сессии тестов — после каждого теста возвращаем как был."""
    before = CFG_PATH.read_bytes()
    yield
    CFG_PATH.write_bytes(before)


def test_get_returns_the_saved_file(client):
    cfg = client.get("/settings/app-config").json()
    assert cfg["default_growth_profile"] == FIXTURE_PROFILE_ID
    assert cfg["cycle_days"] == 42 and cfg["total_mortality_pct"] == 0.0


def test_put_round_trips_and_reaches_the_calculation(client):
    cfg = client.get("/settings/app-config").json()
    cfg.update(cycle_days=49, total_mortality_pct=3.0)
    r = client.put("/settings/app-config", json=cfg)
    assert r.status_code == 200, r.text

    assert client.get("/settings/app-config").json() == cfg
    # Длина цикла — день, на который summary7 даёт цель скорости туннеля
    s = client.post("/calc/summary7", json=CALC).json()
    assert s["tunnel_target_day"] == 49


def test_out_of_range_is_rejected_and_file_untouched(client):
    before = CFG_PATH.read_bytes()
    cfg = client.get("/settings/app-config").json()
    cfg["cycle_days"] = 100
    assert client.put("/settings/app-config", json=cfg).status_code == 422
    assert CFG_PATH.read_bytes() == before


def test_unknown_default_profile_is_rejected(client):
    """Раньше сохранялся с 200 — и каждый расчёт главной отвечал 404 у всех."""
    before = CFG_PATH.read_bytes()
    cfg = client.get("/settings/app-config").json()
    cfg["default_growth_profile"] = "no-such-profile"
    r = client.put("/settings/app-config", json=cfg)
    assert r.status_code == 422
    assert r.json()["detail"] == {"code": "profile_not_found", "params": {"id": "no-such-profile"}}
    assert CFG_PATH.read_bytes() == before
    assert client.post("/calc/minmax", json=CALC).status_code == 200


def test_default_profile_cannot_be_deleted(client):
    assert client.put("/profiles/my-default", json=CUSTOM).status_code == 200
    cfg = client.get("/settings/app-config").json()
    cfg["default_growth_profile"] = "my-default"
    assert client.put("/settings/app-config", json=cfg).status_code == 200

    r = client.delete("/profiles/my-default")
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "profile_is_default"
    assert client.post("/calc/minmax", json=CALC).status_code == 200

    # Выбрали другой по умолчанию — теперь удаляется
    cfg["default_growth_profile"] = FIXTURE_PROFILE_ID
    assert client.put("/settings/app-config", json=cfg).status_code == 200
    assert client.delete("/profiles/my-default").status_code == 200


def test_profile_without_temperatures_is_rejected(client):
    """Сохранялся с 200, а каждый расчёт по нему потом отвечал 400 profile_day_missing."""
    body = {"name": "Только масса",
            "points": [{"day": 1, "body_weight_g": 50.0}, {"day": 42, "body_weight_g": 3000.0}]}
    r = client.put("/profiles/weights-only", json=body)
    assert r.status_code == 422
    assert r.json()["detail"] == "profile_needs_two_temps"   # без параметров — строка кода
    assert client.get("/profiles/weights-only").status_code == 404
