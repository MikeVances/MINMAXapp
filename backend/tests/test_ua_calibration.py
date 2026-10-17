"""
Калибровка UA по тесту остывания (TODO P1, ревью 2026-10-16).
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from backend.app.core.building_thermal import THERMAL_CONFIG_PATH, calculate_ua_coefficient


def test_ua_uses_exponential_cooling_law():
    """
    V = 1000 м³, 20 → 18 °C за 10 мин, снаружи 0 °C.
      ρ(19 °C) = 353.05 / 292.15 = 1.20845 кг/м³;  C = 1000 × 1.20845 × 1006 = 1 215 701 Дж/°C
      UA = C / 600 с × ln(20 / 18) = 1 215 701 / 600 × 0.10536 = 213.48 Вт/°C
    Средняя арифметическая ΔT (как было) давала C × (2/600) / 19 = 213.28 — на большом
    остывании расхождение растёт: 30 → 10 °C при 0 °C снаружи — на 9 % меньше точного
    (средняя ΔT = 20: 20/1800/20 = 5.56e-4 против ln 3/1800 = 6.10e-4).
    """
    assert calculate_ua_coefficient(1000, 20, 18, 0, 10) == pytest.approx(213.48, abs=0.01)


def test_strong_cooling_differs_from_arithmetic_mean():
    v, t0, t1, tout, minutes = 1000, 30, 10, 0, 30
    c = v * 353.05 / (20 + 273.15) * 1006
    exact = c / (minutes * 60) * math.log(30 / 10)

    assert calculate_ua_coefficient(v, t0, t1, tout, minutes) == pytest.approx(exact, rel=1e-12)


def test_warming_house_is_rejected_not_abs():
    """Раньше abs() превращал рост температуры в правдоподобный положительный UA."""
    with pytest.raises(ValueError):
        calculate_ua_coefficient(1000, 18, 20, 0, 10)


def test_api_returns_400_for_warming_and_marks_method(client):
    path = Path(THERMAL_CONFIG_PATH)
    path.write_text(json.dumps({"building": {"length_m": 10, "width_m": 10, "height_m": 10}}),
                    encoding="utf-8")
    try:
        bad = client.post("/thermal/calibrate",
                          json={"t_initial_c": 18, "t_final_c": 20, "t_outside_c": 0, "time_minutes": 10})
        ok = client.post("/thermal/calibrate",
                         json={"t_initial_c": 20, "t_final_c": 18, "t_outside_c": 0, "time_minutes": 10})
    finally:
        path.unlink(missing_ok=True)

    assert bad.status_code == 400
    assert ok.status_code == 200
    assert ok.json()["method"] == "air_only_cooling"
    assert ok.json()["ua_coefficient"] == pytest.approx(213.48, abs=0.01)
