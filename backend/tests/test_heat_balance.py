"""
Тепловой баланс горелок: одна формула в расчёте Qmin/Qmax и в анализе обогрева
(TODO P1, ревью 2026-10-16: duty cycle считался двумя разными способами —
ρ при T_нар в calc_core и фиксированные 1.2·1005 в building_thermal).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.app.core.building_thermal import (
    THERMAL_CONFIG_PATH, calculate_heat_balance, heater_co2_dilution_m3h,
)
from backend.app.core.calc_core import CalcInput, compute

UA = 3_000.0          # Вт/°C
HEATER_KW = 2_000.0   # с запасом, чтобы duty не упирался в 1.0


def _write_thermal_config(heater_type: str) -> Path:
    path = Path(THERMAL_CONFIG_PATH)
    path.write_text(json.dumps({
        "heater": {"heater_type": heater_type, "total_power_kw": HEATER_KW},
        "calibration": {"t_initial_c": 20, "t_final_c": 18, "t_outside_c": 0,
                        "time_minutes": 30, "ua_coefficient": UA},
    }), encoding="utf-8")
    return path


@pytest.fixture
def calibrated_house():
    path = _write_thermal_config("electric")
    yield
    path.unlink(missing_ok=True)


@pytest.fixture
def gas_heated_house():
    path = _write_thermal_config("gas_open")
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


def test_open_gas_burners_add_co2_dilution_air_to_qmin(gas_heated_house):
    """
    Газ открытого горения: к Qmin добавляется воздух на разбавление CO₂ горелок
    (heater_co2_dilution_m3h при расчётном duty cycle), электрический обогрев — нет.
    Единственный эталон на путь горелок внутри compute(), а не в отдельной функции.
    """
    args = dict(birds=10_000, age_days=21, outside_t=-10.0, outside_rh=80.0)
    off = compute(CalcInput(**args, heater_on=False))
    on = compute(CalcInput(**args, heater_on=True))

    expected_air = heater_co2_dilution_m3h(HEATER_KW, on.heater_duty_cycle, "gas_open")

    assert expected_air > 0
    assert on.heater_air_m3h == pytest.approx(expected_air, rel=1e-6)
    # Горелки могли ещё и поднять Qmin через пар (влагобаланс) — но не ниже, чем на воздух горения
    assert on.q_min_m3h >= off.q_min_m3h + expected_air - 1e-6


# ─── Загрузка горелок согласована с их собственным воздухом (аудит 2026-10-18) ──

def _heat_need_w(r, outside_t: float, birds: int) -> float:
    """Потребность в тепле при ИТОГОВОМ Qmin результата — по первичным формулам."""
    from backend.app.core.app_config import load_app_config
    from backend.app.core.survival import survival_fraction

    cfg = load_app_config()
    birds_eff = birds * survival_fraction(r.profile_day_resolved, cfg.total_mortality_pct, cfg.cycle_days)
    t_in = r.min_temp_c
    rho_in = 353.05 / (t_in + 273.15)
    dt = t_in - outside_t
    walls = UA * dt
    vent = r.q_min_m3h / 3600.0 * rho_in * 1006.0 * dt
    birds_w = 6.90 * (r.weight_used_g / 1000.0) ** 0.75 * birds_eff
    return walls + vent - birds_w


def test_open_flame_duty_covers_heating_of_its_own_dilution_air(gas_heated_house):
    """
    Определяющее равенство: P · d = UA·ΔT + ρ·Cp·ΔT·Qmin/3600 − тепло птицы,
    где Qmin УЖЕ включает воздух разбавления CO₂ горелок. Раньше d считался по
    Qmin без этого воздуха — равенство нарушалось в разы (каждый кВт пламени
    требует ~58 м³/ч воздуха, при ΔT 35 К его нагрев ≈ 68 % мощности).
    """
    birds = 10_000
    r = compute(CalcInput(birds=birds, age_days=21, outside_t=-10.0, outside_rh=50.0, heater_on=True))

    assert 0.0 < r.heater_duty_cycle < 1.0
    assert r.heater_air_m3h == pytest.approx(heater_co2_dilution_m3h(HEATER_KW, r.heater_duty_cycle, "gas_open"))
    assert HEATER_KW * 1000.0 * r.heater_duty_cycle == pytest.approx(_heat_need_w(r, -10.0, birds), rel=1e-6)
    assert r.heater_insufficient is False


def test_undersized_burners_are_flagged(monkeypatch, tmp_path):
    """50 кВт открытого пламени на 30 000 голов при −20 °C: на 100 % тепла не хватает — флаг, а не «99 %»."""
    from backend.app.core import building_thermal

    path = tmp_path / "thermal.json"
    path.write_text(json.dumps({
        "heater": {"heater_type": "gas_open", "total_power_kw": 50.0},
        "calibration": {"t_initial_c": 20, "t_final_c": 18, "t_outside_c": 0,
                        "time_minutes": 30, "ua_coefficient": UA},
    }), encoding="utf-8")
    monkeypatch.setattr(building_thermal, "THERMAL_CONFIG_PATH", str(path))
    from backend.app.core import calc_core
    monkeypatch.setattr(calc_core, "load_thermal_config", lambda: building_thermal.load_thermal_config(str(path)))

    r = compute(CalcInput(birds=30_000, age_days=7, outside_t=-20.0, outside_rh=50.0, heater_on=True))

    assert r.heater_duty_cycle == 1.0
    assert r.heater_insufficient is True


def test_heater_analysis_matches_calc_for_open_flame(gas_heated_house):
    """
    Анализ горелок (вкладка калибровки) получает Qmin ПТИЦЫ и сам добавляет воздух
    пламени тем же решателем — загрузка совпадает с расчётом Qmin.
    """
    args = dict(birds=10_000, age_days=21, outside_t=-10.0, outside_rh=50.0)
    birds_only = compute(CalcInput(**args, heater_on=False))
    with_heaters = compute(CalcInput(**args, heater_on=True))

    analysis = calculate_heat_balance(
        ua_coefficient=UA, q_min_m3h=birds_only.q_min_m3h,
        t_inside_target=birds_only.min_temp_c, t_outside=-10.0,
        num_birds=round(birds_only.q_min_m3h / birds_only.rates_per_bird_min),
        bird_weight_kg=birds_only.weight_used_g / 1000.0,
        heater_power_kw=HEATER_KW, heater_type="gas_open",
    )

    assert analysis.duty_cycle == pytest.approx(with_heaters.heater_duty_cycle, abs=1e-3)
    assert analysis.dilution_air_m3h == pytest.approx(with_heaters.heater_air_m3h, rel=1e-3)
