"""
Эталоны для отдельных физических функций: CIGR, стехиометрия горелок,
психрометрия панелей, поправка вентилятора в тесте герметичности.
"""
from __future__ import annotations

import pytest

from backend.app.core.building_thermal import heater_co2_dilution_m3h
from backend.app.core.evap_cooling_calc import _wet_bulb_stull
from backend.app.core.leakage_calc import _fan_correction
from backend.app.core.ventilation_calc import calc_q_min_per_bird


def test_cigr_qmin_per_bird_for_2kg_broiler():
    """
    CIGR 1984, W = 2.0 кг, запас 1.5:
      H    = 10.62 × 2.0^0.75 = 17.861 Вт
      VCO₂ = 17.861 × 0.153   = 2.7327 л/ч
      Qmin = 2.7327 / 2.6 × 1.5 = 1.5765 м³/ч → округление до 3 знаков = 1.577
    """
    assert calc_q_min_per_bird(2.0, safety_factor=1.5) == pytest.approx(1.577, abs=1e-9)


def test_open_gas_heater_co2_dilution_100kw_full_duty():
    """
    100 кВт при LHV ≈ 10 кВт·ч/м³ → 10 м³ CH₄/ч → 10 000 л CO₂/ч (CH₄ + 2O₂ → CO₂ + 2H₂O).
    Разбавление до ΔCO₂ = 2.6 л/м³ с запасом 1.5: 10 000 / 2.6 × 1.5 = 5 769.2 м³/ч.
    """
    assert heater_co2_dilution_m3h(100.0, 1.0, "gas_open") == pytest.approx(5_769.23, rel=1e-5)


def test_electric_heater_adds_no_co2():
    assert heater_co2_dilution_m3h(100.0, 1.0, "electric") == 0.0


def test_wet_bulb_matches_stull_2011_reference_point():
    """Контрольная точка из статьи Stull (2011): 20 °C, 50 % RH → T_wb ≈ 13.7 °C."""
    assert _wet_bulb_stull(20.0, 50.0) == pytest.approx(13.7, abs=0.05)


def test_fan_correction_is_unity_at_rating_pressure():
    """
    Вентилятор паспортизирован при 0.10" (≈ 25 Па): полином UGA должен давать ≈ 1.
      p = 25 / 249.089 = 0.10037"
      k = −2.57·p² − 0.97·p + 1.124 = 1.00076
    """
    assert _fan_correction(1.0, 25.0) == pytest.approx(1.00076, abs=1e-5)
