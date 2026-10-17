"""
Тепловой баланс горелок: одна формула в расчёте Qmin/Qmax и в анализе обогрева
(TODO P1, ревью 2026-10-16: duty cycle считался двумя разными способами —
ρ при T_нар в calc_core и фиксированные 1.2·1005 в building_thermal).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.app.core.building_thermal import THERMAL_CONFIG_PATH, calculate_heat_balance
from backend.app.core.calc_core import CalcInput, compute

UA = 3_000.0          # Вт/°C
HEATER_KW = 2_000.0   # с запасом, чтобы duty не упирался в 1.0


@pytest.fixture
def calibrated_house():
    path = Path(THERMAL_CONFIG_PATH)
    path.write_text(json.dumps({
        "heater": {"heater_type": "electric", "total_power_kw": HEATER_KW},
        "calibration": {"t_initial_c": 20, "t_final_c": 18, "t_outside_c": 0,
                        "time_minutes": 30, "ua_coefficient": UA},
    }), encoding="utf-8")
    yield
    path.unlink(missing_ok=True)


def test_duty_cycle_same_in_calc_and_heat_analysis(calibrated_house):
    r = compute(CalcInput(birds=10_000, age_days=21, outside_t=-10.0, outside_rh=80.0))

    analysis = calculate_heat_balance(
        ua_coefficient=UA, q_min_m3h=r.q_min_m3h, t_inside_target=r.min_temp_c,
        t_outside=-10.0, num_birds=10_000, bird_weight_kg=r.weight_used_g / 1000.0,
        heater_power_kw=HEATER_KW, heater_type="electric",
    )

    assert 0.0 < r.heater_duty_cycle < 1.0
    assert r.heater_duty_cycle == pytest.approx(analysis.duty_cycle, abs=1e-4)
