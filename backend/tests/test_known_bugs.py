"""
Известные ошибки из ревью 2026-10-16 (TODO.md, раздел P0/P1).

Каждый тест описывает ПРАВИЛЬНОЕ поведение и помечен xfail(strict=True):
  - сейчас он падает → «ожидаемо», CI зелёный;
  - после исправления он пройдёт → strict превращает это в ПАДЕНИЕ с XPASS,
    и маркер нужно снять. Так тест служит проверкой «от обратного»: он
    доказуемо падал на старом коде и доказуемо проходит на новом.
"""
from __future__ import annotations

import pytest

from backend.app.core.calc_core import CalcInput, compute

def _calc(profile, birds: int, age_days: int, outside_t: float, outside_rh: float = 60.0):
    ci = CalcInput(
        birds=birds, age_days=age_days, mode="summer", display_unit="per_bird",
        outside_t=outside_t, outside_rh=outside_rh,
    )
    return compute(profile, ci)


@pytest.mark.xfail(reason="TODO P0: мощность туннеля масштабируется от введённого поголовья")
def test_tunnel_capacity_does_not_depend_on_entered_bird_count(profile):
    """
    В туннельном режиме Qmax — это установленные вентиляторы корпуса.
    Если ввести вдвое меньше птицы, вентиляторов меньше не станет.
    """
    full = _calc(profile, birds=10_000, age_days=35, outside_t=30.0)
    half = _calc(profile, birds=5_000, age_days=35, outside_t=30.0)

    assert full.tunnel_active and half.tunnel_active
    assert half.q_max_m3h == pytest.approx(full.q_max_m3h, rel=1e-9)


@pytest.mark.xfail(reason="TODO P1: KeyError → 500 на недопустимой паре тип пэда / толщина")
def test_evap_cooling_rejects_unknown_pad_thickness_with_422(client):
    """У SANHE 5090 нет толщины 200 мм — это ошибка ввода (422), а не падение сервера (500)."""
    payload = dict(
        house_length_m=120, t_outdoor_db_c=35, rh_outdoor_pct=40, total_fan_m3h=500_000,
        pad_type="5090", pad_thickness_mm=200, pad_length_m=40, pad_height_m=1.8,
    )
    assert client.post("/calc/tools/evap_cooling", json=payload).status_code == 422
