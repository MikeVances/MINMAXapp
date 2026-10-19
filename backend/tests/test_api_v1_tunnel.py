"""
API v1, этап 3b: давление туннеля, рабочая точка вентиляторов, панели, впуск,
расчётный климат по координатам.

Ожидаемые числа — руками: скоростной напор ½ρv² при стандартном воздухе 1.2
(AMCA 210), впуск ½ρ(v/Cd)², панель — по таблице SANHE 7090 / 150 мм
(1.5 м/с → 32 Па, 2.0 м/с → 48 Па), рабочая точка — из квадратного уравнения,
а не той же бисекцией, что в коде.
"""
from __future__ import annotations

import math

import pytest

from backend.app import api_v1
from backend.app.core.errors import CalcError
from backend.tests.test_api_v1_design import REQ, URL, _req

Q_DESIGN = 604_800.0          # верх цели туннеля для REQ (смена воздуха за 40 с)
SECTION = 56.0
RHO = 1.2


def _p(j):
    return j["equipment"]["tunnel_static_pressure_pa"]


def test_open_end_pressure_by_hand(client):
    v = Q_DESIGN / 3600 / SECTION                      # 3.0 м/с
    section = 0.5 * RHO * v ** 2                         # 5.4 Па
    inlet = 0.5 * RHO * (v / 0.90) ** 2                  # открытый торец, Cd 0.90
    j = client.post(URL, json=REQ).json()
    p = _p(j)
    assert p["section"] == pytest.approx(section, abs=0.05)
    assert p["inlet"] == pytest.approx(inlet, abs=0.05)
    assert p["pad"] == 0 and p["length_loss"] == 0 and p["basis"] == "estimated"
    assert p["total"] == pytest.approx(section + inlet, abs=0.1)
    assert "pad_area_m2" not in j["equipment"]
    assert "tunnel_length_loss_not_included" in {a["code"] for a in j["assumptions"]}


def test_pads_add_their_resistance(client):
    j = client.post(URL, json={**REQ, "pads": {"type": "7090", "thickness_mm": 150}}).json()
    area = Q_DESIGN / 3600 / 1.78                        # UGA: 150 мм — 1.78 м/с
    assert j["equipment"]["pad_area_m2"] == pytest.approx(area, abs=0.1)
    p = _p(j)
    assert p["pad"] == pytest.approx(32 + (48 - 32) * (1.78 - 1.5) / 0.5, abs=0.1)
    assert p["inlet"] == pytest.approx(0.5 * RHO * (1.78 / 0.62) ** 2, abs=0.05)
    # Панель — главный член; выше 50 Па — повод перепроверить каталог
    assert p["total"] > 50
    assert "tunnel_pressure_high" in {w["code"] for w in j["warnings"]}


def test_cage_aisle_speed_head(client):
    rows = [{"count": 4, "width_m": 1.6, "height_m": 2.2}]
    j = client.post(URL, json=_req(flock={"housing": "cages"}, house={"cage_rows": rows})).json()
    # 5 м/с в проходах: ½·1.2·25 = 15 Па — втрое больше, чем у пола при 3 м/с
    assert _p(j)["section"] == pytest.approx(15.0, abs=0.05)


def _fans_by_hand(q0: float, slope: float, k: float, target: float) -> tuple[int, float]:
    """
    Вентилятор q = q0 − slope·P, корпус P = k·Q². n вентиляторов:
    n·(q0 − slope·k·Q²) = Q → slope·k·n·Q² + Q − n·q0 = 0.
    """
    n = 1
    while True:
        a = slope * k * n
        q = (-1 + math.sqrt(1 + 4 * a * n * q0)) / (2 * a)
        if q >= target * 0.999:
            return n, q
        n += 1


def test_fan_count_at_operating_point(client):
    # Каталог: 50 000 м³/ч при 0 Па, 30 000 при 50 Па (линейный — для ручного счёта)
    curve = {"points": [{"static_pressure_pa": 0, "flow_m3h": 50_000},
                        {"static_pressure_pa": 50, "flow_m3h": 30_000}]}
    j = client.post(URL, json={**REQ, "tunnel_fan": curve}).json()
    v = 1 / 3600 / SECTION
    k = 0.5 * RHO * (v ** 2 + (v / 0.90) ** 2)            # Па на (м³/ч)²
    n, q = _fans_by_hand(50_000, 400, k, Q_DESIGN)
    fans = j["equipment"]["tunnel_fans"]
    assert fans["count"] == n
    assert fans["flow_per_fan_m3h"] == pytest.approx(q / n, abs=2)
    assert fans["operating_pressure_pa"] == pytest.approx(k * q ** 2, abs=0.1)
    # По паспорту 0 Па вышло бы меньше: 604 800 / 50 000 → 13
    assert n > math.ceil(Q_DESIGN / 50_000)


def test_measured_pressure_replaces_estimate(client):
    j = client.post(URL, json={**REQ, "tunnel_static_pressure_pa": 45}).json()
    p = _p(j)
    assert p["basis"] == "measured" and p["total"] == 45
    assert "tunnel_length_loss_not_included" not in {a["code"] for a in j["assumptions"]}


def test_operating_point_beyond_catalogue_is_flagged(client):
    # Каталог только до 10 Па, а с панелями корпус требует > 50
    curve = {"points": [{"static_pressure_pa": 0, "flow_m3h": 45_000},
                        {"static_pressure_pa": 10, "flow_m3h": 42_000}]}
    j = client.post(URL, json={**REQ, "pads": {}, "tunnel_fan": curve}).json()
    w = [x for x in j["warnings"] if x["code"] == "fan_curve_extrapolated"]
    assert w and w[0]["params"]["last_pa"] == 10 and w[0]["params"]["pressure_pa"] > 10


@pytest.mark.parametrize("points, index", [
    ([(0, 40_000), (25, 41_000)], 1),                    # расход растёт с давлением
    ([(0, 40_000), (25, 35_000), (20, 30_000)], 2),      # давление не по возрастанию
])
def test_invalid_fan_curve(client, points, index):
    curve = {"points": [{"static_pressure_pa": p, "flow_m3h": q} for p, q in points]}
    r = client.post(URL, json={**REQ, "tunnel_fan": curve})
    assert r.status_code == 422
    assert r.json()["code"] == "fan_curve_invalid" and r.json()["params"] == {"index": index}


def test_min_vent_inlet_area_by_uga_rule(client):
    # 750 cfm на ft² = 13 717 м³/ч на м² открытого клапана
    eq = client.post(URL, json=REQ).json()["equipment"]
    assert eq["inlet_area_m2"] == pytest.approx(eq["min_vent_fans_m3h"]["max"] / 13_717, abs=0.01)


# ─── Расчётный климат ─────────────────────────────────────────────────────────

@pytest.fixture
def fake_era5(monkeypatch):
    """Год часов без сети: T от −20 до +40 °C равномерно, RH 50 %."""
    calls = []

    def fetch(lat, lon, timeout_s=60.0):
        calls.append((lat, lon))
        n = 24 * 366
        return [-20 + 60 * i / (n - 1) for i in range(n)], [50.0] * n, 150.0

    monkeypatch.setattr(api_v1.design_climate, "fetch_hourly", fetch)
    api_v1._climate_cache.clear()
    yield calls
    api_v1._climate_cache.clear()


def test_climate_design_is_cached_per_tenth_degree(client, fake_era5):
    r = client.get("/api/v1/climate-designs", params={"latitude": 45.04, "longitude": 38.98})
    assert r.status_code == 200
    j = r.json()
    # 0.4 % самых холодных часов равномерного ряда −20…+40: −20 + 60·0.004 ≈ −19.76
    assert j["winter_design_c"] == pytest.approx(-19.8, abs=0.1)
    assert j["summer_design_db_c"] == pytest.approx(39.8, abs=0.1)
    assert j["elevation_m"] == 150 and j["source_id"] == "era5_open_meteo"
    # Та же клетка 0.1° — из кэша, без второго похода в сеть
    client.get("/api/v1/climate-designs", params={"latitude": 45.01, "longitude": 39.02})
    assert fake_era5 == [(45.0, 39.0)]


def test_climate_unavailable_is_502(client, monkeypatch):
    def down(*a, **k):
        raise CalcError("climate_unavailable")
    monkeypatch.setattr(api_v1.design_climate, "fetch_hourly", down)
    api_v1._climate_cache.clear()
    r = client.get("/api/v1/climate-designs", params={"latitude": 10, "longitude": 10})
    assert r.status_code == 502 and r.json()["code"] == "climate_unavailable"
    assert r.headers["content-type"].startswith("application/problem+json")
