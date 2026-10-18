"""
Туннельный калькулятор (TODO P1, ревью 2026-10-16): рабочая точка вентиляторов,
эффект влажности в ощущаемой температуре, индекс теплового стресса для бройлеров.
"""
from __future__ import annotations

import pytest

from backend.app.core.tunnel_speed_calc import TunnelSpeedInput, calculate_tunnel_speed

# Независимые значения для 32 °C / 60 % (psychrolib 2.5 = ASHRAE Fundamentals 2017)
RHO_32_60 = 1.1445     # плотность влажного воздуха, кг/м³
T_WB_32_60 = 25.555    # мокрый термометр, °C

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
    p_system = RHO_32_60 / 2 * (1 / 54 ** 2 + 1 / (60 * 0.62) ** 2) * Q ** 2
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
    expected = (0.85 * 32 + 0.15 * T_WB_32_60) * 1.2 ** -0.058

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
# День 35: цель скорости 2.0 м/с, предел ощущаемой < 30 °C (Cobb 2021 §9.7); сечение 18 × 3 = 54 м².
TUNNEL_35D = dict(house_width_m=18, tunnel_height_m=3.0, fan_capacity_m3h=40_000,
                  rh_outdoor_pct=50, bird_age_days=35, num_inlets=2, inlet_width_m=20, inlet_height_m=1.5)


@pytest.mark.parametrize("fans, t_out, action, speed_ok, heat_ok", [
    (6, 24, "add_fans", False, True),             # 1.23 м/с, ощущаемая 20.6 < 30 — НЕ жарко
    (6, 36, "add_fans_heat", False, False),       # 31.2 ≥ 30, но при 2.0 м/с — ниже 30
    (6, 38, "add_fans_and_pads", False, False),   # и при 2.0 м/с — 38 (охлаждение ветром гаснет к 37.8)
    (12, 38, "pads", True, False),                # 2.47 м/с, а всё равно 38 ≥ 30
    (12, 30, "ok", True, True),
])
def test_tunnel_verdict_names_what_is_missing(client, fans, t_out, action, speed_ok, heat_ok):
    r = client.post("/calc/tools/tunnel_speed",
                    json={**TUNNEL_35D, "num_fans": fans, "t_outdoor_db_c": t_out}).json()
    assert (r["tunnel_action"], r["speed_sufficient"], r["heat_sufficient"]) == (action, speed_ok, heat_ok)
    assert r["tunnel_sufficient"] is (speed_ok and heat_ok)
    assert r["bird_comfort_target_c"] == 30.0
    assert r["heat_sufficient"] is (r["effective_temp_c"] < r["bird_comfort_target_c"])


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


# ─── Панели во впуске (аудит 2026-10-18: инструмент туннеля их не видел) ─────

def test_pad_in_the_inlet_lowers_the_operating_flow():
    """
    Рабочая точка с панелью лежит на обеих кривых: вентилятор q = q₀ − s·P и
    система P = c·Q² + ΔP_панели(Q/A) по таблице SANHE. Без панели — прежний расчёт.
    """
    from backend.app.core.evap_cooling_calc import SANHE_PADS, _pad_pressure_pa
    from backend.app.core.psychro import moist_air_density

    base = dict(HOUSE, fan_capacity_25pa_m3h=36_000)
    open_inlet = calculate_tunnel_speed(TunnelSpeedInput(**base))
    padded = calculate_tunnel_speed(TunnelSpeedInput(**base, pad_type="7090", pad_thickness_mm=150))

    assert padded.air_velocity_ms < open_inlet.air_velocity_ms
    assert padded.pad_pressure_pa > 0 and open_inlet.pad_pressure_pa == 0

    pad = SANHE_PADS["7090"]
    Q = 10 * padded.fan_operating_m3h / 3600.0
    c = moist_air_density(32, 60) / 2 * (1 / 54 ** 2 + 1 / (60 * 0.62) ** 2)
    p_system = c * Q ** 2 + _pad_pressure_pa(pad["velocities"], pad["pressure_pa"][150], Q / 60)
    assert padded.fan_operating_m3h == pytest.approx(40_000 - 4_000 / 25 * p_system, abs=2.0)


def test_api_rejects_a_pad_thickness_the_type_does_not_have(client):
    payload = {**HOUSE, "pad_type": "5090", "pad_thickness_mm": 200}
    r = client.post("/calc/tools/tunnel_speed", json=payload)
    assert r.status_code == 422


def test_api_passes_the_pad_through(client):
    payload = {**HOUSE, "fan_capacity_25pa_m3h": 36_000, "pad_type": "7060", "pad_thickness_mm": 150}
    r = client.post("/calc/tools/tunnel_speed", json=payload)
    assert r.status_code == 200 and r.json()["pad_pressure_pa"] > 0


def test_profile_target_is_reported_but_does_not_fail_the_tunnel(client):
    """
    Уставка профиля на день (Cobb: «target temperatures for specific ages») — второй
    уровень: выше неё — предупреждение «смотрите на птицу», туннель не «недостаточен».
    Таблица 32→24 °C по возрасту без источника снята (решение 2026-10-19).
    """
    r = client.post("/calc/tools/tunnel_speed",
                    json={**TUNNEL_35D, "num_fans": 12, "t_outdoor_db_c": 30}).json()
    assert r["profile_target_c"] == pytest.approx(20.0, abs=0.5)     # тестовый профиль, день 35
    assert r["above_profile_target"] is True and r["tunnel_sufficient"] is True
