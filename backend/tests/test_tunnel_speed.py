"""
Туннельный калькулятор (TODO P1, ревью 2026-10-16): рабочая точка вентиляторов,
эффект влажности в ощущаемой температуре, индекс теплового стресса для бройлеров.
"""
from __future__ import annotations

import pytest

from backend.app.core.evap_cooling_calc import _wet_bulb_stull
from backend.app.core.tunnel_speed_calc import (
    RHO_AIR_KG_M3, TunnelSpeedInput, calculate_tunnel_speed,
)

HOUSE = dict(house_width_m=18, tunnel_height_m=3.0, num_fans=10, fan_capacity_m3h=40_000,
             t_outdoor_db_c=32, rh_outdoor_pct=60, bird_age_days=35,
             num_inlets=2, inlet_width_m=20, inlet_height_m=1.5)


def test_operating_point_lies_on_fan_curve_and_system_curve():
    """
    Рабочая точка — пересечение двух кривых, проверяем обе независимо от решателя:
      вентилятор: q = 40 000 − (40 000 − 36 000)/25 · P   [м³/ч]
      система:    P = ρ/2 · (1/A² + 1/(A_вп·Cd)²) · Q²,  A = 54 м², A_вп = 60 м², Cd = 0.62
    """
    r = calculate_tunnel_speed(TunnelSpeedInput(**HOUSE, fan_capacity_25pa_m3h=36_000))

    q = r.fan_operating_m3h
    Q = 10 * q / 3600.0
    p_system = RHO_AIR_KG_M3 / 2 * (1 / 54 ** 2 + 1 / (60 * 0.62) ** 2) * Q ** 2
    q_on_fan_curve = 40_000 - (40_000 - 36_000) / 25 * p_system

    assert r.velocity_basis == "operating_point"
    assert q == pytest.approx(q_on_fan_curve, abs=1.0)   # округление до 1 м³/ч
    assert q < 40_000


def test_without_second_rating_point_flags_free_air_rating():
    r = calculate_tunnel_speed(TunnelSpeedInput(**HOUSE))

    assert r.velocity_basis == "rated_0pa"
    assert r.fan_operating_m3h == 40_000


def test_humid_still_air_feels_hotter_than_thermometer():
    """
    Таблица при 35 °C / RH 70 % и V = 0 даёт 38.3 °C. Раньше min(t_eff, t_db)
    срезал это до 35 °C — эффект влажности пропадал.
    """
    still = {**HOUSE, "num_fans": 1, "fan_capacity_m3h": 1, "t_outdoor_db_c": 35, "rh_outdoor_pct": 70}

    r = calculate_tunnel_speed(TunnelSpeedInput(**still))

    assert r.effective_temp_c == pytest.approx(38.3, abs=0.05)


def test_thvi_for_broilers_tao_xin_2003():
    """
    THVI = (0.85·T_db + 0.15·T_wb) · V^−0.058; V = 2.06 м/с > 1.2 → берётся 1.2
    (за пределами исследования эффект скорости не экстраполируется).
    """
    r = calculate_tunnel_speed(TunnelSpeedInput(**HOUSE))
    t_wb = _wet_bulb_stull(32, 60)
    expected = (0.85 * 32 + 0.15 * t_wb) * 1.2 ** -0.058

    assert r.thi_value == pytest.approx(expected, abs=0.05)
    assert r.thi_status == "normal"       # < 35 °C


def test_api_rejects_rating_point_not_below_free_air(client):
    payload = {**HOUSE, "fan_capacity_25pa_m3h": 41_000}

    assert client.post("/calc/tools/tunnel_speed", json=payload).status_code == 422


# ─── Охлаждение ветром не растёт с жарой и гаснет у температуры птицы (аудит 2026-10-18) ──

from backend.app.core.tunnel_speed_calc import (  # noqa: E402
    _effective_temperature, _find_tunnel_temp_limit,
)


@pytest.mark.parametrize("rh", [50.0, 70.0])
def test_wind_cooling_does_not_grow_above_85F(rh):
    """
    UGA (Czarick): кривые 85, 90 и 95 °F дают одинаковое охлаждение. Таблица давала
    при 2.5 м/с −9.4 °C при 29.4 °C и −12.8 °C при 35 °C (RH 50 %).
    """
    def cooling(t):
        return _effective_temperature(t, rh, 0.0) - _effective_temperature(t, rh, 2.5)

    assert cooling(35.0) == pytest.approx(cooling(29.4), abs=1e-9)
    assert cooling(32.2) == pytest.approx(cooling(29.4), abs=1e-9)


@pytest.mark.parametrize("v", [0.5, 1.5, 2.5])
def test_wind_gives_no_cooling_at_bird_surface_temperature(v):
    """
    Воздух 95–100 °F практически останавливает теплоотдачу бройлера (Univ. of Kentucky,
    AFS гл. 9). Старая экстраполяция давала при 40 °C и 2.5 м/с охлаждение 13.9 °C.
    """
    for t in (37.8, 40.0, 45.0):
        assert _effective_temperature(t, 50.0, v) == pytest.approx(_effective_temperature(t, 50.0, 0.0), abs=1e-9)


def test_wind_never_warms_birds_in_cool_air():
    """Экстраполяция ниже 21.1 °C давала отрицательное охлаждение — «ветер греет»."""
    for t in (0.0, 10.0, 15.0, 21.1):
        for v in (0.5, 1.0, 2.5):
            assert _effective_temperature(t, 50.0, v) <= _effective_temperature(t, 50.0, 0.0) + 1e-9


def test_tunnel_limit_for_market_birds_is_below_bird_surface_temperature():
    """
    2.5 м/с, RH 50 %, комфорт 24 °C (42 дня): было «тоннель достаточен до 38.6 °C».
    С плато охлаждения 9.4 °C предел 24 + 9.4 = 33.4 °C — выше этого нужны панели.
    """
    limit = _find_tunnel_temp_limit(50.0, 2.5, 24.0)

    assert limit == pytest.approx(33.4, abs=0.15)


def test_birds_heat_air_along_the_house_and_comfort_is_checked_at_the_fans(client):
    """
    Аудит 2026-10-18: проверки сравнивали с целью воздух на ВХОДЕ, а у вентиляторов
    он теплее на тепло птицы. 35 000 голов, день 42 (профиль test-breed: 2.998 кг), 32 °C:
      явное тепло корпуса CIGR 2002 при 32 °C: f_s = (0.61 × 760 − 0.228 × 32²)/1000 = 0.2301
      H   = 10.62 × 2.998^0.75 × 0.2301 × 35 000 = 194 136 Вт
      Q   = 10 × 40 000 / 3600 = 111.11 м³/с,  ρ(32 °C) = 353.05 / 305.15 = 1.1570
      ΔT  = H / (ρ · 1006 · Q) = 1.50 °C
    """
    body = dict(house_width_m=15, tunnel_height_m=2.5, num_fans=10, fan_capacity_m3h=40_000,
                t_outdoor_db_c=32.0, rh_outdoor_pct=50.0, bird_age_days=42)
    plain = client.post("/calc/tools/tunnel_speed", json=body).json()
    r = client.post("/calc/tools/tunnel_speed", json={**body, "num_birds": 35_000}).json()

    f_s = (0.61 * 760 - 0.228 * 32 ** 2) / 1000
    heat_w = 10.62 * 2.998 ** 0.75 * f_s * 35_000
    rise = heat_w / (353.05 / 305.15 * 1006 * (400_000 / 3600))

    assert r["air_temp_rise_c"] == pytest.approx(rise, abs=0.05)
    assert r["t_fan_end_c"] == pytest.approx(32.0 + rise, abs=0.05)
    assert r["effective_temp_c"] == pytest.approx(_effective_temperature(32.0 + rise, 50.0, r["air_velocity_ms"]), abs=0.05)
    assert r["t_outdoor_tunnel_limit_c"] == pytest.approx(plain["t_outdoor_tunnel_limit_c"] - rise, abs=0.1)
    assert r["end_to_end_rise_excessive"] is False


# ── Причина провала туннеля (аудит 2026-10-18) ────────────────────────────────
# tunnel_sufficient = (скорость ≥ цели) И (ощущаемая ≤ цели), а карточка при любом
# провале писала «ощущаемая выше целевой → панели». При нехватке одной скорости
# это неверно: птице не жарко, а лечится всё вентиляторами, не панелями.
# День 35: цель скорости 2.0 м/с, комфорт ≤ 25 °C; сечение 18 × 3 = 54 м².
TUNNEL_35D = dict(house_width_m=18, tunnel_height_m=3.0, fan_capacity_m3h=40_000,
                  rh_outdoor_pct=50, bird_age_days=35, num_inlets=2, inlet_width_m=20, inlet_height_m=1.5)


@pytest.mark.parametrize("fans, t_out, action, speed_ok, heat_ok", [
    (6, 24, "add_fans", False, True),             # 1.23 м/с, ощущаемая 20.6 < 25 — НЕ жарко
    (6, 33, "add_fans_heat", False, False),       # жарко, но при 2.0 м/с — 23.6 ≤ 25
    (6, 36, "add_fans_and_pads", False, False),   # и при 2.0 м/с — 30.0 > 25
    (12, 36, "pads", True, False),                # 2.47 м/с, а всё равно 30.0 > 25
    (12, 30, "ok", True, True),
])
def test_tunnel_verdict_names_what_is_missing(client, fans, t_out, action, speed_ok, heat_ok):
    r = client.post("/calc/tools/tunnel_speed",
                    json={**TUNNEL_35D, "num_fans": fans, "t_outdoor_db_c": t_out}).json()
    assert (r["tunnel_action"], r["speed_sufficient"], r["heat_sufficient"]) == (action, speed_ok, heat_ok)
    assert r["tunnel_sufficient"] is (speed_ok and heat_ok)
    assert r["heat_sufficient"] is (r["effective_temp_c"] <= r["bird_comfort_target_c"])


def test_effective_temperature_at_target_speed_matches_a_house_that_has_it():
    """
    Прогноз «при целевой скорости» обязан совпасть с расчётом корпуса, где эта
    скорость реально есть — вместе с меньшим нагревом вдоль корпуса (больше воздуха).
    """
    birds = dict(num_birds=30_000, bird_weight_kg=2.3)
    slow = calculate_tunnel_speed(TunnelSpeedInput(**TUNNEL_35D, **birds, num_fans=6, t_outdoor_db_c=33))
    # 2.0 м/с × 54 м² = 108 м³/с = 388 800 м³/ч → 6 вентиляторов по 64 800
    at_target = calculate_tunnel_speed(TunnelSpeedInput(
        **{**TUNNEL_35D, "fan_capacity_m3h": 2.0 * 54 * 3600 / 6}, **birds, num_fans=6, t_outdoor_db_c=33))
    assert at_target.air_velocity_ms == pytest.approx(2.0, abs=0.005)
    assert slow.air_temp_rise_c > at_target.air_temp_rise_c
    assert slow.effective_temp_at_target_speed_c == pytest.approx(at_target.effective_temp_c, abs=0.05)
