"""
Имя корпуса в /thermal/config (TODO P0, ревью 2026-10-16: stored XSS).

house_id сохранялся без ограничений и вставлялся в innerHTML на странице
калибровки — у каждого, кто её откроет.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.app.core.building_thermal import THERMAL_CONFIG_PATH

XSS_HOUSE_ID = '<img src=x onerror=alert(1)>'


@pytest.fixture
def clean_thermal_config():
    """Тесты пишут thermal_config в общий временный каталог — убрать за собой."""
    path = Path(THERMAL_CONFIG_PATH)
    yield path
    path.unlink(missing_ok=True)


def test_put_rejects_house_id_with_markup(client, clean_thermal_config):
    r = client.put("/thermal/config", json={"house_id": XSS_HOUSE_ID})

    assert r.status_code == 422
    # Отказ именно по house_id, а не по чему-то раньше по пути
    assert any(err["loc"][-1] == "house_id" for err in r.json()["detail"])
    assert not clean_thermal_config.exists()


def test_put_accepts_cyrillic_house_name(client, clean_thermal_config):
    """Шаблон не должен отсекать обычные имена корпусов."""
    r = client.put("/thermal/config", json={"house_id": "Корпус 3-А_1.2"})

    assert r.status_code == 200
    assert client.get("/thermal/config").json()["house_id"] == "Корпус 3-А_1.2"


def test_get_drops_legacy_house_id_with_markup(client, clean_thermal_config):
    """Файл, сохранённый до валидации: GET не падает с 500 и не отдаёт разметку."""
    clean_thermal_config.write_text(json.dumps({"house_id": XSS_HOUSE_ID}), encoding="utf-8")

    r = client.get("/thermal/config")

    assert r.status_code == 200
    assert r.json()["house_id"] is None
