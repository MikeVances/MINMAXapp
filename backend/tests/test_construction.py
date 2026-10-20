"""
Справочник материалов и UA по слоям (API v1, этап 2).

Значения λ и R_si/R_se — BRE BR 443 (2019) §3 и §4.3 (по BS EN ISO 10456 и 6946);
ядро PIR — декларация Marcegaglia 100P (EN 14509). Ожидаемые числа ниже посчитаны
руками по формуле U = 1 / (R_si + Σ d/λ + R_se), а не взяты из модуля.
"""
from __future__ import annotations

import math

import pytest

from backend.app.core.building_thermal import BuildingDimensions, envelope_area_m2
from backend.app.core.construction import (
    MATERIALS, HouseGeometry, Layer, Surface,
    envelope_areas, envelope_ua, surface_u,
)
from backend.app.core.errors import CalcError
from backend.app.core.sources import CATALOG

# Сэндвич-панель: сталь 0.5 мм + PIR 40 мм + сталь 0.5 мм
PANEL_40 = Surface(layers=(Layer(0.5, "steel"), Layer(40, "pir_core"), Layer(0.5, "steel")))
R_PANEL_40 = 0.0005 / 50 + 0.040 / 0.022 + 0.0005 / 50


def test_wall_u_by_hand():
    # Стена: поток горизонтальный, R_si 0.13
    assert surface_u(PANEL_40, "wall") == pytest.approx(1 / (0.13 + R_PANEL_40 + 0.04), rel=1e-9)


def test_roof_uses_upward_surface_resistance():
    # Кровля зимой: поток вверх, R_si 0.10 (BR 443 §4.3) — U выше, чем у стены
    assert surface_u(PANEL_40, "roof") == pytest.approx(1 / (0.10 + R_PANEL_40 + 0.04), rel=1e-9)
    assert surface_u(PANEL_40, "roof") > surface_u(PANEL_40, "wall")


def test_steep_roof_counts_as_wall():
    # Круче 60° — поток в пределах ±30° от горизонтали, R_si как у стены
    assert surface_u(PANEL_40, "roof", roof_pitch_deg=70) == surface_u(PANEL_40, "wall")


def test_layer_sum_is_below_declared_panel_u():
    # Та же панель в декларации: Ud,S = 0.57. По слоям меньше — декларация учитывает
    # стыки и крепёж. Поэтому для панелей предпочтителен U из декларации
    assert surface_u(PANEL_40, "wall") == pytest.approx(0.503, abs=0.001)
    assert surface_u(Surface(u_w_m2k=0.57), "wall") == 0.57


def test_brick_wall_with_render():
    # Кирпич 250 мм (наружная верста) + штукатурка 20 мм с двух сторон
    wall = Surface(layers=(Layer(20, "mortar_exposed"), Layer(250, "brick_exposed"),
                           Layer(20, "mortar_protected")))
    r = 0.02 / 0.94 + 0.25 / 0.77 + 0.02 / 0.88
    assert surface_u(wall, "wall") == pytest.approx(1 / (0.13 + r + 0.04), rel=1e-9)


def test_declared_lambda_layer_for_insulation():
    # Минвата — только с λ из паспорта (в справочнике её нет намеренно)
    wall = Surface(layers=(Layer(100, lambda_w_mk=0.040),))
    assert surface_u(wall, "wall") == pytest.approx(1 / (0.13 + 2.5 + 0.04), rel=1e-9)


# ─── Геометрия ────────────────────────────────────────────────────────────────

def test_flat_roof_area_matches_existing_envelope_area():
    # Один корпус — одна площадь: и калибровка UA, и расчёт по слоям делят на неё
    g = HouseGeometry(length_m=120, width_m=16, wall_height_m=3)
    old = envelope_area_m2(BuildingDimensions(length_m=120, width_m=16, height_m=3))
    assert envelope_areas(g).total_m2 == pytest.approx(old, rel=1e-9)


def test_gable_roof_areas():
    g = HouseGeometry(length_m=120, width_m=16, wall_height_m=3, ridge_height_m=4.5)
    a = envelope_areas(g)
    assert a.side_walls_m2 == pytest.approx(720)
    assert a.end_walls_m2 == pytest.approx(2 * (16 * 3 + 8 * 1.5))      # 120
    assert a.roof_m2 == pytest.approx(2 * 120 * math.hypot(8, 1.5))     # ≈ 1953.5
    assert a.roof_pitch_deg == pytest.approx(math.degrees(math.atan(1.5 / 8)))


def test_envelope_ua_sums_parts():
    g = HouseGeometry(length_m=120, width_m=16, wall_height_m=3, ridge_height_m=4.5)
    brick = Surface(layers=(Layer(250, "brick_exposed"),))
    res = envelope_ua(g, walls=PANEL_40, roof=PANEL_40, end_walls=brick)
    a = res.areas
    expected = (surface_u(PANEL_40, "wall") * a.side_walls_m2
                + surface_u(brick, "wall") * a.end_walls_m2
                + surface_u(PANEL_40, "roof") * a.roof_m2)
    assert res.ua_w_per_k == pytest.approx(expected, rel=1e-9)
    # Торцы без своей конструкции — как стены
    same = envelope_ua(g, walls=PANEL_40, roof=PANEL_40)
    assert same.end_walls_u == same.side_walls_u


# ─── Ошибки ───────────────────────────────────────────────────────────────────

G = HouseGeometry(length_m=120, width_m=16, wall_height_m=3)


def test_unknown_material():
    with pytest.raises(CalcError) as e:
        surface_u(Surface(layers=(Layer(100, "unobtainium"),)), "wall")
    assert e.value.code == "material_not_found" and e.value.params == {"id": "unobtainium"}


@pytest.mark.parametrize("layer", [
    Layer(100),                                            # нет источника λ
    Layer(100, "brick_exposed", lambda_w_mk=0.5),          # два источника
    Layer(0, "brick_exposed"),                             # нулевая толщина
    Layer(100, lambda_w_mk=0.001),                         # λ вне физики
])
def test_invalid_layer(layer):
    with pytest.raises(CalcError) as e:
        surface_u(Surface(layers=(layer,)), "wall")
    assert e.value.code == "validation_failed"


def test_thickness_typo_is_implausible():
    # PIR 1000 мм вместо 100: U ≈ 0.02 — ниже физического коридора
    huge = Surface(layers=(Layer(1000, "pir_core"),))
    with pytest.raises(CalcError) as e:
        envelope_ua(G, walls=huge, roof=huge)
    assert e.value.code == "envelope_implausible"


def test_single_steel_sheet_is_still_plausible():
    # Голая профнастил-«штора»: U ≈ 5.9 — плохо, но физично (верх коридора 8)
    sheet = Surface(layers=(Layer(0.5, "steel"),))
    assert envelope_ua(G, walls=sheet, roof=sheet).mean_u_w_m2k < 8


# ─── Справочник ───────────────────────────────────────────────────────────────

def test_every_material_has_a_known_source():
    for m in MATERIALS.values():
        assert m.source_id in CATALOG, m.id
        assert 0.01 <= m.lambda_w_mk <= 200, m.id


def test_no_generic_insulation_in_catalog():
    # BR 443 §3: λ утеплителя — только из декларации производителя
    assert not {"mineral_wool", "eps", "xps"} & MATERIALS.keys()
