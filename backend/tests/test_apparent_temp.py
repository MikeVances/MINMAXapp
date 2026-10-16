"""
Ощущаемая температура: уставка зависит от целевой RH в корпусе.

Эталоны — ячейки Ross Broiler Management Handbook 2025, табл. 2.5 (стр. 30),
промежуточные значения посчитаны вручную линейной интерполяцией.
"""
from __future__ import annotations

import pytest

from backend.app.core.apparent_temp import rh_temperature_shift
from backend.app.core.calc_core import CalcInput, compute


@pytest.mark.parametrize(
    "weight_g, rh, expected, why",
    [
        (44,   60, 0.0,  "опорная колонка — сдвига нет"),
        (44,   40, 5.2,  "36.0 − 30.8: сухой воздух, суточный цыплёнок"),
        (590,  50, 2.0,  "26.8 − 24.8"),
        (2296, 70, -1.4, "строка «>1530 г»: 19.3 − 20.7"),
        # середина 1015…1260 г и середина 40…50 %:
        #   строка = ((26.9+25.7)/2, (24.7+23.5)/2, …, (22.7+21.7)/2) = (26.3, 24.1, …, 22.2)
        #   T(45 %) = (26.3 + 24.1)/2 = 25.2  →  25.2 − 22.2 = +3.0
        (1137.5, 45, 3.0, "интерполяция по массе и по RH"),
    ],
)
def test_shift_matches_ross_table_2_5(weight_g, rh, expected, why):
    assert rh_temperature_shift(weight_g, rh) == pytest.approx(expected, abs=1e-9), why


def test_rh_outside_table_is_refused():
    with pytest.raises(ValueError):
        rh_temperature_shift(1000, 80)


def _day35(**kw):
    return compute(CalcInput(birds=10_000, age_days=35, display_unit="per_bird",
                             outside_t=10.0, outside_rh=60.0, **kw))


def test_humid_target_lowers_setpoint_and_raises_qmax():
    """
    День 35 (W = 2.296 кг), профиль 20 °C при 60 %. Цель RH 70 % → уставка 20 − 1.4 = 18.6 °C.
    Меньше ΔT с улицей 10 °C → тем же явным теплом нужно больше воздуха:
      Qmax = 6.90 × 2.296^0.75 × 10 000 × 3600 / (1.2469 × 1006 × 8.6) = 42 950 м³/ч
      (при 60 % было 36 937 — см. test_calc_core_golden)
    """
    r = _day35(target_rh=70.0)

    assert r.min_temp_c == pytest.approx(18.6)
    assert r.rv_percent == 70.0
    assert r.q_max_m3h == pytest.approx(42_950.1, rel=1e-4)


def test_without_target_rh_profile_reference_is_used():
    r = _day35()

    assert r.min_temp_c == pytest.approx(20.0)
    assert r.rv_percent == 60.0


def test_api_rejects_target_rh_outside_table(client):
    payload = dict(house="1", birds=10_000, age_days=21, outside_t=20.0, target_rh=80)

    r = client.post("/calc/minmax", json=payload)

    assert r.status_code == 422
    assert any(err["loc"][-1] == "target_rh" for err in r.json()["detail"])
