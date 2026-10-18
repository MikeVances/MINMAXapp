"""
Психрометрия (core/psychro.py) против независимой реализации ASHRAE.

Эталоны посчитаны psychrolib 2.5 (реализация уравнений ASHRAE Handbook
Fundamentals 2017, Meyer & Thevenard) при 101 325 Па, 2026-10-19; сама
библиотека в зависимости проекта не входит — значения вписаны сюда.
Точка росы — выше нуля: ниже psychrolib берёт насыщение надо льдом, а RH
у нас (как у метеостанций) — над водой.

Почему это важно: формула Стулла, которую заменил модуль, в сухую жару
ошибалась до +1 °C по мокрому термометру, а расход воды на панели с ней и с
ρ = 1.184 выходил на 16 % больше карты UGA.
"""
from __future__ import annotations

import pytest

from backend.app.core import psychro as ps
from backend.app.core.evap_cooling_calc import _water_flow_lpm

# (T °C, RH %) → (T_wb °C, ρ кг/м³, T_dp °C)
ASHRAE = {
    (32, 60): (25.555, 1.1445, 23.26),
    (20, 50): (13.783, 1.1989, 9.27),
    (35, 30): (21.524, 1.1383, 14.84),
    (40, 20): (22.032, 1.1210, 12.78),
    (45, 10): (21.175, 1.1056, 6.37),
    (25, 80): (22.380, 1.1728, 21.31),
    (15, 50): (9.672, 1.2211, 4.67),
    (5, 80): (3.588, 1.2658, 1.84),
}


@pytest.mark.parametrize("state", ASHRAE)
def test_wet_bulb_density_dew_point_match_ashrae(state):
    t, rh = state
    twb, rho, tdp = ASHRAE[state]
    assert ps.wet_bulb_c(t, rh) == pytest.approx(twb, abs=0.05)
    assert ps.moist_air_density(t, rh) == pytest.approx(rho, rel=1e-3)
    assert ps.dew_point_c(t, rh) == pytest.approx(tdp, abs=0.1)


def test_hot_dry_air_where_stull_was_off_by_a_degree():
    """45 °C / 10 %: Стулл давал 22.0 °C (+0.9), ASHRAE — 21.18."""
    assert ps.wet_bulb_c(45, 10) == pytest.approx(21.175, abs=0.05)


def test_water_use_matches_the_uga_chart():
    """
    Карта расхода воды UGA (Czarick, «Evaporative cooling pad water usage»):
    90 °F, 60 % RH, 100 000 cfm, бумажная панель 6" → ≈ 1.75 gpm. КПД 0.75 —
    типичный для панели 6" (University of Arkansas FSA-1068).
    """
    t = (90 - 32) / 1.8
    q_m3h = 100_000 * 1.69901
    lpm = _water_flow_lpm(q_m3h, t, 60, ps.wet_bulb_c(t, 60), 0.75)
    assert lpm / 3.78541 == pytest.approx(1.75, rel=0.03)
