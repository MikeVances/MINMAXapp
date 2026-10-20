"""
Идентификатор расчёта и журнал вызовов API v1.

Зачем: агент может пересказать «результат», которого не было (инструмент не
подключился, а описание API он знает из промта). Промт требует называть
request_id; журнал на сервере позволяет сверить, что такой расчёт был и с какими
данными. Тест — что идентификатор один и тот же в теле, заголовке и журнале.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from backend.tests.test_api_v1_design import REQ as DESIGN_REQ, URL as DESIGN_URL
from backend.tests.test_api_v1_requirements import REQ as NOW_REQ, URL as NOW_URL

LOG = Path(os.environ["API_AUDIT_LOG"])


def _entry(rid: str) -> dict:
    for line in LOG.read_text(encoding="utf-8").splitlines():
        e = json.loads(line)
        if e["request_id"] == rid:
            return e
    raise AssertionError(f"{rid} нет в журнале")


def test_design_request_id_matches_header_and_log(client):
    r = client.post(DESIGN_URL, json=DESIGN_REQ)
    rid = r.json()["request_id"]
    assert rid.startswith("req-") and r.headers["x-request-id"] == rid
    e = _entry(rid)
    assert e["status"] == 201 and e["path"].endswith("/ventilation-designs")
    # В журнале — входные данные и главные числа: по ним сверяется пересказ агента
    assert e["request"]["flock"]["birds"] == DESIGN_REQ["flock"]["birds"]
    assert e["result"]["peak"] == r.json()["peak"]


def test_requirement_request_id_matches_log(client):
    r = client.post(NOW_URL, json=NOW_REQ)
    j = r.json()
    e = _entry(j["request_id"])
    assert e["result"]["qmin_m3h"] == j["qmin_m3h"] and e["result"]["qmax_m3h"] == j["qmax_m3h"]


def test_refusals_are_logged_too(client):
    # «Посчитал», а сервер отказал — отказ должен остаться в журнале
    r = client.post(NOW_URL, json={**NOW_REQ, "flock": {**NOW_REQ["flock"], "growth_profile_id": "ross999"}})
    rid = r.json()["instance"]
    assert r.headers["x-request-id"] == rid
    e = _entry(rid)
    assert e["status"] == 404 and e["code"] == "profile_not_found"


def test_request_ids_are_unique(client):
    ids = {client.post(NOW_URL, json=NOW_REQ).json()["request_id"] for _ in range(20)}
    assert len(ids) == 20


def test_audit_failure_does_not_break_the_calculation(client, monkeypatch):
    from backend.app import api_v1

    class Broken:
        def info(self, *_):
            raise OSError("disk full")
    monkeypatch.setattr(api_v1, "_audit_logger", Broken())
    assert client.post(NOW_URL, json=NOW_REQ).status_code == 201


def test_contract_is_served_for_agent_platforms(client):
    r = client.get("/api/v1/openapi.yaml")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/yaml")
    assert "operationId: createVentilationDesign" in r.text and "request_id" in r.text


def test_missing_contract_is_a_problem_not_a_crash(client, monkeypatch, tmp_path):
    # Площадка развёрнута без docs/ — агент должен получить разбираемый отказ с
    # request_id и кодом, а не голое «Internal Server Error», которое читается как
    # «сломался калькулятор» и уводит его считать вручную
    from backend.app import api_v1
    monkeypatch.setattr(api_v1, "CONTRACT_PATH", tmp_path / "openapi.yaml")
    r = client.get("/api/v1/openapi.yaml")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["code"] == "contract_not_found"
    # Отказ записан в журнал: владелец площадки увидит, что контракт не выложен
    assert _entry(r.json()["instance"])["code"] == "contract_not_found"


def test_climate_response_has_request_id(client, monkeypatch):
    # Температуры из климата агент переносит в проект — без номера их не сверить
    from backend.app import api_v1
    n = 24 * 366
    monkeypatch.setattr(api_v1.design_climate, "fetch_hourly",
                        lambda *a, **k: ([-20 + 60 * i / (n - 1) for i in range(n)], [50.0] * n, 150.0))
    api_v1._climate_cache.clear()
    first = client.get("/api/v1/climate-designs", params={"latitude": 45.0, "longitude": 39.0})
    again = client.get("/api/v1/climate-designs", params={"latitude": 45.0, "longitude": 39.0})
    api_v1._climate_cache.clear()
    assert first.json()["request_id"] == first.headers["x-request-id"]
    # Из кэша — но со своим номером: кэш не должен раздавать чужой request_id
    assert again.json()["request_id"] != first.json()["request_id"]
    assert _entry(again.json()["request_id"])["status"] == 200
