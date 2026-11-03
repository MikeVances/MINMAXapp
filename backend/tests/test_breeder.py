"""
Родительское стадо бройлеров (broiler_breeder): закон тепла CIGR 2002 §2.7.3 ур. 18,
встроенные профили Ross 308 PS и Cobb 500 FF / Cobb MX, норма минвентиляции Ross PS
Table 25, этапы «Ремонт» (rearing) и «Продуктивный период» (production), автоматическое
добавление петухов к курам в продуктивном периоде.

Эталоны — из первоисточников (refs/breeders, ссылки — core/sources.py):
  CIGR 2002 §2.7.3 ур. 18: Φtot(20 °C) = 6.8·m^0.75 + 25·Y2 [Вт/гол];
  Ross PS Handbook 2023 Table 4 с. 25: температура посадки 30→21 °C к 24 сут, 20 °C в продуктивном;
  Ross PS Handbook 2023 Table 18 с. 66: доля петухов по возрасту (10 % → 7 %);
  Ross PS Handbook 2023 Table 25 с. 113: минвентиляция на голову по живой массе;
  Ross PS Performance Objectives 2021 с. 4, 7, 10: живая масса ♀/♂ и суточная яйцемасса Y2;
  Cobb Breeder Management Guide 2021 с. 26, 51, 123: температура, тоннель 2.5/3.0 м/с, 10 % петухов;
  Cobb500 FF Supplement 2026 с. 5, 9 и Cobb Male Supplement 2026 с. 11: масса и суточная яйцемасса.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
from copy import deepcopy
from pathlib import Path

import pytest

from backend.app.core import breeder_norms as bn
from backend.app.core.bird_heat import house_heat_per_bird
from backend.app.core.growth_profiles import load_profile
from backend.app.core.ventilation_calc import calc_q_min_per_bird

ROOT = Path(__file__).resolve().parents[2]
PROFILES = Path(os.environ["GROWTH_PROFILES_DIR"])
BREEDERS = (
    "ross308-ps-females",
    "ross308-ps-males",
    "cobb500ff-females",
    "cobb-mx-males",
)

# Корпус 120 × 15 = 1800 м²: 9000 кур — 5.0 гол/м²
HOUSE = {"length_m": 120, "width_m": 15, "wall_height_m": 3.0, "ridge_height_m": 4.5}
FLOOR_M2 = 120 * 15
REQ_REARING = {
    "house": HOUSE,
    "flock": {
        "birds": 9000,
        "growth_profile_id": "ross308-ps-females",
        "age_days": 140,
        "housing": "floor_litter",
        "stage": "rearing",
    },
    "conditions": {"outdoor_t_c": -10.0, "outdoor_rh_pct": 80.0},
}
REQ_PROD = {
    "house": HOUSE,
    "flock": {
        "birds": 9000,
        "growth_profile_id": "ross308-ps-females",
        "age_days": 210,
        "housing": "floor_litter",
        "stage": "production",
    },
    "conditions": {"outdoor_t_c": -10.0, "outdoor_rh_pct": 80.0},
}
DESIGN_REARING = {
    "house": HOUSE,
    "envelope": {"walls": {"u_w_m2k": 0.4}, "roof": {"u_w_m2k": 0.25}},
    "flock": {
        "birds": 9000,
        "growth_profile_id": "ross308-ps-females",
        "first_day": 1,
        "cycle_days": 140,
        "housing": "floor_litter",
        "mortality_pct": 0,
        "stage": "rearing",
    },
    "climate": {"winter_design_c": -20, "summer_design_db_c": 32, "summer_design_rh_pct": 40},
}
DESIGN_PROD = {
    "house": HOUSE,
    "envelope": {"walls": {"u_w_m2k": 0.4}, "roof": {"u_w_m2k": 0.25}},
    "flock": {
        "birds": 9000,
        "growth_profile_id": "ross308-ps-females",
        "first_day": 141,
        "cycle_days": 448,
        "housing": "floor_litter",
        "mortality_pct": 0,
        "stage": "production",
    },
    "climate": {"winter_design_c": -20, "summer_design_db_c": 32, "summer_design_rh_pct": 40},
}


@pytest.fixture(scope="module", autouse=True)
def breeder_profiles():
    copied = []
    for pid in BREEDERS:
        dst = PROFILES / "builtin" / f"{pid}.json"
        shutil.copyfile(ROOT / "data/growth_profiles/builtin" / f"{pid}.json", dst)
        copied.append(dst)
    yield
    for dst in copied:
        dst.unlink()


def _with(base: dict, **patch) -> dict:
    r = deepcopy(base)
    for part, values in patch.items():
        r[part].update(values)
    return r


def _post(client, path: str, body: dict, status: int = 201) -> dict:
    r = client.post(path, json=body)
    assert r.status_code == status, r.text
    return r.json()


def _codes(notes) -> set:
    return {n["code"] for n in notes}


# ─── Закон тепла CIGR 2002 §2.7.3 ур. 18 и CO₂ ───────────────────────────────

def test_breeder_total_heat_is_cigr_eq18():
    # При 20 °C температурный множитель равен 1.0: Φtot = 6.8·m^0.75 + 25·Y2
    h_rearing = house_heat_per_bird(2.230, 20.0, "broiler_breeder", egg_mass_kg=0.0)
    assert h_rearing.total_w == pytest.approx(6.8 * 2.230 ** 0.75)

    h_prod = house_heat_per_bird(3.410, 20.0, "broiler_breeder", egg_mass_kg=0.0506)
    assert h_prod.total_w == pytest.approx(6.8 * 3.410 ** 0.75 + 25.0 * 0.0506)


def test_breeder_co2_minimum_includes_egg_mass_heat():
    expected = (6.8 * 3.410 ** 0.75 + 25.0 * 0.0506) * 0.153 / 2.6 * 1.5
    assert calc_q_min_per_bird(
        3.410, 1.5, "broiler_breeder", egg_mass_kg=0.0506
    ) == pytest.approx(expected, abs=1e-3)


# ─── Профили и генератор ─────────────────────────────────────────────────────

def test_profiles_are_what_the_generator_builds():
    spec = importlib.util.spec_from_file_location("bbp", ROOT / "scripts/build_breeder_profiles.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for profile in module.build():
        on_disk = json.loads((ROOT / "data/growth_profiles/builtin" / f"{profile['id']}.json").read_text("utf-8"))
        assert on_disk == profile, profile["id"]


def test_profile_days_match_the_guides(client):
    ross_f = {d["day"]: d for d in client.get("/api/v1/growth-profiles/ross308-ps-females").json()["days"]}
    # Неделя 20 (140 сут): 2230 г, яйцемасса 0, уставка 21 °C; неделя 30 (210 сут): 3410 г, 50.6 г/сут, 20 °C
    assert ross_f[140]["weight_g"] == 2230.0 and ross_f[140]["egg_mass_g"] == 0.0
    assert ross_f[140]["temp_c"] == 21.0 and ross_f[141]["temp_c"] == 20.0
    assert ross_f[210]["weight_g"] == 3410.0 and ross_f[210]["egg_mass_g"] == 50.6
    assert ross_f[448]["weight_g"] == 4085.0 and ross_f[448]["egg_mass_g"] == 37.5

    cobb_f = {d["day"]: d for d in client.get("/api/v1/growth-profiles/cobb500ff-females").json()["days"]}
    # Cobb 500 FF: 20 недель — 2300 г; 30 недель (210 сут) — 3600 г, 49.2 г/сут; 65 недель (455 сут) — 4260 г
    assert cobb_f[140]["weight_g"] == 2300.0 and cobb_f[140]["egg_mass_g"] == 0.0
    assert cobb_f[210]["weight_g"] == 3600.0 and cobb_f[210]["egg_mass_g"] == 49.2
    assert cobb_f[455]["weight_g"] == 4260.0 and cobb_f[28]["temp_c"] == 21.0


# ─── Норма минвентиляции Ross PS Table 25 и доля петухов ─────────────────────

def test_ross_table25_interpolation_and_bounds():
    # Границы таблицы: ≤ 0.05 кг → 0.09 м³/ч; ≥ 5.0 кг → 2.89 м³/ч
    assert bn.table25_per_bird_m3h(0.04) == pytest.approx(0.09)
    assert bn.table25_per_bird_m3h(5.5) == pytest.approx(2.89)
    # Ровно узлы таблицы: 2.2 кг → 1.56, 2.4 кг → 1.67; 2.3 кг — середина
    assert bn.table25_per_bird_m3h(2.3) == pytest.approx((1.56 + 1.67) / 2)
    assert bn.guide_min_vent_m3h(bn.ROSS_PS_TABLE25, 1000, 2.2) == pytest.approx(1560.0)


def test_production_males_follows_guide_tables():
    ross_f = load_profile("ross308-ps-females")
    cobb_f = load_profile("cobb500ff-females")
    # Ross Table 18: 210 сут (30 нед) → 9.5 % (0.095), 400 сут (>50 нед) → 7.0 % (0.070)
    assert bn.production_males(ross_f, 210) == (
        "ross308-ps-males", 0.095, "ross_ps_2023_t18"
    )
    assert bn.production_males(ross_f, 400) == (
        "ross308-ps-males", 0.070, "ross_ps_2023_t18"
    )
    # Cobb Breeder Guide p. 51: 10 % (0.100) на весь продуктивный период
    assert bn.production_males(cobb_f, 210) == (
        "cobb-mx-males", 0.100, "cobb_breeder_2021_males"
    )


# ─── Расчёт в ремонте и продуктивном периоде ─────────────────────────────────

def test_rearing_uses_unadjusted_cigr_and_does_not_add_males(client):
    j = _post(client, "/api/v1/ventilation-requirements", REQ_REARING)
    assert j["weight_g"] == 2230.0
    assert (j["qmin_basis"], j["qmin_m3h"]) == (
        "guide",
        round(9000 * bn.table25_per_bird_m3h(2.230)),
    )
    codes = _codes(j["assumptions"])
    assert {"breeder_sensible_from_broiler", "breeder_rearing_cigr_unadjusted", "qmin_includes_guide_norm"} <= codes
    assert "breeder_males_auto_added" not in codes
    assert {"cigr_2002_breeder", "ross_ps_2023_t25", "ross_ps_2023_t4"} <= {s["id"] for s in j["sources"]}


def test_production_automatically_adds_males_on_top_of_hens(client):
    # В 210 сут к 9000 кур Ross 308 PS автоматически добавляются 855 петухов (9.5 %)
    # Масса кур 3410 г, масса петухов 4150 г (30-я неделя Ross PS Male)
    j = _post(client, "/api/v1/ventilation-requirements", REQ_PROD)
    codes = _codes(j["assumptions"])
    assert "breeder_males_auto_added" in codes
    assert "breeder_rearing_cigr_unadjusted" not in codes
    assert "ross_ps_2023_t18" in {s["id"] for s in j["sources"]}

    expected_guide = 9000 * bn.table25_per_bird_m3h(3.410) + 855 * bn.table25_per_bird_m3h(4.150)
    assert (j["qmin_basis"], j["qmin_m3h"]) == ("guide", round(expected_guide))
    expected_avg_w = (9000 * 3410.0 + 855 * 4150.0) / (9000 + 855)
    assert j["weight_g"] == pytest.approx(expected_avg_w, abs=0.2)


def test_explicit_companion_disables_auto_added_males(client):
    # Если вторая группа задана явно через hens, автодобавление петухов не срабатывает
    body = _with(
        REQ_PROD,
        flock={
            "growth_profile_id": "ross308-ps-males",
            "birds": 500,
            "hens": {"growth_profile_id": "ross308-ps-females", "birds": 9000},
        },
    )
    j = _post(client, "/api/v1/ventilation-requirements", body)
    assert "breeder_males_auto_added" not in _codes(j["assumptions"])
    expected_guide = 9000 * bn.table25_per_bird_m3h(3.410) + 500 * bn.table25_per_bird_m3h(4.150)
    assert j["qmin_m3h"] == round(expected_guide)


def test_cobb_breeder_has_no_guide_min_vent_norm(client):
    body = _with(REQ_REARING, flock={"growth_profile_id": "cobb500ff-females"})
    j = _post(client, "/api/v1/ventilation-requirements", body)
    assert j["qmin_basis"] in ("co2", "moisture")
    assert "qmin_includes_guide_norm" not in _codes(j["assumptions"])


# ─── Проект корпуса: скорость тоннеля и плотность посадки ────────────────────

def test_tunnel_speed_is_2_5_in_rearing_and_3_0_in_production(client):
    eq_rear = _post(client, "/api/v1/ventilation-designs", DESIGN_REARING)["equipment"]
    eq_prod = _post(client, "/api/v1/ventilation-designs", DESIGN_PROD)["equipment"]
    # Средняя высота 15-метрового корпуса со стеной 3.0 и коньком 4.5 равна 3.75 м
    cross_m2 = 15 * 3.75
    assert eq_rear["tunnel_air_speed_ms"]["max"] == 2.5
    assert eq_rear["tunnel_fans_m3h"]["max"] == round(2.5 * cross_m2 * 3600)
    assert eq_rear["tunnel_air_speed_ms"]["source_id"] == "cobb_breeder_2021_tunnel"

    assert eq_prod["tunnel_air_speed_ms"]["max"] == 3.0
    assert eq_prod["tunnel_fans_m3h"]["max"] == round(3.0 * cross_m2 * 3600)


def test_breeder_density_warning_respects_stage_and_line(client):
    # В продуктивном периоде Ross предел 5.5 гол/м²: 9200 кур + 10 % петухов (920) = 10120 гол → 5.62 гол/м² > 5.5
    j = _post(client, "/api/v1/ventilation-designs", _with(DESIGN_PROD, flock={"birds": 9200}))
    note = next(n for n in j["warnings"] if n["code"] == "breeder_density_high")
    assert note["params"]["limit_head_per_m2"] == 5.5
    assert note["source_id"] == "ross_ps_2023_density"

    # Для Cobb в продуктивном периоде предел 7.0 гол/м²: 9200 кур + 920 петухов = 5.62 гол/м² ≤ 7.0
    j_cobb = _post(
        client,
        "/api/v1/ventilation-designs",
        _with(DESIGN_PROD, flock={"growth_profile_id": "cobb500ff-females", "birds": 9200}),
    )
    assert "breeder_density_high" not in _codes(j_cobb["warnings"])


# ─── Валидация входов ────────────────────────────────────────────────────────

@pytest.mark.parametrize("patch, code", [
    ({"stage": None}, "turkey_stage_required"),
    ({"stage": "grow_out"}, "turkey_stage_required"),
    ({"housing": "cages"}, "housing_not_for_species"),
])
def test_invalid_breeder_inputs_are_rejected(client, patch, code):
    body = _with(REQ_REARING, flock=patch)
    body["flock"] = {k: v for k, v in body["flock"].items() if v is not None}
    if patch.get("housing") == "cages":
        body["house"] = {**HOUSE, "cage_rows": [{"count": 4, "width_m": 1.6, "height_m": 2.2}]}
    r = client.post("/api/v1/ventilation-requirements", json=body)
    assert r.status_code == 422 and r.json()["code"] == code, r.text


# ─── Маршруты интерфейса (/calc/summary7 и /profiles) ────────────────────────

def test_ui_summary7_defaults_to_rearing_and_production_windows(client):
    base = {
        "house": "H1",
        "birds": 9000,
        "outside_t": -20.0,
        "outside_rh": 80.0,
        "house_width_m": 15.0,
        "house_height_m": 3.75,
        "growth_profile_id": "ross308-ps-females",
    }
    rear = client.post("/calc/summary7", json={**base, "stage": "rearing"}).json()
    assert (rear["first_day"], rear["last_day"]) == (1, 140)
    assert (rear["rows"][0]["day"], rear["rows"][-1]["day"]) == (1, 140)
    assert rear["rows"][0]["birds_eff"] == 9000

    prod = client.post("/calc/summary7", json={**base, "stage": "production"}).json()
    assert (prod["first_day"], prod["last_day"]) == (141, 448)
    assert (prod["rows"][0]["day"], prod["rows"][-1]["day"]) == (141, 448)
    # На 141-й день к 9000 кур автоматически добавлено 10 % петухов (900 гол) → всего 9900 голов в корпусе
    assert prod["rows"][0]["birds_eff"] == 9900


def test_custom_copy_of_breeder_preserves_species_and_egg_mass(client):
    src = client.get("/profiles/ross308-ps-females").json()
    assert (src["species"], src["sex"], src["last_day"]) == ("broiler_breeder", "female", 448)
    body = {
        "name": "Моё родительское стадо",
        "species": "broiler_breeder",
        "sex": "female",
        "min_vent_norm": src["min_vent_norm"],
        "points": [
            {k: p[k] for k in ("day", "body_weight_g", "min_temp_c", "rv_percent", "egg_mass_g") if p.get(k) is not None}
            for p in src["points"]
        ],
    }
    r = client.put("/profiles/my-breeders", json=body)
    assert r.status_code == 200, r.text
    try:
        saved = client.get("/profiles/my-breeders").json()
        days = {d["day"]: d for d in saved["days"]}
        assert days[210]["egg_mass_g"] == 50.6
        mine = _post(client, "/api/v1/ventilation-requirements", _with(REQ_REARING, flock={"growth_profile_id": "my-breeders"}))
        theirs = _post(client, "/api/v1/ventilation-requirements", REQ_REARING)
        assert (mine["qmin_m3h"], mine["qmin_basis"]) == (theirs["qmin_m3h"], theirs["qmin_basis"])
    finally:
        client.delete("/profiles/my-breeders")
