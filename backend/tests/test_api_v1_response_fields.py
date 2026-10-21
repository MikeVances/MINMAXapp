"""
Поля ответа, которые агент раньше пересчитывал сам (приёмка Haiku 2026-10-20):
плотность посадки, целевая RH дня и правило, давшее расход туннеля.

Число, которое агент считает сам, не сверить по журналу — и оно расходится с
тем, что реально взяло ядро (падеж, RH профиля против RH запроса). Эталоны —
руками, из полей самого ответа и геометрии запроса.
"""
from __future__ import annotations

import pytest

from backend.tests.test_api_v1_contract import ROWS
from backend.tests.test_api_v1_design import FLOOR_M2, REQ, URL, VOLUME_M3, _req
from backend.tests.test_api_v1_requirements import REQ as NOW_REQ, URL as NOW_URL, _req as _now


# ─── Плотность посадки ────────────────────────────────────────────────────────

def test_density_is_live_mass_over_floor_for_any_breed(client):
    # Падеж 0 — живая птица = поголовье: 30 000 × масса дня / 1920 м²
    days = client.post(URL, json=_req(flock={"mortality_pct": 0})).json()["days"]
    for d in days:
        assert d["stocking_density_kg_m2"] == pytest.approx(30000 * d["weight_g"] / 1000 / FLOOR_M2, abs=0.05)
    # 42-й день синтетического профиля: 30 000 × 2.998 / 1920 = 46.8 кг/м²
    assert days[-1]["stocking_density_kg_m2"] == pytest.approx(46.8, abs=0.05)


def test_density_counts_mortality(client):
    # С падежом по умолчанию живой птицы меньше — плотность ниже, чем без падежа
    with_loss = client.post(URL, json=REQ).json()["days"][-1]["stocking_density_kg_m2"]
    assert with_loss < 46.8


def test_density_over_cobb_limit_warns_only_for_cobb(client):
    # 46.8 кг/м² у синтетического кросса (методика Ross): предел 42 — правило Cobb,
    # приписывать его другому кроссу нельзя
    r = client.post(URL, json=_req(flock={"mortality_pct": 0})).json()
    assert "stocking_density_high" not in {w["code"] for w in r["warnings"]}
    assert "cobb_density_transition" not in {a["code"] for a in r["assumptions"]}


def test_cages_have_no_floor_density(client):
    r = client.post(URL, json=_req(house={**REQ["house"], "cage_rows": ROWS},
                                   flock={"housing": "cages"}))
    assert r.status_code == 201
    assert all("stocking_density_kg_m2" not in d for d in r.json()["days"])


def test_requirement_density(client):
    # «Сейчас»: birds — текущее поголовье, падеж не вычитается. 10 000 × 1.012 / 1920
    j = client.post(NOW_URL, json=NOW_REQ).json()
    assert j["stocking_density_kg_m2"] == pytest.approx(10000 * 1.012 / FLOOR_M2, abs=0.05)
    assert j["weight_g"] == 1012.0


# ─── Целевая RH ───────────────────────────────────────────────────────────────

def test_target_rh_from_profile_by_default(client):
    # Профиль test-breed — 60 % на всех точках
    assert {d["target_rh_pct"] for d in client.post(URL, json=REQ).json()["days"]} == {60.0}


def test_target_rh_from_request_wins(client):
    days = client.post(URL, json=_req(flock={"target_rh_pct": 50})).json()["days"]
    assert {d["target_rh_pct"] for d in days} == {50.0}
    j = client.post(NOW_URL, json=_now(flock={**NOW_REQ["flock"], "target_rh_pct": 45})).json()
    assert j["target_rh_pct"] == 45.0


# ─── Правило туннеля ──────────────────────────────────────────────────────────

def test_tall_house_tunnel_is_set_by_air_exchange(client):
    # Средняя высота 3.5 м: смена 6720 м³ за 40 с = 604 800 м³/ч > 200 × 1920 = 384 000
    eq = client.post(URL, json=REQ).json()["equipment"]
    assert eq["tunnel_fans_basis"] == "air_exchange"
    assert eq["tunnel_fans_m3h"]["max"] == pytest.approx(VOLUME_M3 * 3600 / 40, abs=1)


def test_low_house_tunnel_is_set_by_floor_capacity(client):
    # Средняя высота (2.0 + 2.2)/2 = 2.1 м: смена 16 × 2.1 × 120 за 40 с = 362 880 м³/ч
    # < 200 × 1920 = 384 000 — правит ёмкость на м² пола
    eq = client.post(URL, json=_req(house={"wall_height_m": 2.0, "ridge_height_m": 2.2})).json()["equipment"]
    assert eq["tunnel_fans_basis"] == "floor_capacity"
    assert eq["tunnel_fans_m3h"]["max"] == pytest.approx(200 * FLOOR_M2, abs=1)


def test_cage_tunnel_is_set_by_aisle_speed(client):
    eq = client.post(URL, json=_req(house={**REQ["house"], "cage_rows": ROWS},
                                    flock={"housing": "cages"})).json()["equipment"]
    assert eq["tunnel_fans_basis"] == "aisle_speed"
