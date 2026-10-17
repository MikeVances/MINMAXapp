"""
Токен на запись (TODO P0, ревью 2026-10-16: запись открыта всем).

Render — общая тестовая площадка: без токена любой посетитель мог перезаписать
настройки или удалить дневник стада. С WRITE_TOKEN изменяющие эндпоинты
требуют X-Write-Token; расчёты остаются открытыми.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.core.building_thermal import THERMAL_CONFIG_PATH

TOKEN = "test-token-42"

# Все эндпоинты, которые меняют сохранённые данные
WRITE_ROUTES = [
    ("PUT", "/profiles/my-profile"),
    ("DELETE", "/profiles/my-profile"),
    ("PUT", "/settings/app-config"),
    ("PUT", "/thermal/config"),
]


@pytest.fixture
def token_set(monkeypatch):
    monkeypatch.setenv("WRITE_TOKEN", TOKEN)


@pytest.fixture
def clean_thermal_config():
    path = Path(THERMAL_CONFIG_PATH)
    yield
    path.unlink(missing_ok=True)


@pytest.mark.parametrize("method, url", WRITE_ROUTES)
def test_write_route_requires_token(client, token_set, method, url):
    """
    Пустое тело: если бы токен не проверялся, ответ был бы 422 (валидация)
    или 2xx/4xx от самого обработчика. 401 с нашим кодом возможен только
    от require_write_token.
    """
    r = client.request(method, url, json={})

    assert r.status_code == 401
    assert r.json()["detail"] == "write_token_required"


def test_wrong_token_is_rejected(client, token_set, clean_thermal_config):
    r = client.put("/thermal/config", json={"house_id": "1"}, headers={"X-Write-Token": "nope"})

    assert r.status_code == 401


def test_non_ascii_token_is_rejected_not_crashing(client, token_set, clean_thermal_config):
    """compare_digest на str с не-ASCII бросает TypeError — должно быть 401, не 500."""
    r = client.put("/thermal/config", json={"house_id": "1"},
                   headers={"X-Write-Token": "токен".encode("utf-8")})

    assert r.status_code == 401


def test_correct_token_allows_write(client, token_set, clean_thermal_config):
    r = client.put("/thermal/config", json={"house_id": "1"}, headers={"X-Write-Token": TOKEN})

    assert r.status_code == 200


def test_without_server_token_write_is_open(client, monkeypatch, clean_thermal_config):
    """Локальная разработка: WRITE_TOKEN не задан — запись без заголовка."""
    monkeypatch.delenv("WRITE_TOKEN", raising=False)

    assert client.put("/thermal/config", json={"house_id": "1"}).status_code == 200


def test_calculations_do_not_require_token(client, token_set):
    payload = dict(house="1", birds=10_000, age_days=21, outside_t=25.0)

    assert client.post("/calc/minmax", json=payload).status_code == 200
