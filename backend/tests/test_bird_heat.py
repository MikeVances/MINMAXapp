"""
Тепло бройлеров на уровне корпуса (CIGR 2002) — одна модель для Qmax, горелок и влаги.
Аудит 2026-10-18: явное тепло 6.90·W^0.75 (уровень птицы) в тепловом балансе плюс
скрытое по доле корпуса во влажностном давали в сумме больше 100 % полного тепла.
"""
from __future__ import annotations

import pytest

from backend.app.core.bird_heat import house_heat_per_bird, total_heat_factor


@pytest.mark.parametrize("t", [18.0, 20.0, 25.0, 32.0, 35.0])
def test_sensible_plus_latent_equals_temperature_corrected_total(t):
    h = house_heat_per_bird(2.0, t)

    assert h.sensible_w + h.latent_w == pytest.approx(h.total_w, rel=1e-12)
    assert h.total_w == pytest.approx(10.62 * 2.0 ** 0.75 * (1000 + 20 * (20 - t)) / 1000)


def test_old_split_exceeded_total_heat():
    """6.90·W^0.75 + скрытое по доле корпуса при 25 °C = 0.65 + 0.59 = 1.24 полного тепла."""
    q20 = 10.62 * 2.0 ** 0.75
    f_s = (0.61 * 900 - 0.228 * 625) / 1000
    old_sum = 6.90 * 2.0 ** 0.75 + q20 * (1 - f_s)

    h = house_heat_per_bird(2.0, 25.0)

    assert old_sum / q20 == pytest.approx(1.24, abs=0.01)
    assert (h.sensible_w + h.latent_w) / q20 == pytest.approx(0.90)


def test_latent_heat_at_brooding_temperature_no_longer_inflated():
    """32 °C: скрытое = 0.76 − 0.230 = 0.530 полного тепла при 20 °C, а не 1 − 0.230 = 0.770 (×1.45)."""
    q20 = 10.62 * 0.05 ** 0.75
    h = house_heat_per_bird(0.05, 32.0)

    assert h.latent_w / q20 == pytest.approx(0.76 - 0.2301, abs=1e-3)
    assert total_heat_factor(32.0) == pytest.approx(0.76)
