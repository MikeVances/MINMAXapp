"""
Высота фермы над уровнем моря (ASHRAE, пункт 2 отчёта 2026-10-18; источник
свободный — стандартная атмосфера, ASHRAE Fundamentals 2017 гл. 1 ур. 3 = ICAO).

На 1000 м воздух на 11 % реже: при давлении 101.3 кПа массовые балансы
(влага, тепло, UA калибровки) переводились в объём с ошибкой на столько же.
Эталоны — psychrolib 2.5 (GetStandardAtmPressure и др.), 2026-10-19.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from backend.app.core import psychro as ps

CFG_PATH = Path(os.environ["APP_CONFIG_JSON"])


@pytest.mark.parametrize("z, p", [(0, 101_325.0), (500, 95_460.8), (1000, 89_874.5), (2000, 79_495.1)])
def test_standard_atmosphere(z, p):
    assert ps.pressure_at_altitude_pa(z) == pytest.approx(p, abs=1.0)


def test_psychrometrics_at_altitude_match_ashrae():
    p = ps.pressure_at_altitude_pa(1000)
    assert ps.wet_bulb_c(35, 30, p) == pytest.approx(21.047, abs=0.05)
    assert ps.moist_air_density(35, 30, p) == pytest.approx(1.0089, rel=1e-3)


@pytest.fixture
def restore_config():
    before = CFG_PATH.read_bytes()
    yield
    CFG_PATH.write_bytes(before)


def test_farm_altitude_reaches_the_calculation(client, restore_config):
    """
    Тепловой Qmax = H / (ρ·Cp·ΔT): на 1000 м ρ меньше в p/p₀ = 0.887 — объём больше
    ровно в p₀/p = 1.127. Влажностный Qmin = G / (ρ·ΔW) от высоты почти не зависит:
    ρ падает как p, а ΔW растёт как 1/p (масса пара в м³ задаётся его парциальным
    давлением) — это физика, а не пропуск поправки.
    """
    calc = {"house": "1", "birds": 30000, "age_days": 28, "outside_t": 10, "outside_rh": 60}
    sea = client.post("/calc/minmax", json=calc).json()
    cfg = client.get("/settings/app-config").json()
    cfg["altitude_m"] = 1000
    assert client.put("/settings/app-config", json=cfg).status_code == 200
    high = client.post("/calc/minmax", json=calc).json()

    p_ratio = 101_325.0 / ps.pressure_at_altitude_pa(1000)
    assert high["q_max_m3h"] / sea["q_max_m3h"] == pytest.approx(p_ratio, rel=5e-3)
    assert high["q_min_m3h"] / sea["q_min_m3h"] == pytest.approx(1.0, abs=0.02)


def test_altitude_out_of_range_is_rejected(client, restore_config):
    cfg = client.get("/settings/app-config").json()
    cfg["altitude_m"] = 9000
    assert client.put("/settings/app-config", json=cfg).status_code == 422
