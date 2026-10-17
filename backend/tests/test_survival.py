"""
Падёж — одна формула для расчёта и сводки (TODO P1, ревью 2026-10-16).

Раньше calc_core брал зашитые 41 день, а summary7 — cycle_days − 1: при цикле
49 дней на 49-й день поголовье в двух частях приложения расходилось.
"""
from __future__ import annotations

import pytest

from backend.app.core.app_config import AppConfig
from backend.app.core.survival import daily_mortality_to_total, survival_fraction


@pytest.mark.parametrize("cycle_days", [35, 42, 49])
def test_survival_reaches_configured_mortality_on_last_day(cycle_days):
    """Падёж 4 % за цикл → на последнем дне живо ровно 96 % при ЛЮБОЙ длине цикла."""
    assert survival_fraction(1, 4.0, cycle_days) == 1.0
    assert survival_fraction(cycle_days, 4.0, cycle_days) == pytest.approx(0.96, rel=1e-12)


def test_legacy_daily_mortality_conversion_uses_cycle_length():
    """0.1 %/сутки за 48 суток (цикл 49): 1 − e^(48·ln 0.999) = 1 − 0.953111 = 4.6889 %."""
    assert daily_mortality_to_total(0.1, 49) == pytest.approx(4.6889, abs=1e-4)


def test_calc_and_summary_agree_on_last_day_of_long_cycle(client, monkeypatch):
    """
    Цикл 49 дней, падёж 4 %: на 49-й день живо 0.96 × 10 000 = 9 600 голов
    и в расчёте /calc/minmax, и в строке сводки /calc/summary7.
    Qmin по CO₂ пропорционален живому поголовью, поэтому сравниваем его.
    """
    from backend.app.core import calc_core
    from backend.app.routers import calc as calc_router

    cfg = AppConfig(total_mortality_pct=4.0, cycle_days=49, default_growth_profile="test-breed")
    monkeypatch.setattr(calc_core, "load_app_config", lambda: cfg)
    monkeypatch.setattr(calc_router, "load_app_config", lambda: cfg)

    common = dict(house="1", birds=10_000, outside_t=25.0, outside_rh=60.0)
    single = client.post("/calc/minmax", json={**common, "age_days": 49}).json()
    row49 = next(r for r in client.post("/calc/summary7", json=common).json()["rows"] if r["day"] == 49)

    assert row49["birds_eff"] == pytest.approx(9_600.0)
    assert single["q_min_m3h"] == pytest.approx(row49["q_min_m3h"], rel=1e-9)
