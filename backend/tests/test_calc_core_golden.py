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


def _calc(age_days: int, outside_t: float, outside_rh: float, **kw):
    ci = CalcInput(
        birds=N_BIRDS,
        age_days=age_days,
        outside_t=outside_t,
        outside_rh=outside_rh,
        **kw,
    )
    return compute(ci)


# ─── Qmin ─────────────────────────────────────────────────────────────────────

def test_qmin_co2_norm_when_air_has_no_drying_capacity():
    """
    День 21, снаружи 25 °C / 60 % — ровно как уставка внутри (25 °C / 60 %).
    ΔW = 0 → влагобаланс не применим → Qmin = норма CO₂ из живой массы (CIGR 1984):
      H    = 10.62 × 1.012^0.75 = 10.715 Вт;  VCO₂ = 10.715 × 0.153 = 1.6395 л/ч
      q    = 1.6395 / 2.6 × 1.5 (запас) = 0.9458 → 0.946 м³/ч·гол
      Qmin = 10 000 гол × 0.946 м³/ч = 9 460 м³/ч
    """
    r = _calc(age_days=21, outside_t=25.0, outside_rh=60.0)

    assert r.q_min_m3h == pytest.approx(9_460.0, rel=1e-9)
    assert r.qmin_basis == "co2"


def test_qmin_moisture_dominates_with_humid_outside_air():
    """
    День 21 (W = 1.012 кг), внутри 25 °C / 60 %, снаружи 20 °C / 75 %.
      W_вн  = 11.889 г/кг,  W_нар = 10.949 г/кг  → ΔW = 0.9406 г/кг   (Magnus, P = 101 325 Па)
      Явная доля на уровне корпуса (CIGR 2002, с подстилкой) при 25 °C:
        f_s   = [0.61 × (1000 + 20 × (20 − 25)) − 0.228 × 25²] / 1000 = 0.4065
      Скрытое = 10.62 × 1.012^0.75 × (1 − 0.4065) = 6.3596 Вт/гол
      G     = 6.3596 × 3600 / 2430 × 10 000 = 94 216 г/ч   (скрытое тепло → пар)
      ρ_вн  = 353.05 / 298.15 = 1.1841 кг/м³
      Qmin  = G / (ρ × ΔW) = 84 592 м³/ч   > 9 460 по CO₂ → основание «moisture»
    До учёта подстилки (ревью 2026-10-16) — только дыхание 3.72·W^0.75: 49 926 м³/ч.
    """
    r = _calc(age_days=21, outside_t=20.0, outside_rh=75.0)

    assert r.q_min_m3h == pytest.approx(84_592.3, rel=1e-4)
    assert r.qmin_basis == "moisture"


def test_humid_outside_air_flags_uncontrollable_humidity():
    """
    День 21, внутри 25 °C / 60 % (W = 11.89 г/кг), снаружи 25 °C / 80 % (W ≈ 15.9 г/кг):
    наружный воздух ВЛАЖНЕЕ целевого, вентиляцией RH не удержать. Qmin показан
    по CO₂, но это должно быть видно флагом, а не тихой подменой (ревью 2026-10-16).
    """
    r = _calc(age_days=21, outside_t=25.0, outside_rh=80.0)

    assert r.humidity_uncontrollable is True
    assert r.qmin_basis == "co2"


def test_house_sensible_fraction_matches_cigr_2002_figure():
    """CIGR 2002 (ур. 13 у Aarnink): 0.54 при 19 °C и 0.20 при 33 °C — как на рис. 5 статьи."""
    from backend.app.core.calc_core import house_sensible_fraction_cigr2002 as fs

    assert fs(19.0) == pytest.approx((0.61 * 1020 - 0.228 * 361) / 1000)   # 0.5399
    assert fs(33.0) == pytest.approx((0.61 * 740 - 0.228 * 1089) / 1000)   # 0.2031


def test_dry_outside_air_does_not_flag_humidity():
    r = _calc(age_days=21, outside_t=20.0, outside_rh=75.0)

    assert r.humidity_uncontrollable is False


# ─── Qmax и туннель ───────────────────────────────────────────────────────────

# Корпус 12 × 3 м в сечении: туннель 2.5 м/с × 36 м² × 3600 = 324 000 м³/ч
HOUSE = dict(house_width_m=12.0, house_height_m=3.0)
TUNNEL_M3H = 324_000.0


def test_tunnel_active_qmax_equals_house_tunnel_requirement():
    """
    День 21 ≥ tunnel_min_day (14) и 25 °C ≥ tunnel_min_temp (18) → туннель включён,
    Qmax = v_tunnel × ширина × средняя высота × 3600 = 2.5 × 12 × 3 × 3600 = 324 000 м³/ч.
    """
    r = _calc(age_days=21, outside_t=25.0, outside_rh=60.0, **HOUSE)

    assert r.tunnel_active is True
    assert r.q_max_m3h == pytest.approx(TUNNEL_M3H, rel=1e-9)
    assert r.house_geometry_missing is False


def test_tunnel_requirement_does_not_depend_on_bird_count():
    """
    Туннельный расход — свойство корпуса. До исправления (ревью 2026-10-16) мощность
    хранилась на голову и умножалась на введённое поголовье: 30k → 120 753, 15k → 60 376.
    """
    full = _calc(age_days=35, outside_t=30.0, outside_rh=60.0, **HOUSE)
    half = compute(CalcInput(
        birds=N_BIRDS // 2, age_days=35,
        outside_t=30.0, outside_rh=60.0, **HOUSE,
    ))

    assert full.tunnel_active and half.tunnel_active
    assert half.q_max_m3h == pytest.approx(full.q_max_m3h, rel=1e-9)


def test_tunnel_without_house_geometry_is_flagged_not_guessed():
    """Нет размеров — туннельный Qmax не из чего считать: флаг и Qmax = Qmin."""
    r = _calc(age_days=21, outside_t=25.0, outside_rh=60.0)

    assert r.tunnel_active is True
    assert r.house_geometry_missing is True
    assert r.q_max_m3h == pytest.approx(r.q_min_m3h, rel=1e-9)


def test_young_birds_qmax_capped_by_transitional_ceiling():
    """
    День 10 < tunnel_min_day: туннель запрещён, снаружи 30 °C > внутри — тепловой
    баланс вырождается. Потолок переходного режима = 4 × Qmin (Aviagen: 3–5×).
      W(10) = 50 + (1012 − 50) × 9/20 = 482.9 г   (линейная интерполяция 1 → 21)
      q     = 10.62 × 0.4829^0.75 × 0.153 / 2.6 × 1.5 = 0.5430 → 0.543 м³/ч·гол
      Qmax  = 4 × 0.543 × 10 000 = 21 720 м³/ч
    """
    r = _calc(age_days=10, outside_t=30.0, outside_rh=60.0, **HOUSE)

    assert r.tunnel_active is False
    assert r.q_max_m3h == pytest.approx(21_720.0, rel=1e-9)


@pytest.mark.parametrize(
    "age_days, outside_t, reason",
    [
        (10, 30.0, "моложе tunnel_min_day = 14"),
        (21, 15.0, "холоднее tunnel_min_temp = 18 °C"),
    ],
)
def test_tunnel_stays_off_outside_its_limits(age_days, outside_t, reason):
    r = _calc(age_days=age_days, outside_t=outside_t, outside_rh=60.0)

    assert r.tunnel_active is False, reason


def test_qmax_heat_balance_uses_sensible_heat_only():
    """
    День 35 (W = 2.296 кг), внутри 20 °C, снаружи 10 °C (туннель выключен), UA = 0.
    Воздух уносит только ЯВНОЕ тепло (ρ·Cp·ΔT), скрытое уходит с паром:
      H_явн = 6.90 × 2.296^0.75 × 10 000 = 128 690 Вт
      ρ     = 353.05 / 283.15 = 1.2469 кг/м³
      Qmax  = 128 690 × 3600 / (1.2469 × 1006 × 10) = 36 937 м³/ч  (3.694 м³/ч·гол)
    До исправления (ревью 2026-10-16) код давал 56 851 м³/ч — с полным теплом 10.62.
    """
    r = _calc(age_days=35, outside_t=10.0, outside_rh=60.0)

    assert r.q_max_m3h == pytest.approx(36_937.1, rel=1e-3)


def test_qmax_never_below_qmin_norm():
    """
    Сильный мороз: тепла птицы на отвод почти не нужно, тепловой баланс даёт
    крошечный Qmax. Он обязан быть не ниже нормы Qmin на голову.
    """
    r = _calc(age_days=35, outside_t=-30.0, outside_rh=80.0)

    assert r.rates_per_bird_max >= r.rates_per_bird_min


# ─── Выживаемость ─────────────────────────────────────────────────────────────

def test_survival_on_day_42_equals_configured_cycle_mortality(monkeypatch):
    """
    Падёж 4 % за цикл 42 дня → к 42-му дню живо ровно 96 % поголовья:
      daily = 1 − 0.96^(1/41),  survival(42) = (1 − daily)^41 = 0.96
    Qmin по CO₂ (W = 2.998 кг): 10.62 × 2.998^0.75 × 0.153 / 2.6 × 1.5 = 2.1358 → 2.136 м³/ч·гол
      Qmin = 2.136 × 10 000 × 0.96 = 20 505.6 м³/ч
    (снаружи 25 °C / 60 % влажнее уставки 19 °C / 60 % → влагобаланс не применим)
    """
    from backend.app.core import calc_core
    from backend.app.core.app_config import AppConfig

    monkeypatch.setattr(
        calc_core, "load_app_config", lambda: AppConfig(total_mortality_pct=4.0, default_growth_profile="test-breed")
    )
    r = _calc(age_days=42, outside_t=25.0, outside_rh=60.0)

    assert r.q_min_m3h == pytest.approx(20_505.6, rel=1e-9)
    assert r.qmin_basis == "co2"


# ─── API-обёртка ──────────────────────────────────────────────────────────────

def test_api_minmax_caps_qmax_by_user_capacity(client):
    payload = dict(
        house="1", birds=N_BIRDS, age_days=21,
        outside_t=25.0, outside_rh=60.0, user_max_m3h=100_000, **HOUSE,
    )
    r = client.post("/calc/minmax", json=payload)

    assert r.status_code == 200
    body = r.json()
    assert body["q_max_nominal_m3h"] == pytest.approx(TUNNEL_M3H)
    assert body["tunnel_requirement_m3h"] == pytest.approx(TUNNEL_M3H)
    assert body["q_max_m3h"] == pytest.approx(100_000.0)
    # Мощности хватает: Qmin 9 460 < 100 000
    assert body["capacity_insufficient"] is False


# Qmin по CO₂ = 9 460 м³/ч (день 21), установлено только 5 000 м³/ч
_UNDERSIZED = dict(
    house="1", birds=N_BIRDS,
    outside_t=25.0, outside_rh=60.0, user_max_m3h=5_000,
)


def test_api_minmax_does_not_cut_qmin_to_capacity(client):
    """
    Минимум — биологическое требование: его нельзя «подогнать» под железо.
    До исправления (ревью 2026-10-16) API отдавал q_min = 5 000 — нехватка
    вентиляторов маскировалась заниженной нормой.
    """
    body = client.post("/calc/minmax", json={**_UNDERSIZED, "age_days": 21}).json()

    assert body["q_min_m3h"] == pytest.approx(9_460.0)
    assert body["q_max_m3h"] == pytest.approx(5_000.0)
    assert body["capacity_insufficient"] is True


def test_api_summary7_flags_rows_where_qmin_exceeds_capacity(client):
    body = client.post("/calc/summary7", json=_UNDERSIZED).json()
    day21 = next(row for row in body["rows"] if row["day"] == 21)

    assert day21["q_min_m3h"] == pytest.approx(9_460.0)
    assert day21["q_min_pct"] == pytest.approx(189.2)   # 9 460 / 5 000 — больше 100 %
    assert day21["capacity_insufficient"] is True


def test_api_minmax_rejects_numeric_house_id(client):
    """house — строка; число Pydantic v2 не приводит молча (так ломался smoke_test)."""
    payload = dict(house=1, birds=N_BIRDS, age_days=21, outside_t=25.0)

    assert client.post("/calc/minmax", json=payload).status_code == 422
