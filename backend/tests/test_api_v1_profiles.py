"""
GET /api/v1/growth-profiles/{id} — профиль по дням без расчёта корпуса.

Синтетический профиль test-breed (conftest) задан четырьмя точками: дни 1, 21, 35,
42 — промежуточные дни достроены линейно, и ответ должен это показывать.
"""
from __future__ import annotations

import pytest

from backend.tests.test_api_v1_contract import _check, _response_ref

URL = "/api/v1/growth-profiles/test-breed"


def test_days_are_complete_and_interpolated_between_points(client):
    r = client.get(URL)
    assert r.status_code == 200
    days = {d["day"]: d for d in r.json()["days"]}
    assert sorted(days) == list(range(1, 43))
    # Опорные точки — как заданы
    assert days[21] == {"day": 21, "weight_g": 1012.0, "temp_c": 25.0, "rh_pct": 60.0, "interpolated": False}
    # День 28 — середина между 21 (1012 г, 25 °C) и 35 (2296 г, 20 °C), руками
    assert days[28]["interpolated"] is True
    assert days[28]["weight_g"] == pytest.approx((1012 + 2296) / 2)
    assert days[28]["temp_c"] == pytest.approx((25 + 20) / 2)


def test_each_column_has_its_own_source(client):
    # У test-breed источник массы — строка; ответ отдаёт его как {citation}
    j = client.get(URL).json()
    assert j["sources"]["weight"]["citation"].startswith("Ross 308 as-hatched 2022")


def test_matches_contract(client):
    r = client.get(URL)
    _check(r.json(), _response_ref("/growth-profiles/{profile_id}", "get", 200, r.headers["content-type"]))


@pytest.mark.parametrize("pid, status, code", [
    ("ross999", 404, "profile_not_found"),
    ("Bad Id!", 422, "validation_failed"),
])
def test_errors(client, pid, status, code):
    r = client.get(f"/api/v1/growth-profiles/{pid}")
    assert r.status_code == status and r.json()["code"] == code
    _check(r.json(), _response_ref("/growth-profiles/{profile_id}", "get", status, r.headers["content-type"]))
