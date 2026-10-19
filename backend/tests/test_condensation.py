"""
Риск конденсата на ограждениях (ASHRAE, пункт 3 отчёта 2026-10-18; свободная
теплопередача через стенку, R_si = 0.13 м²·К/Вт — ASHRAE Fundamentals гл. 26).

  T_si = T_in − U·R_si·(T_in − T_out),  U = UA / площадь оболочки.
Ниже точки росы внутреннего воздуха — конденсат на стенах и кровле.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.app.core.building_thermal import (
    THERMAL_CONFIG_PATH, BuildingDimensions, envelope_area_m2, surface_condensation,
)
from backend.app.core.calc_core import CalcInput, compute

DIMS = {"length_m": 100, "width_m": 16, "height_m": 3.25}
B = BuildingDimensions(**DIMS)


def test_surface_temperature_by_hand():
    """U = 2 Вт/(м²·К): T_si = 30 − 2·0.13·(30 − (−10)) = 19.6 °C; роса при 30 °C / 60 % — 21.4 °C."""
    ua = 2.0 * envelope_area_m2(B)
    t_si, t_dew, risk = surface_condensation(ua, B, 30.0, 60.0, -10.0)
    assert t_si == pytest.approx(19.6, abs=0.01)
    assert t_dew == pytest.approx(21.4, abs=0.1)
    assert risk is True


def test_insulated_house_has_no_risk():
    """U = 0.4 (сэндвич-панели): поверхность 27.9 °C — выше росы."""
    t_si, t_dew, risk = surface_condensation(0.4 * envelope_area_m2(B), B, 30.0, 60.0, -10.0)
    assert risk is False and t_si > t_dew


@pytest.fixture
def calibrated(request):
    path = Path(THERMAL_CONFIG_PATH)
    u = request.param
    pts = [[0, 28], [600, 27], [1200, 26], [1800, 25], [2400, 24]]
    path.write_text(json.dumps({"houses": {"1": {
        "building": DIMS,
        "calibration": {"t_initial_c": 28, "t_final_c": 24, "t_outside_c": 5, "time_minutes": 40,
                        "ua_coefficient": u * envelope_area_m2(B), "method": "cooling_curve", "points": pts}}}}))
    yield
    path.unlink(missing_ok=True)


@pytest.mark.parametrize("calibrated", [3.0], indirect=True)
def test_calculation_flags_condensation_for_its_house(calibrated):
    r = compute(CalcInput(birds=20_000, age_days=7, outside_t=-15.0, outside_rh=80.0, house_id="1"))
    assert r.condensation_risk is True and r.surface_temp_c < r.dew_point_inside_c


@pytest.mark.parametrize("calibrated", [0.3], indirect=True)
def test_well_insulated_house_is_not_flagged(calibrated):
    r = compute(CalcInput(birds=20_000, age_days=7, outside_t=-15.0, outside_rh=80.0, house_id="1"))
    assert r.condensation_risk is False and r.surface_temp_c is not None


def test_without_calibration_nothing_is_claimed():
    r = compute(CalcInput(birds=20_000, age_days=7, outside_t=-15.0, outside_rh=80.0, house_id="nobody"))
    assert r.condensation_risk is False and r.surface_temp_c is None
