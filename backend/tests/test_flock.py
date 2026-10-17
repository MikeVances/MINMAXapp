"""
Стадо и дневник (/flock/*): метаданные, валидация, имена файлов, ответы 500.
Ревью 2026-10-16, P2.
"""
from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from backend.app.core import flock_storage

_INFO = dict(
    house_id="X", flock_name="Партия 1", placement_date="2026-10-01",
    initial_bird_count=30000, target_days=42,
)


def _post_info(client, house_id, **overrides):
    return client.post(f"/flock/{house_id}/info", json={**_INFO, **overrides})


def test_created_at_survives_update(client):
    """POST «создать или обновить» раньше ставил created_at заново при каждом вызове."""
    first = _post_info(client, "keep-created").json()
    second = _post_info(client, "keep-created", flock_name="Партия 2").json()

    assert first["created_at"] is not None
    assert second["created_at"] == first["created_at"]
    assert second["updated_at"] >= first["updated_at"]
    assert second["flock_name"] == "Партия 2"


@pytest.mark.parametrize("bad_date", ["01.10.2026", "2026-13-01", "вчера", ""])
def test_placement_date_must_be_iso(client, bad_date):
    """Нечитаемая дата раньше сохранялась, а текущий день молча становился 0."""
    r = _post_info(client, "bad-date", placement_date=bad_date)

    assert r.status_code == 422
    assert "placement_date" in r.text


def test_diary_date_must_be_iso(client):
    _post_info(client, "diary-date")
    r = client.post("/flock/diary-date/diary", json={"date": "10/01/2026", "day_of_cycle": 3})

    assert r.status_code == 422


def test_dot_and_underscore_house_ids_are_different_flocks(client):
    """Старая замена символов на «_» клеила A.1 и A_1 в один файл."""
    _post_info(client, "A.1", flock_name="dot")
    _post_info(client, "A_1", flock_name="underscore")

    assert client.get("/flock/A.1/info").json()["flock_name"] == "dot"
    assert client.get("/flock/A_1/info").json()["flock_name"] == "underscore"


def test_house_id_with_space_and_cyrillic_round_trips(client):
    house = "Корпус 7"
    _post_info(client, house, flock_name="ru")

    assert client.get(f"/flock/{house}/info").json()["flock_name"] == "ru"
    assert house in flock_storage.list_all_flocks()


def test_house_id_with_markup_is_rejected(client):
    # Без «/»: слэш делит путь и попадает в другой маршрут (405), а не в валидацию
    r = _post_info(client, "<b>x")

    assert r.status_code == 422


def test_current_day_uses_client_date(client):
    """Сервер в UTC: день цикла считается от даты, которую прислал клиент."""
    placement = date(2026, 10, 1)
    _post_info(client, "today-param", placement_date=placement.isoformat())

    r = client.get("/flock/today-param/info", params={"today": (placement + timedelta(days=9)).isoformat()})

    assert r.json()["current_day"] == 10  # день посадки = день 1


def test_internal_error_hides_details(client):
    """Текст исключения (путь на диске, позиция в JSON) не должен уходить клиенту."""
    _post_info(client, "corrupt")
    path = flock_storage._get_info_path("corrupt")
    path.write_text("{not json", encoding="utf-8")

    r = client.get("/flock/corrupt/info")

    assert r.status_code == 500
    detail = r.json()["detail"]
    assert detail == {"code": "internal_error", "params": {"operation": "load_flock_info"}}
    assert "Expecting" not in r.text and str(path) not in r.text
