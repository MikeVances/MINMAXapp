"""
Валидация входа инструментов (/calc/tools/*): недопустимые данные → 422, а не 500.
"""
from __future__ import annotations

import pytest

_EVAP = dict(
    house_length_m=120, t_outdoor_db_c=35, rh_outdoor_pct=40, total_fan_m3h=500_000,
    pad_length_m=40, pad_height_m=1.8,
)


@pytest.mark.parametrize(
    "pad_type, thickness",
    [("5090", 200), ("7090", 125), ("7060", 50)],
)
def test_evap_unknown_pad_thickness_is_422(client, pad_type, thickness):
    """
    До исправления (ревью 2026-10-16) таблица SANHE давала KeyError → 500.
    У 5090 нет 200 мм, у 7090 нет 125 мм, у 7060 нет 50 мм.
    """
    r = client.post("/calc/tools/evap_cooling",
                    json={**_EVAP, "pad_type": pad_type, "pad_thickness_mm": thickness})

    assert r.status_code == 422
    assert "pad_thickness_mm" in r.text


def test_evap_valid_pad_still_calculates(client):
    """Валидатор не должен отсекать существующие пары."""
    r = client.post("/calc/tools/evap_cooling",
                    json={**_EVAP, "pad_type": "5090", "pad_thickness_mm": 150})

    assert r.status_code == 200


@pytest.mark.parametrize("thickness, v_design", [(100, 1.14), (150, 1.78)])
def test_recommended_pad_area_uses_design_velocity_of_thickness(client, thickness, v_design):
    """
    UGA (Czarick): 225 fpm ≈ 1.14 м/с для 100 мм, 350 fpm ≈ 1.78 м/с для 150 мм.
    Раньше одна скорость 1.25 м/с: для 150 мм площадь была в 1.4 раза больше нужной
    (аудит 2026-10-18).
    """
    body = client.post("/calc/tools/evap_cooling",
                       json={**_EVAP, "pad_type": "7090", "pad_thickness_mm": thickness}).json()

    assert body["recommended_pad_area_m2"] == pytest.approx(
        _EVAP["total_fan_m3h"] / 3600.0 / v_design, abs=0.01)


def test_pad_cooling_sufficiency_is_judged_at_the_fan_end(client):
    """
    Аудит 2026-10-18: охлаждённый воздух по пути к вентиляторам нагревается теплом
    птицы, а достаточность сравнивалась с T сразу за панелью. 30 000 голов, день 42
    (test-breed: 2.998 кг), Q = 500 000 м³/ч: ΔT = H_явн(T_панели) / (ρ·Cp·Q).
    """
    base = {**_EVAP, "pad_type": "7090", "pad_thickness_mm": 150, "t_inside_target_c": 28}
    plain = client.post("/calc/tools/evap_cooling", json=base).json()
    r = client.post("/calc/tools/evap_cooling", json={**base, "num_birds": 30_000, "bird_age_days": 42}).json()

    t_pad = r["t_pad_out_c"]
    f_s = (0.61 * (1000 + 20 * (20 - t_pad)) - 0.228 * t_pad ** 2) / 1000
    heat_w = 10.62 * 2.998 ** 0.75 * f_s * 30_000
    rise = heat_w / (353.05 / (t_pad + 273.15) * 1006 * (500_000 / 3600))

    assert r["air_temp_rise_c"] == pytest.approx(rise, abs=0.1)
    assert r["temp_margin_c"] == pytest.approx(plain["temp_margin_c"] - rise, abs=0.1)
    assert plain["air_temp_rise_c"] == 0.0                      # без поголовья — как раньше
