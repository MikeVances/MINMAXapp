"""
Многоточечный тест герметичности (ASHRAE, пункт 4 отчёта 2026-10-18; открытая
методика — степенной закон Q = C·ΔPⁿ, LBNL / ASTM E779).

Одна точка молча предполагает n = 0.5 (Бернулли) и переоценивает утечку при
малых перепадах; две и более точки дают n и утечку при 4 Па (ветер, тяга).
"""
from __future__ import annotations

import pytest

from backend.app.core.leakage_calc import LeakageInput, _fan_correction, calculate_leakage


def _rated_for(q_corrected: float, dp: float) -> float:
    """Паспортный расход (при 25 Па), который после поправки UGA даст q_corrected при dp."""
    return q_corrected / _fan_correction(1.0, dp)


def test_exponent_and_low_pressure_leak_are_recovered():
    C, n = 2_500.0, 0.65
    pts = [(C * dp ** n, dp) for dp in (12.0, 25.0, 50.0)]
    r = calculate_leakage(LeakageInput(
        house_length_m=120, house_width_m=16,
        fan_capacity_m3h=_rated_for(*pts[1]), measured_pressure_pa=25.0,
        extra_points=tuple((_rated_for(q, dp), dp) for q, dp in (pts[0], pts[2]))))
    assert r.flow_exponent_n == pytest.approx(n, abs=1e-3)
    assert r.flow_coefficient == pytest.approx(C, rel=1e-3)
    assert r.leak_at_4pa_m3h == pytest.approx(C * 4 ** n, rel=1e-3)
    assert r.exponent_out_of_range is False


def test_single_point_keeps_the_uga_result_and_reports_no_exponent():
    r = calculate_leakage(LeakageInput(house_length_m=120, house_width_m=16,
                                       fan_capacity_m3h=34_000, measured_pressure_pa=25.0))
    assert r.flow_exponent_n is None and r.leak_at_4pa_m3h is None


def test_points_at_the_same_pressure_are_refused(client):
    body = {"house_length_m": 120, "house_width_m": 16, "fan_capacity_m3h": 34_000, "measured_pressure_pa": 25,
            "extra_points": [{"fan_capacity_m3h": 30_000, "measured_pressure_pa": 26}]}
    r = client.post("/calc/tools/leakage", json=body)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "leakage_points_too_close"


def test_api_returns_the_power_law(client):
    body = {"house_length_m": 120, "house_width_m": 16, "fan_capacity_m3h": 34_000, "measured_pressure_pa": 25,
            "extra_points": [{"fan_capacity_m3h": 68_000, "measured_pressure_pa": 60}]}
    r = client.post("/calc/tools/leakage", json=body).json()
    assert r["flow_exponent_n"] is not None and r["leak_at_4pa_m3h"] > 0 and r["infiltration_kw_per_10k"] > 0
