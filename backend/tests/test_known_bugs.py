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


@pytest.mark.xfail(reason="TODO P1: KeyError → 500 на недопустимой паре тип пэда / толщина")
def test_evap_cooling_rejects_unknown_pad_thickness_with_422(client):
    """У SANHE 5090 нет толщины 200 мм — это ошибка ввода (422), а не падение сервера (500)."""
    payload = dict(
        house_length_m=120, t_outdoor_db_c=35, rh_outdoor_pct=40, total_fan_m3h=500_000,
        pad_type="5090", pad_thickness_mm=200, pad_length_m=40, pad_height_m=1.8,
    )
    assert client.post("/calc/tools/evap_cooling", json=payload).status_code == 422
