"""
Статусы инструментов — машинные коды, текст собирает клиент (ревью 2026-10-16, P2).

Раньше сервер отдавал русские фразы с эмодзи, а клиент выбирал цвет бейджа
по эмодзи внутри строки — при переводе интерфейса на другой язык всё это
оставалось по-русски.
"""
from __future__ import annotations

import re

import pytest

from backend.app.core.building_thermal import calculate_heat_balance

_CODE = re.compile(r"^[a-z_]+$")
_LEVELS = {"ok", "warn", "danger"}

_TUNNEL = dict(house_width_m=18, tunnel_height_m=3.0, num_fans=10, fan_capacity_m3h=40_000,
               t_outdoor_db_c=32, rh_outdoor_pct=60, bird_age_days=35,
               num_inlets=2, inlet_width_m=20, inlet_height_m=1.5)
_EVAP = dict(house_length_m=120, t_outdoor_db_c=35, rh_outdoor_pct=40, total_fan_m3h=500_000,
             pad_length_m=40, pad_height_m=1.8, pad_type="5090", pad_thickness_mm=150)


def test_tunnel_statuses_are_codes(client):
    d = client.post("/calc/tools/tunnel_speed", json=_TUNNEL).json()

    for field in ("thi_status", "inlet_status", "velocity_status", "status_code"):
        assert _CODE.fullmatch(d[field]), (field, d[field])
    assert d["status_level"] in _LEVELS
    assert "status_label" not in d


def test_evap_statuses_are_codes_with_velocity_bounds(client):
    d = client.post("/calc/tools/evap_cooling", json=_EVAP).json()

    assert _CODE.fullmatch(d["velocity_status"])
    assert _CODE.fullmatch(d["status_code"])
    assert d["status_level"] in _LEVELS
    # Границы скорости нужны клиенту для текста «слишком низкая (v < v_min)»
    assert 0 < d["pad_v_min_ms"] < d["pad_v_max_ms"]


@pytest.mark.parametrize(
    "heater_kw, t_outside, expected_code, expected_level",
    [
        (300.0, 25.0, "no_heating_needed", "ok"),   # снаружи теплее уставки
        (10.0,  -20.0, "insufficient", "danger"),   # 10 кВт на 30 000 голов в мороз
    ],
)
def test_heater_status_codes(heater_kw, t_outside, expected_code, expected_level):
    r = calculate_heat_balance(
        ua_coefficient=2000.0, q_min_m3h=20_000, t_inside_target=20.0, t_outside=t_outside,
        num_birds=30_000, bird_weight_kg=1.0, heater_power_kw=heater_kw, heater_type="gas_open",
    )

    assert (r.status_code, r.status_level) == (expected_code, expected_level)
    # Дефицит отдаётся числом, чтобы клиент подставил его в перевод
    assert (r.heater_deficit_kw > 0) == (expected_code == "insufficient")
