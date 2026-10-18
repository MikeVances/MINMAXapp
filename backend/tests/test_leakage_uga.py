"""
Герметичность — по методике UGA, сверено с первоисточниками 2026-10-19.

Формула: калькулятор UGA poultry_house_air_leakage_calculator_2018.xlsx (лист
«House Leakage calculator»), переписан построчно ниже с его же константами
(1 cfm = 1.7 м³/ч, 1" = 254 Па, 1 ft = 0.305 м, ρ = 1.184, Cd = 1). Наш расчёт
использует точные переводы единиц — расхождение должно быть ~1 %, не больше.

Пороги классов: «Poultry House Leakage Estimating Spreadsheet 2014» (0.48, 0.65)
и «Poultry411 Tightness Calculator» (1.0; примеры 0.45 excellent, 0.78 marginal).
"""
from __future__ import annotations

import math
import re
from pathlib import Path

import pytest

from backend.app.core.leakage_calc import LeakageInput, calculate_leakage

FT = 0.3048
IN_PA = 249.089
CFM_M3H = 1.69901


def _uga_xlsx(length_ft, width_ft, fan_cfm_at_010, sp_in):
    """Ячейки xlsx: C18 (поправка), I2, K2, L2, M2, N2 — как в файле."""
    c18 = fan_cfm_at_010 * (-2.57 * sp_in**2 - 0.97 * sp_in + 1.124)
    i2 = c18 * 1.7 / 60 / 60                 # м³/с
    k2 = sp_in * 254                         # Па
    l2 = i2 * (1.184 / (2 * k2)) ** 0.5      # ELA, м²
    m2 = l2 / (0.305 * 0.305)                # ft²
    return m2, m2 / (length_ft * width_ft / 1000)


def _ours(length_ft, width_ft, fan_cfm, sp_in):
    return calculate_leakage(LeakageInput(
        house_length_m=length_ft * FT, house_width_m=width_ft * FT,
        fan_capacity_m3h=fan_cfm * CFM_M3H, measured_pressure_pa=sp_in * IN_PA))


@pytest.mark.parametrize("case", [(500, 40, 20000, 0.25), (500, 50, 25000, 0.10), (600, 66, 40000, 0.15)])
def test_relative_leakage_matches_the_uga_spreadsheet(case):
    _, rel_uga = _uga_xlsx(*case)
    assert _ours(*case).relative_leakage == pytest.approx(rel_uga, rel=0.02)


def test_poultry411_worked_example_19_4_ft2():
    """50' × 500', один вентилятор 25 000 cfm @ 0.10", 0.10" → «approximately 19.4 ft²»."""
    r = _ours(500, 50, 25000, 0.10)
    assert r.ela_m2 / FT**2 == pytest.approx(19.4, rel=0.02)


@pytest.mark.parametrize("rel,cls", [(0.35, "tight"), (0.45, "tight"), (0.6, "moderate"),
                                     (0.78, "leaky"), (0.99, "leaky"), (1.1, "very_leaky")])
def test_classes_follow_uga_thresholds(rel, cls):
    """0.45 — excellent, 0.78 — marginal (Poultry411); 0.35 раньше было «умеренно»."""
    from backend.app.core.leakage_calc import _classify
    assert _classify(rel) == cls


def test_frontend_takes_the_class_from_the_server():
    js = (Path(__file__).resolve().parents[1] / "app" / "static" / "calculators.js").read_text(encoding="utf-8")
    body = js[js.index("function renderLeakage"):]
    body = body[:body.index("\n}\n")]
    assert not re.search(r"relative_leakage\s*<\s*[\d.]+", body), "копия порогов на фронтенде"
