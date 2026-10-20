"""
Ключи X-API-Key и лимит частоты API v1 (этап 5б).

Зачем: публичная копия без ключа отдавала /climate-designs кому угодно — перебор
координат тратит квоту Open-Meteo площадки. Тесты держат четыре обещания README:
без API_KEYS доступ открыт как раньше; с ключами чужой запрос получает 401 раньше
любой работы; у каждого ключа свои лимиты по группам; документация открыта всегда.
"""
from __future__ import annotations

import pytest

from backend.app import api_access, api_v1
from backend.app.api_access import RateLimiter
from backend.tests.test_api_v1_audit import LOG, _entry
from backend.tests.test_api_v1_contract import _check, _response_ref
from backend.tests.test_api_v1_design import REQ as DESIGN_REQ, URL as DESIGN_URL

KEY_A = "agent-alpha-7f3c9e"
KEY_B = "agent-beta-1d8a42"


@pytest.fixture
def keys(monkeypatch):
    monkeypatch.setenv("API_KEYS", f" {KEY_A} , {KEY_B} ,")   # пробелы и пустой хвост — как набирают руками
    api_access.limiter.reset()
    yield
    api_access.limiter.reset()


@pytest.fixture
def tight(monkeypatch, keys):
    # Малые лимиты: доходим до 429 за несколько запросов, а не за 300
    small = RateLimiter({"calc": 2, "catalog": 3, "climate": 1})
    monkeypatch.setattr(api_access, "limiter", small)
    return small


def _problem(r, path: str, method: str, status: int, code: str) -> dict:
    assert r.status_code == status, r.text
    assert r.headers["content-type"].startswith("application/problem+json")
    body = r.json()
    assert body["code"] == code
    assert body["instance"] == r.headers["x-request-id"]
    _check(body, _response_ref(path, method, status, r.headers["content-type"]))
    return body


# ─── Открытый режим ───────────────────────────────────────────────────────────

def test_without_api_keys_access_stays_open(client, monkeypatch):
    # Регрессионный сторож: LAN и локальная работа без ключей — как до этапа 5б
    monkeypatch.delenv("API_KEYS", raising=False)
    assert client.get("/api/v1/sources").status_code == 200
    assert client.post(DESIGN_URL, json=DESIGN_REQ).status_code == 201


# ─── Ключ ─────────────────────────────────────────────────────────────────────

def test_missing_key_is_401_problem_in_the_log(client, keys):
    r = client.get("/api/v1/sources")
    body = _problem(r, "/sources", "get", 401, "api_key_required")
    entry = _entry(body["instance"])
    assert entry["status"] == 401 and "client" not in entry


@pytest.mark.parametrize("header", ["wrong-key", KEY_A + " ", KEY_A.upper()])
def test_wrong_key_is_401(client, keys, header):
    r = client.get("/api/v1/housing-systems", headers={"X-API-Key": header})
    _problem(r, "/housing-systems", "get", 401, "api_key_required")


def test_non_ascii_key_is_401_not_500(client, keys):
    # compare_digest на str с не-ASCII бросает TypeError — сравниваем байты
    r = client.get("/api/v1/sources", headers={"X-API-Key": "ключ".encode("utf-8")})
    assert r.status_code == 401


def test_key_is_checked_before_the_body(client, keys):
    # Чужой клиент не должен узнавать по 422, какие поля мы ждём, и тратить расчёт
    r = client.post(DESIGN_URL, json={"house": "?"})
    _problem(r, "/ventilation-designs", "post", 401, "api_key_required")


def test_unknown_path_without_key_is_401_not_404(client, keys):
    # Перебор адресов без ключа не отличает «нет маршрута» от «нет ключа»
    assert client.get("/api/v1/admin").status_code == 401


@pytest.mark.parametrize("key", [KEY_A, KEY_B])
def test_each_configured_key_works_and_is_logged_by_fingerprint(client, keys, key):
    r = client.post(DESIGN_URL, json=DESIGN_REQ, headers={"X-API-Key": key})
    assert r.status_code == 201
    entry = _entry(r.json()["request_id"])
    assert entry["client"] == api_access.key_id(key)
    # Сам ключ в журнал не попадает — журнал читают не только владельцы ключей
    assert key not in LOG.read_text(encoding="utf-8")


@pytest.mark.parametrize("path", ["/openapi.yaml", "/openapi.json", "/docs"])
def test_documentation_is_open_without_key(client, keys, path):
    # Платформа агента импортирует контракт ДО того, как ей вписали ключ
    assert client.get(f"/api/v1{path}").status_code == 200


def test_keys_do_not_touch_the_ui(client, keys):
    # Интерфейс ходит в свои маршруты, не в /api/v1 — ключ ему не нужен
    assert client.get("/version").status_code == 200


# ─── Лимит частоты ────────────────────────────────────────────────────────────

def test_catalog_limit_gives_429_with_retry_after(client, tight):
    h = {"X-API-Key": KEY_A}
    for _ in range(3):
        assert client.get("/api/v1/sources", headers=h).status_code == 200
    r = client.get("/api/v1/sources", headers=h)
    body = _problem(r, "/sources", "get", 429, "rate_limited")
    assert body["params"] == {"limit": 3, "window_s": 60}
    assert 1 <= int(r.headers["retry-after"]) <= 60
    assert _entry(body["instance"])["client"] == api_access.key_id(KEY_A)


def test_limits_are_per_key_and_per_group(client, tight):
    a, b = {"X-API-Key": KEY_A}, {"X-API-Key": KEY_B}
    for _ in range(3):
        client.get("/api/v1/sources", headers=a)
    assert client.get("/api/v1/sources", headers=a).status_code == 429
    # Справочники ключа A исчерпаны — расчёты A и справочники B живут отдельно
    assert client.post(DESIGN_URL, json=DESIGN_REQ, headers=a).status_code == 201
    assert client.get("/api/v1/sources", headers=b).status_code == 200


def test_calc_limit(client, tight):
    h = {"X-API-Key": KEY_A}
    for _ in range(2):
        assert client.post(DESIGN_URL, json=DESIGN_REQ, headers=h).status_code == 201
    r = client.post(DESIGN_URL, json=DESIGN_REQ, headers=h)
    _problem(r, "/ventilation-designs", "post", 429, "rate_limited")


def test_climate_limit_stops_before_open_meteo(client, tight, monkeypatch):
    # Ради этого лимит и делался: отказ раньше внешнего запроса, квота не тратится
    calls = []
    n = 24 * 366

    def fake_fetch(*args, **_k):
        calls.append(args)
        return [-20 + 60 * i / (n - 1) for i in range(n)], [50.0] * n, 150.0
    monkeypatch.setattr(api_v1.design_climate, "fetch_hourly", fake_fetch)
    api_v1._climate_cache.clear()
    h = {"X-API-Key": KEY_A}
    try:
        assert client.get("/api/v1/climate-designs", params={"latitude": 45.0, "longitude": 39.0},
                          headers=h).status_code == 200
        # Новая точка — промах кэша, без лимита ушла бы в Open-Meteo
        r = client.get("/api/v1/climate-designs", params={"latitude": 55.0, "longitude": 37.0},
                       headers=h)
    finally:
        api_v1._climate_cache.clear()
    _problem(r, "/climate-designs", "get", 429, "rate_limited")
    assert len(calls) == 1


def test_documentation_is_not_counted(client, tight):
    for _ in range(5):
        assert client.get("/api/v1/openapi.yaml", headers={"X-API-Key": KEY_A}).status_code == 200
    assert client.get("/api/v1/sources", headers={"X-API-Key": KEY_A}).status_code == 200


def test_production_limits_match_the_readme():
    assert api_access.LIMITS == {"calc": 60, "catalog": 300, "climate": 10}


# ─── Окно ─────────────────────────────────────────────────────────────────────

def test_sliding_window_and_retry_after():
    lim = RateLimiter({"calc": 2}, window_s=60)
    assert lim.hit("k", "calc", now=0).allowed
    assert lim.hit("k", "calc", now=10).allowed
    # Полное окно: место освободится, когда выйдет отметка t=0 — через 30 с
    v = lim.hit("k", "calc", now=30)
    assert not v.allowed and v.retry_after_s == 30
    assert lim.hit("k", "calc", now=60).allowed          # t=0 вышла из окна
    assert not lim.hit("k", "calc", now=60.5).allowed    # в окне t=10 и t=60
    # Отказ не занимает место: иначе клиент, повторяющий запрос, не дождался бы никогда
    assert lim.hit("k", "calc", now=70).allowed


def test_retry_after_is_never_zero():
    lim = RateLimiter({"calc": 1}, window_s=60)
    lim.hit("k", "calc", now=0)
    assert lim.hit("k", "calc", now=59.99).retry_after_s == 1


def test_zero_limit_closes_the_group():
    # Лимит 0 — естественный способ закрыть группу; пустое окно не должно ронять сервер
    v = RateLimiter({"climate": 0}, window_s=60).hit("k", "climate", now=0)
    assert not v.allowed and v.retry_after_s == 60
