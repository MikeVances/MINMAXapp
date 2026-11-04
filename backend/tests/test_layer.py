"""
Товарные несушки и ремонтный молодняк в клетках (species="layer", housing="cages")
и бройлеры в клетках (broiler_cages) в ядре, API v1 и маршрутах интерфейса (/calc).

Эталоны из первоисточников (refs/layers, ссылки — core/sources.py):
  CIGR 2002 §2.7.2 ур. 17: Φtot(20 °C) = 6.28·m^0.75 + 25·Y2 [Вт/гол];
  CIGR 2002 §3.3.2 ур. 34: Φs_house = [0.67·(1000 + 20·(20 − t)) − 9.8·10⁻⁸·t⁶] / 1000 · Φtot(20 °C);
  Lohmann LSL-Classic & Lohmann Brown-Classic Cage Management Guides (2019):
    ремонт 1–17 нед. (1–119 сут, Y2 = 0) и яйцекладка 18–72 нед. (120–504 сут, плато массы, Y2 > 0);
  Hy-Line Brown (2024/2018) & Hy-Line W-36 (2025):
    кривые живой массы, суточной яйцемассы и таблица минвентиляции Dr. Hongwei Xin (hyline_2018_xin).
"""
from __future__ import annotations

import os
import shutil
from copy import deepcopy
from pathlib import Path

import pytest

from backend.app.core import layer_norms as ln
from backend.app.core.bird_heat import house_heat_per_bird, layer_cage_sensible_fraction
from backend.app.core.growth_profiles import load_profile
from backend.app.core.ventilation_calc import calc_q_min_per_bird

ROOT = Path(__file__).resolve().parents[2]
PROFILES = Path(os.environ["GROWTH_PROFILES_DIR"])
LAYERS = (
    "lohmann-lsl-classic",
    "lohmann-brown-classic",
    "hyline-brown",
    "hyline-w36",
)

# Клеточный корпус 100 × 18 м, стена 4.0 м, 6 рядов батарей 1.4 × 3.2 м:
# полное сечение = 72.0 м², батареи = 6 × 1.4 × 3.2 = 26.88 м², свободное сечение = 45.12 м²
CAGE_HOUSE = {
    "length_m": 100.0,
    "width_m": 18.0,
    "wall_height_m": 4.0,
    "cage_rows": [{"count": 6, "width_m": 1.4, "height_m": 3.2}],
}
FREE_SECTION_M2 = 18.0 * 4.0 - 6 * 1.4 * 3.2  # 45.12 м²


@pytest.fixture(scope="module", autouse=True)
def layer_profiles():
    copied = []
    for pid in LAYERS:
        dst = PROFILES / "builtin" / f"{pid}.json"
        if not dst.exists():
            shutil.copy(ROOT / "data" / "growth_profiles" / "builtin" / f"{pid}.json", dst)
            copied.append(dst)
    yield
    for p in copied:
        p.unlink(missing_ok=True)


def test_cigr_2002_layer_cage_heat_and_co2_equations():
    # CIGR 2002 §2.7.2 ур. 17: Φtot(20 °C) = 6.28·m^0.75 + 25·Y2
    # Ремонтная молодка 1.2 кг (Y2 = 0) при 20 °C:
    phi_pullet_20 = 6.28 * (1.2 ** 0.75)
    # CIGR 2002 §3.3.2 ур. 34 при 20 °C: [0.67·1000 − 9.8e-8·20^6] / 1000 = 0.67 − 0.006272 = 0.663728
    f_sens_20 = (0.67 * 1000.0 - 9.8e-8 * (20.0 ** 6)) / 1000.0
    assert layer_cage_sensible_fraction(20.0) == pytest.approx(f_sens_20, rel=1e-6)
    h_pullet = house_heat_per_bird(1.2, 20.0, "layer", 0.0)
    assert h_pullet.total_w == pytest.approx(phi_pullet_20, rel=1e-6)
    assert h_pullet.sensible_w == pytest.approx(phi_pullet_20 * f_sens_20, rel=1e-6)

    # Взрослая несушка 1.75 кг с суточной яйцемассой Y2 = 60 г (0.060 кг) при 20 °C:
    phi_hen_20 = 6.28 * (1.75 ** 0.75) + 25.0 * 0.060
    h_hen = house_heat_per_bird(1.75, 20.0, "layer", 0.060)
    assert h_hen.total_w == pytest.approx(phi_hen_20, rel=1e-6)
    assert h_hen.total_w > house_heat_per_bird(1.75, 20.0, "layer", 0.0).total_w

    # Минимум по CO₂ растёт с яйцемассой пропорционально полному теплу (185 мл CO₂/ч на Вт; calc_q_min_per_bird округляет до 4 знаков)
    q_no_egg = calc_q_min_per_bird(1.75, 1.5, "layer", 0.0)
    q_with_egg = calc_q_min_per_bird(1.75, 1.5, "layer", 0.060)
    assert q_with_egg / q_no_egg == pytest.approx(phi_hen_20 / (6.28 * (1.75 ** 0.75)), rel=1e-3)


def test_builtin_layer_profiles_rearing_vs_production_plateau():
    for pid in LAYERS:
        p = load_profile(pid)
        assert p.species == "layer"
        assert p.sex == "female"
        daily = p.daily()
        assert min(daily) == 0 and max(daily) == 504
        # В ремонте (до 119 сут / 17 нед.) яйцемасса равна 0, вес растёт с ~37–40 г до ~1.22–1.48 кг
        assert (daily[7].egg_mass_g or 0.0) == 0.0
        assert (daily[119].egg_mass_g or 0.0) == 0.0
        assert 1150 <= daily[119].body_weight_g <= 1550
        # Во взрослом стаде (с 30 нед. = 210 сут до 72 нед. = 504 сут) масса стабильна (плато), а Y2 > 50 г/сут
        w_210 = daily[210].body_weight_g
        w_504 = daily[504].body_weight_g
        assert abs(w_504 - w_210) / w_210 < 0.06, f"{pid}: adult weight not stable ({w_210} -> {w_504})"
        assert daily[210].egg_mass_g >= 53.0
        assert daily[350].egg_mass_g >= 54.0


def test_xin_and_hendrix_min_vent_norms():
    # Dr. Hongwei Xin (Hy-Line Brown Guide 2018, с. 17): м³/ч на 1000 птиц
    # Неделя 1 (до 7 сут) → 75 м³/ч на 1000 гол = 0.075 м³/ч·гол
    assert ln.guide_min_vent_m3h(ln.HYLINE_2018_XIN, 50_000, 0.06, 5) == pytest.approx(50_000 * 0.075)
    # Неделя 18 (126 сут) → 600 м³/ч на 1000 гол = 0.60 м³/ч·гол
    assert ln.guide_min_vent_m3h(ln.HYLINE_2018_XIN, 50_000, 1.48, 126) == pytest.approx(50_000 * 0.60)
    # Взрослая несушка (19+ нед., ≥ 127 сут) → 700 м³/ч на 1000 гол = 0.70 м³/ч·гол
    assert ln.guide_min_vent_m3h(ln.HYLINE_2018_XIN, 50_000, 1.90, 210) == pytest.approx(50_000 * 0.70)
    # Hendrix Genetics (0.7 м³/ч на кг живой массы)
    assert ln.guide_min_vent_m3h(ln.HENDRIX_CAGE_07, 50_000, 1.80, 210) == pytest.approx(50_000 * 1.80 * 0.7)


def test_api_v1_layer_cages_rearing_and_production(client):
    # 1) Напольное содержание для товарной несушки запрещено (422 housing_not_for_species)
    bad_floor = client.post(
        "/api/v1/ventilation-requirements",
        json={
            "house": {"length_m": 100, "width_m": 18, "wall_height_m": 4.0},
            "flock": {
                "birds": 60000,
                "growth_profile_id": "lohmann-lsl-classic",
                "housing": "floor_litter",
                "age_days": 70,
                "stage": "rearing",
            },
            "conditions": {"outdoor_t_c": 10.0, "outdoor_rh_pct": 70.0},
        },
    )
    assert bad_floor.status_code == 422 and bad_floor.json()["code"] == "housing_not_for_species"

    # 2) Ремонтный молодняк в клетках (день 56, 8 нед.) vs взрослая несушка (день 210, 30 нед., пик яйцекладки)
    req_rearing = client.post(
        "/api/v1/ventilation-requirements",
        json={
            "house": CAGE_HOUSE,
            "flock": {
                "birds": 60000,
                "growth_profile_id": "hyline-brown",
                "housing": "cages",
                "age_days": 56,
                "stage": "rearing",
            },
            "conditions": {"outdoor_t_c": -10.0, "outdoor_rh_pct": 80.0},
        },
    )
    assert req_rearing.status_code == 201
    jr = req_rearing.json()
    assert jr["tunnel"]["free_section_m2"] == pytest.approx(FREE_SECTION_M2, abs=0.01)
    src_ids = {s["id"] for s in jr["sources"]}
    assert "cigr_2002_layer_cages" in src_ids
    assert "hyline_2018_xin_vent" in src_ids
    # Напольная сплит-оговорка бройлера (aarnink_2018 / cages_heat_split_bounded) у несушек не добавляется
    assert "aarnink_2018" not in src_ids
    assert all(a["code"] != "cages_heat_split_bounded" for a in jr["assumptions"])

    req_prod = client.post(
        "/api/v1/ventilation-requirements",
        json={
            "house": CAGE_HOUSE,
            "flock": {
                "birds": 60000,
                "growth_profile_id": "hyline-brown",
                "housing": "cages",
                "age_days": 210,
                "stage": "production",
            },
            "conditions": {"outdoor_t_c": 26.0, "outdoor_rh_pct": 55.0},
        },
    )
    assert req_prod.status_code == 201
    jp = req_prod.json()
    assert jp["qmin_m3h"] > jr["qmin_m3h"]
    # Авто-добавления петухов у товарной несушки нет (в отличие от родительского стада бройлеров)
    assert all(a["code"] != "breeder_males_auto_added" for a in jp["assumptions"])

    # 3) Проектный расчёт продуктивного корпуса (дни 120–504)
    des = client.post(
        "/api/v1/ventilation-designs",
        json={
            "house": CAGE_HOUSE,
            "envelope": {"walls": {"u_w_m2k": 0.35}, "roof": {"u_w_m2k": 0.25}},
            "flock": {
                "birds": 60000,
                "growth_profile_id": "lohmann-lsl-classic",
                "housing": "cages",
                "first_day": 120,
                "cycle_days": 504,
                "stage": "production",
                "mortality_pct": 3.0,
            },
            "climate": {"winter_design_c": -20.0, "summer_design_db_c": 32.0, "summer_design_rh_pct": 45.0},
        },
    )
    assert des.status_code == 201
    jdes = des.json()
    assert jdes["days"][0]["day"] == 120 and jdes["days"][-1]["day"] == 504
    assert jdes["equipment"]["tunnel_free_section_m2"] == pytest.approx(FREE_SECTION_M2, abs=0.01)
    assert jdes["equipment"]["tunnel_fans_basis"] == "aisle_speed"


def test_calc_summary7_and_minmax_for_broiler_cages_and_layers_cages(client):
    # 1) Ремонтный молодняк несушек в /calc/summary7 (по умолчанию дни 1..119)
    r_rear = client.post(
        "/calc/summary7",
        json={
            "house": "L1",
            "birds": 60000,
            "growth_profile_id": "lohmann-brown-classic",
            "housing": "cages",
            "stage": "rearing",
            "house_length_m": 100.0,
            "house_width_m": 18.0,
            "house_height_m": 4.0,
            "cage_rows_count": 6,
            "cage_row_width_m": 1.4,
            "cage_row_height_m": 3.2,
            "outside_t": 28.0,
            "outside_rh": 50.0,
        },
    )
    assert r_rear.status_code == 200
    jr = r_rear.json()
    assert jr["species"] == "layer" and jr["housing"] == "cages"
    assert jr["first_day"] == 1 and jr["last_day"] == 119
    assert jr["tunnel_free_section_m2"] == pytest.approx(FREE_SECTION_M2, abs=0.01)
    assert jr["males_auto_added"] is False

    # 2) Взрослое стадо несушек в /calc/summary7 (по умолчанию дни 120..504)
    r_prod = client.post(
        "/calc/summary7",
        json={
            "house": "L2",
            "birds": 60000,
            "growth_profile_id": "lohmann-brown-classic",
            "housing": "cages",
            "stage": "production",
            "house_length_m": 100.0,
            "house_width_m": 18.0,
            "house_height_m": 4.0,
            "cage_rows_count": 6,
            "cage_row_width_m": 1.4,
            "cage_row_height_m": 3.2,
            "outside_t": 28.0,
            "outside_rh": 50.0,
        },
    )
    assert r_prod.status_code == 200
    jp = r_prod.json()
    assert jp["first_day"] == 120 and jp["last_day"] == 504
    # Туннельный расход на 504-й день считается по свободному сечению проходов (45.12 м²) и скорости 4.5 м/с
    assert jp["rows"][-1]["q_max_nominal_m3h"] == pytest.approx(4.5 * FREE_SECTION_M2 * 3600.0, rel=1e-4)

    # 3) Бройлеры в клетках в /calc/summary7 и /calc/minmax:
    # без размеров клеточных батарей в жару сообщается house_geometry_missing = True
    r_bc_missing = client.post(
        "/calc/summary7",
        json={
            "house": "BC1",
            "birds": 50000,
            "housing": "cages",
            "house_length_m": 100.0,
            "house_width_m": 18.0,
            "house_height_m": 4.0,
            "outside_t": 30.0,
            "outside_rh": 50.0,
        },
    ).json()
    assert r_bc_missing["rows"][-1]["house_geometry_missing"] is True

    # С размерами батарей туннель считается по свободному сечению, а в переходном режиме Qmax выше напольного
    r_bc = client.post(
        "/calc/minmax",
        json={
            "house": "BC1",
            "birds": 50000,
            "age_days": 20,
            "housing": "cages",
            "house_length_m": 100.0,
            "house_width_m": 18.0,
            "house_height_m": 4.0,
            "cage_rows_count": 6,
            "cage_row_width_m": 1.4,
            "cage_row_height_m": 3.2,
            "outside_t": 18.0,
            "outside_rh": 60.0,
        },
    ).json()
    r_bf = client.post(
        "/calc/minmax",
        json={
            "house": "BC1",
            "birds": 50000,
            "age_days": 20,
            "housing": "floor_litter",
            "house_length_m": 100.0,
            "house_width_m": 18.0,
            "house_height_m": 4.0,
            "outside_t": 18.0,
            "outside_rh": 60.0,
        },
    ).json()
    # В 20 сут при +18 °C (тепловой баланс без туннеля) у бройлера в клетках больше явного тепла воздуха → выше Qmax
    assert r_bc["q_max_nominal_m3h"] > r_bf["q_max_nominal_m3h"]
