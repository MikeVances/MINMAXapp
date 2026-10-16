"""
Эталонные тесты расчёта Qmin/Qmax (calc_core.compute).

Каждое ожидаемое число посчитано ВРУЧНУЮ по первичным формулам (CIGR 1984,
Magnus, стехиометрия), а не вызовом функций приложения: эталон, который
повторяет проверяемый код, совпадёт с ним и в ошибке.

Здесь — поведение, которое на момент ревью (2026-10-16) считается ВЕРНЫМ.
Известные ошибки живут отдельно в test_known_bugs.py.
"""
from __future__ import annotations

import pytest

from backend.app.core.calc_core import CalcInput, compute

N_BIRDS = 10_000


def _calc(profile, age_days: int, outside_t: float, outside_rh: float, **kw):
    ci = CalcInput(
        birds=N_BIRDS,
        age_days=age_days,
        mode="summer",
        display_unit="per_bird",
        outside_t=outside_t,
        outside_rh=outside_rh,
        **kw,
    )
    return compute(profile, ci)


# ─── Qmin ─────────────────────────────────────────────────────────────────────

def test_qmin_co2_norm_when_air_has_no_drying_capacity(profile):
    """
    День 21, снаружи 25 °C / 60 % — ровно как уставка внутри (25 °C / 60 %).
    ΔW = 0 → влагобаланс не применим → Qmin = норма CO₂ из профиля.
      Qmin = 10 000 гол × 0.946 м³/ч = 9 460 м³/ч
    """
    r = _calc(profile, age_days=21, outside_t=25.0, outside_rh=60.0)

    assert r.q_min_m3h == pytest.approx(9_460.0, rel=1e-9)
    assert r.qmin_basis == "co2"


def test_qmin_moisture_dominates_with_humid_outside_air(profile):
    """
    День 21 (W = 1.012 кг), внутри 25 °C / 60 %, снаружи 20 °C / 75 %.
      W_вн  = 11.889 г/кг,  W_нар = 10.949 г/кг  → ΔW = 0.9406 г/кг   (Magnus, P = 101 325 Па)
      G     = 3.72 × 1.012^0.75 × 3600 / 2430 × 10 000 = 55 656 г/ч   (скрытое тепло → пар)
      ρ_вн  = 353.05 / 298.15 = 1.1841 кг/м³
      Qmin  = G / (ρ × ΔW) = 49 926 м³/ч   > 9 460 по CO₂ → основание «moisture»
    """
    r = _calc(profile, age_days=21, outside_t=20.0, outside_rh=75.0)

    assert r.q_min_m3h == pytest.approx(49_926.2, rel=1e-4)
    assert r.qmin_basis == "moisture"


# ─── Qmax и туннель ───────────────────────────────────────────────────────────

def test_tunnel_active_qmax_equals_installed_capacity(profile):
    """
    День 21 ≥ tunnel_min_day (14) и 25 °C ≥ tunnel_min_temp (18) → туннель включён,
    Qmax = q_max_per_bird × поголовье = 17.0 × 10 000 = 170 000 м³/ч.
    """
    r = _calc(profile, age_days=21, outside_t=25.0, outside_rh=60.0)

    assert r.tunnel_active is True
    assert r.q_max_m3h == pytest.approx(170_000.0, rel=1e-9)


@pytest.mark.parametrize(
    "age_days, outside_t, reason",
    [
        (10, 30.0, "моложе tunnel_min_day = 14"),
        (21, 15.0, "холоднее tunnel_min_temp = 18 °C"),
    ],
)
def test_tunnel_stays_off_outside_its_limits(profile, age_days, outside_t, reason):
    r = _calc(profile, age_days=age_days, outside_t=outside_t, outside_rh=60.0)

    assert r.tunnel_active is False, reason


def test_qmax_never_below_qmin_norm(profile):
    """
    Сильный мороз: тепла птицы на отвод почти не нужно, тепловой баланс даёт
    крошечный Qmax. Он обязан быть не ниже нормы Qmin на голову.
    """
    r = _calc(profile, age_days=35, outside_t=-30.0, outside_rh=80.0)

    assert r.rates_per_bird_max >= r.rates_per_bird_min


# ─── Выживаемость ─────────────────────────────────────────────────────────────

def test_survival_on_day_42_equals_configured_cycle_mortality(profile, monkeypatch):
    """
    Падёж 4 % за цикл 42 дня → к 42-му дню живо ровно 96 % поголовья:
      daily = 1 − 0.96^(1/41),  survival(42) = (1 − daily)^41 = 0.96
    В туннеле Qmax = 17.0 × 10 000 × 0.96 = 163 200 м³/ч.
    """
    from backend.app.core import calc_core
    from backend.app.core.app_config import AppConfig

    monkeypatch.setattr(
        calc_core, "load_app_config", lambda: AppConfig(total_mortality_pct=4.0)
    )
    r = _calc(profile, age_days=42, outside_t=25.0, outside_rh=60.0)

    assert r.q_max_m3h == pytest.approx(163_200.0, rel=1e-9)


# ─── API-обёртка ──────────────────────────────────────────────────────────────

def test_api_minmax_caps_qmax_by_user_capacity(client):
    payload = dict(
        house="1", birds=N_BIRDS, age_days=21, mode_id="summer",
        outside_t=25.0, outside_rh=60.0, user_max_m3h=100_000,
    )
    r = client.post("/calc/minmax", json=payload)

    assert r.status_code == 200
    body = r.json()
    assert body["q_max_nominal_m3h"] == pytest.approx(170_000.0)
    assert body["q_max_m3h"] == pytest.approx(100_000.0)


def test_api_minmax_rejects_numeric_house_id(client):
    """house — строка; число Pydantic v2 не приводит молча (так ломался smoke_test)."""
    payload = dict(house=1, birds=N_BIRDS, age_days=21, mode_id="summer", outside_t=25.0)

    assert client.post("/calc/minmax", json=payload).status_code == 422
