"""
Индейка (2026-10-26): закон тепла, профили B.U.T. 6 / Converter, норма минвентиляции
производителя, брудер и доращивание как отдельные корпуса.

Эталоны — из первоисточников (refs/turkey, ссылки — core/sources.py), а не вызовом
модуля:
  CIGR 2002 §2.7.4 ур. 19: Φtot(20 °C) = 9.86·m^0.77 Вт;
  Aviagen CL23 с. 30: минимум 1 м³/ч на кг живой массы; табл. 5 — уставки;
  Hybrid CMG с. 46: 0.17 м³/ч·гол (> 10 гол/м²) или 1.7 м³/ч·м² (< 10) × неделя возраста;
  Hybrid CMG с. 51: тоннель 2 м/с; Hybrid ventcalc: 18.3 / 27.5 м³/ч·м²;
  Aviagen CL23 с. 13: на доращивании не больше 3.2 самца на м².

Профили — НАСТОЯЩИЕ встроенные файлы индейки, на время модуля копируются в каталог
профилей тестов (conftest); рабочий data/ не трогается.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
from copy import deepcopy
from pathlib import Path

import pytest

from backend.app.core import turkey_norms as tn
from backend.app.core.bird_heat import house_heat_per_bird
from backend.app.core.ventilation_calc import calc_q_min_per_bird

ROOT = Path(__file__).resolve().parents[2]
PROFILES = Path(os.environ["GROWTH_PROFILES_DIR"])
TURKEY = ("but6-toms", "but6-hens", "converter-toms", "converter-hens",
          "converter-novo-toms", "converter-novo-hens")

# Корпус 120 × 20 = 2400 м²: 6000 индюков — 2.5 гол/м² (< 10, Hybrid по площади)
HOUSE = {"length_m": 120, "width_m": 20, "wall_height_m": 3.0, "ridge_height_m": 5.0}
FLOOR_M2 = 120 * 20
REQ = {
    "house": HOUSE,
    "flock": {"birds": 6000, "growth_profile_id": "but6-toms", "age_days": 140,
              "housing": "floor_litter", "stage": "grow_out"},
    "conditions": {"outdoor_t_c": -10.0, "outdoor_rh_pct": 80.0},
}
DESIGN = {
    "house": HOUSE,
    "envelope": {"walls": {"u_w_m2k": 0.4}, "roof": {"u_w_m2k": 0.25}},
    "flock": {"birds": 6000, "growth_profile_id": "but6-toms", "first_day": 36, "cycle_days": 140,
              "housing": "floor_litter", "mortality_pct": 0, "stage": "grow_out"},
    "climate": {"winter_design_c": -20, "summer_design_db_c": 32, "summer_design_rh_pct": 40},
}


@pytest.fixture(scope="module", autouse=True)
def turkey_profiles():
    copied = []
    for pid in TURKEY:
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


# ─── Закон тепла и CO₂ ───────────────────────────────────────────────────────

def test_turkey_total_heat_is_cigr_eq19_and_broiler_is_unchanged():
    # 20 °C — без температурной поправки: полное тепло равно закону как есть
    assert house_heat_per_bird(20.0, 20.0, "turkey").total_w == pytest.approx(9.86 * 20.0 ** 0.77)
    assert house_heat_per_bird(2.0, 20.0).total_w == pytest.approx(10.62 * 2.0 ** 0.75)


def test_turkey_co2_minimum_uses_turkey_heat():
    # CIGR 1984: 0.153 л CO₂ на Вт·ч, ΔCO₂ 2.6 л/м³, запас 1.5
    expected = 9.86 * 20.0 ** 0.77 * 0.153 / 2.6 * 1.5
    assert calc_q_min_per_bird(20.0, 1.5, "turkey") == pytest.approx(expected, abs=1e-3)


# ─── Профили ─────────────────────────────────────────────────────────────────

def test_profiles_are_what_the_generator_builds():
    # Файлы собираются скриптом из таблиц руководств: правка JSON руками, мимо
    # таблиц со ссылками на страницы, — расхождение, которое этот тест ловит
    spec = importlib.util.spec_from_file_location("btp", ROOT / "scripts/build_turkey_profiles.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for profile in module.build():
        on_disk = json.loads((ROOT / "data/growth_profiles/builtin" / f"{profile['id']}.json").read_text("utf-8"))
        assert on_disk == profile, profile["id"]


def test_profile_days_match_the_guides(client):
    toms = {d["day"]: d for d in client.get("/api/v1/growth-profiles/but6-toms").json()["days"]}
    # B.U.T. 6, 20-я неделя — 21.50 кг; табл. 5: день 7 — 30 °C (34 − 1·4), неделя 2 — 27
    assert toms[140]["weight_g"] == 21500.0
    assert (toms[7]["temp_c"], toms[8]["temp_c"], toms[14]["temp_c"]) == (30.0, 27.0, 27.0)
    assert toms[154]["temp_c"] == 16.0
    hens = {d["day"]: d for d in client.get("/api/v1/growth-profiles/converter-hens").json()["days"]}
    # Converter самки, 18-я неделя — 13.02 кг; таблица самок кончается на 91-м дне (18 °C)
    assert hens[126]["weight_g"] == 13020.0 and hens[126]["temp_c"] == 18.0
    assert hens[1]["temp_c"] == 35.0 and hens[50]["temp_c"] == 19.0


def test_profile_catalog_names_species_and_sex(client):
    data = {p["id"]: p for p in client.get("/api/v1/growth-profiles").json()["data"]}
    assert (data["but6-toms"]["species"], data["but6-toms"]["sex"]) == ("turkey", "male")
    assert data["test-breed"]["species"] == "broiler" and "sex" not in data["test-breed"]


# ─── Норма минвентиляции производителя ───────────────────────────────────────

def test_hybrid_norm_by_area_when_sparse_and_per_head_when_dense():
    # Неделя 3 (дни 15–21): 2.5 гол/м² — по площади, 12.5 гол/м² — на голову
    assert tn.guide_min_vent_m3h(tn.HYBRID_PER_WEEK, 6000, 0.7, 21, 2400) == pytest.approx(1.7 * 3 * 2400)
    assert tn.guide_min_vent_m3h(tn.HYBRID_PER_WEEK, 30000, 0.7, 15, 2400) == pytest.approx(0.17 * 3 * 30000)
    assert tn.guide_min_vent_m3h(tn.AVIAGEN_PER_KG, 1000, 20.0, 140, None) == pytest.approx(20000)


def test_aviagen_norm_sets_qmin_of_heavy_toms(client):
    # 6000 индюков × 21.5 кг × 1 м³/кг·ч = 129 000 м³/ч — больше, чем требует CO₂
    j = _post(client, "/api/v1/ventilation-requirements", REQ)
    assert (j["qmin_basis"], j["qmin_m3h"]) == ("guide", 129000)
    assert {"cigr_2002_turkey", "aviagen_turkey_cl23_min_vent", "aviagen_turkey_cl23_t5"} <= {
        s["id"] for s in j["sources"]}
    assert {"turkey_sensible_from_broiler", "qmin_includes_guide_norm"} <= _codes(j["assumptions"])


def test_guide_stays_the_basis_with_open_flame_heaters(client):
    # Ветка горелок пересчитывает основание Qmin: норма производителя не должна
    # подменяться на «co2», когда она больше CO₂ птицы вместе с CO₂ горелок
    body = _with(REQ, conditions={"outdoor_t_c": -20.0})
    body["envelope"] = {"ua_w_per_k": 3000}
    body["heaters"] = {"type": "gas_open", "power_kw": 100}
    j = _post(client, "/api/v1/ventilation-requirements", body)
    assert (j["qmin_basis"], j["qmin_m3h"]) == ("guide", 129000)


def test_turkey_setpoint_has_no_rh_shift(client):
    # Ни Aviagen, ни Hybrid поправки на RH не дают: уставка дня — таблица как есть
    dry = _post(client, "/api/v1/ventilation-requirements", _with(REQ, flock={"target_rh_pct": 40}))
    wet = _post(client, "/api/v1/ventilation-requirements", _with(REQ, flock={"target_rh_pct": 70}))
    assert dry["target_temp_c"] == wet["target_temp_c"] == 16.0


# ─── Проверки входа ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("patch, code", [
    ({"stage": None}, "turkey_stage_required"),
    ({"housing": "cages"}, "housing_not_for_species"),
    ({"growth_profile_id": "test-breed", "age_days": 30}, "stage_turkey_only"),
    ({"growth_profile_id": "test-breed", "age_days": 90, "stage": None}, "broiler_day_out_of_range"),
])
def test_input_that_makes_no_sense_for_the_species_is_rejected(client, patch, code):
    body = _with(REQ, flock=patch)
    body["flock"] = {k: v for k, v in body["flock"].items() if v is not None}
    if patch.get("housing") == "cages":
        body["house"] = {**HOUSE, "cage_rows": [{"count": 4, "width_m": 1.6, "height_m": 2.2}]}
    r = client.post("/api/v1/ventilation-requirements", json=body)
    assert r.status_code == 422 and r.json()["code"] == code, r.text


def test_broiler_design_still_stops_at_day_63(client):
    body = _with(DESIGN, flock={"growth_profile_id": "test-breed", "first_day": 1, "cycle_days": 70})
    del body["flock"]["stage"]
    r = client.post("/api/v1/ventilation-designs", json=body)
    assert r.status_code == 422 and r.json()["code"] == "broiler_day_out_of_range"


# ─── Проект: доращивание с дня пересадки ─────────────────────────────────────

def test_grow_out_design_starts_at_transfer_day(client):
    j = _post(client, "/api/v1/ventilation-designs", _with(DESIGN, flock={"mortality_pct": 10}))
    days = j["days"]
    assert (days[0]["day"], days[-1]["day"]) == (36, 140)
    # Падёж корпуса — от дня посадки: в день пересадки живы все 6000
    assert days[0]["stocking_density_head_m2"] == pytest.approx(6000 / FLOOR_M2, abs=0.01)
    assert days[-1]["stocking_density_head_m2"] == pytest.approx(0.9 * 6000 / FLOOR_M2, abs=0.01)


def test_turkey_tunnel_and_min_vent_fans_follow_turkey_norms(client):
    eq = _post(client, "/api/v1/ventilation-designs", DESIGN)["equipment"]
    # Тоннель — 2 м/с в сечении: 20 м × средняя высота 4 м
    assert eq["tunnel_fans_basis"] == "air_speed"
    assert eq["tunnel_air_speed_ms"]["max"] == 2.0
    assert eq["tunnel_fans_m3h"]["max"] == round(2.0 * 20 * 4.0 * 3600)
    # Вентиляторы минвентиляции — не меньше 27.5 м³/ч·м² доращивания (Hybrid)
    assert eq["min_vent_fans_m3h"]["source_id"] == "hybrid_turkey_ventcalc"
    assert eq["min_vent_fans_m3h"]["min"] >= 27.5 * FLOOR_M2


def test_turkey_density_warning_in_heads_per_m2(client):
    # 9000 индюков на 2400 м² = 3.75 гол/м² > 3.2 (Aviagen, доращивание самцов)
    j = _post(client, "/api/v1/ventilation-designs", _with(DESIGN, flock={"birds": 9000}))
    note = next(n for n in j["warnings"] if n["code"] == "turkey_density_high")
    assert note["params"]["limit_head_per_m2"] == 3.2 and note["source_id"] == "aviagen_turkey_cl23_density"
    assert "stocking_density_high" not in _codes(j["warnings"])


def test_turkey_tunnel_reports_no_broiler_effective_temperature(client):
    hot = _with(REQ, conditions={"outdoor_t_c": 32.0, "outdoor_rh_pct": 40.0})
    j = _post(client, "/api/v1/ventilation-requirements", hot)
    assert j["tunnel"]["active"] and "effective_temp_c" not in j["tunnel"]
    assert "effective_temp_limit_c" not in j["tunnel"]
    assert "effective_temp_not_for_turkey" in _codes(j["assumptions"])


# ─── Профили в интерфейсе (маршрут /profiles) ────────────────────────────────

def test_ui_profile_route_opens_a_turkey_profile(client):
    # С бройлерными пределами модели (день ≤ 70, масса ≤ 10 кг) ответ падал в 500
    r = client.get("/profiles/but6-toms")
    assert r.status_code == 200, r.text
    j = r.json()
    assert (j["species"], j["sex"], j["last_day"]) == ("turkey", "male", 154)
    assert j["days"][-1]["body_weight_g"] == 23880.0


def test_custom_copy_of_a_turkey_stays_a_turkey(client):
    src = client.get("/profiles/converter-toms").json()
    body = {"name": "Мои индюки", "species": "turkey", "sex": "male", "min_vent_norm": src["min_vent_norm"],
            "mixed_temps": src["mixed_temps"],
            "points": [{k: p[k] for k in ("day", "body_weight_g", "min_temp_c", "rv_percent")}
                       for p in src["points"]]}
    assert client.put("/profiles/my-toms", json=body).status_code == 200
    try:
        mine = _post(client, "/api/v1/ventilation-requirements", _with(REQ, flock={"growth_profile_id": "my-toms"}))
        theirs = _post(client, "/api/v1/ventilation-requirements", _with(REQ, flock={"growth_profile_id": "converter-toms"}))
        # Тот же закон тепла и та же норма Hybrid — те же числа, что у встроенного кросса
        assert (mine["qmin_m3h"], mine["qmin_basis"]) == (theirs["qmin_m3h"], theirs["qmin_basis"])
        assert "cigr_2002_turkey" in {s["id"] for s in mine["sources"]}
        # Смешанное стадо по копии — та же таблица смешанных стад Hybrid
        mixed = {"hens": {"growth_profile_id": "converter-hens", "birds": 6000}, "age_days": 22}
        a = _post(client, "/api/v1/ventilation-requirements", _with(REQ, flock={"growth_profile_id": "my-toms", **mixed}))
        assert a["target_temp_c"] == 26.0
    finally:
        client.delete("/profiles/my-toms")


def test_turkey_norm_on_a_broiler_profile_is_rejected(client):
    body = {"name": "x", "min_vent_norm": "aviagen_turkey_per_kg",
            "points": [{"day": 0, "body_weight_g": 42, "min_temp_c": 33}, {"day": 42, "body_weight_g": 3000, "min_temp_c": 20}]}
    r = client.put("/profiles/broiler-with-norm", json=body)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "profile_norm_turkey_only", r.text


# ─── Смешанное стадо ─────────────────────────────────────────────────────────

MIXED_REQ = _with(REQ, flock={"growth_profile_id": "but6-toms", "age_days": 70, "birds": 3000,
                              "hens": {"growth_profile_id": "but6-hens", "birds": 3000}})


def test_mixed_flock_guide_is_the_sum_over_sexes(client):
    # Aviagen 1 м³/кг·ч: 3000 × 7.60 кг (индюки, 10-я неделя) + 3000 × 5.71 кг (индюшки)
    j = _post(client, "/api/v1/ventilation-requirements", MIXED_REQ)
    assert (j["qmin_basis"], j["qmin_m3h"]) == ("guide", round(3000 * 7.60 + 3000 * 5.71))
    assert j["weight_g"] == pytest.approx((7600 + 5710) / 2)
    assert "mixed_flock_average_bird" in _codes(j["assumptions"])


def test_mixed_flock_heat_counts_both_sexes(client):
    # Qmax по тепловому балансу без ограждений (UA = 0) пропорционален явному теплу
    # корпуса, а уставка B.U.T. 6 общая для M+F: максимум смешанного стада равен сумме
    # максимумов индюков и индюшек по отдельности. 10 °C снаружи — баланс, не туннель
    mild = {"outdoor_t_c": 10.0, "outdoor_rh_pct": 50.0}
    toms = _post(client, "/api/v1/ventilation-requirements",
                 _with(REQ, flock={"age_days": 70, "birds": 3000}, conditions=mild))
    hens = _post(client, "/api/v1/ventilation-requirements",
                 _with(REQ, flock={"growth_profile_id": "but6-hens", "age_days": 70, "birds": 3000},
                       conditions=mild))
    mixed = _post(client, "/api/v1/ventilation-requirements", _with(MIXED_REQ, conditions=mild))
    assert not mixed["tunnel"]["active"]
    assert mixed["qmax_m3h"] == pytest.approx(toms["qmax_m3h"] + hens["qmax_m3h"], abs=2)


def test_mixed_hybrid_flock_uses_the_mixed_table_until_removal(client):
    # Hybrid с. 57: смешанное стадо 22–28 сут — 26 °C (у индюков 25); с. 56 после выборки
    body = _with(DESIGN, flock={"growth_profile_id": "converter-toms", "first_day": 1, "cycle_days": 140,
                                "stage": "grow_out", "hens": {"growth_profile_id": "converter-hens",
                                                              "birds": 6000, "removal_day": 98}})
    days = {d["day"]: d for d in _post(client, "/api/v1/ventilation-designs", body)["days"]}
    assert days[22]["target_temp_c"] == 26.0 and days[98]["target_temp_c"] == 16.0
    # День 99: индюшек нет — таблица самцов (> 99 — 14 °C), плотность вдвое ниже
    assert days[99]["target_temp_c"] == 14.0
    assert days[99]["stocking_density_head_m2"] == pytest.approx(days[98]["stocking_density_head_m2"] / 2, abs=0.01)


def test_mixed_grow_out_says_there_is_no_density_limit(client):
    body = _with(DESIGN, flock={"birds": 9000, "hens": {"growth_profile_id": "but6-hens", "birds": 9000}})
    j = _post(client, "/api/v1/ventilation-designs", body)
    assert "turkey_density_high" not in _codes(j["warnings"])
    assert "turkey_density_no_limit" in _codes(j["assumptions"])


@pytest.mark.parametrize("hens, code", [
    ({"growth_profile_id": "converter-hens", "birds": 100}, "mixed_flock_mismatch"),
    ({"growth_profile_id": "but6-toms", "birds": 100}, "mixed_flock_mismatch"),
    ({"growth_profile_id": "but6-hens", "birds": 100, "removal_day": 20}, "hens_removal_out_of_range"),
])
def test_mixed_flock_input_is_checked(client, hens, code):
    r = client.post("/api/v1/ventilation-designs", json=_with(DESIGN, flock={"hens": hens}))
    assert r.status_code == 422 and r.json()["code"] == code, r.text


def test_mixed_flock_co2_is_the_weighted_mean_per_bird():
    # CO₂ (CIGR 1984) линеен по головам: на голову смешанного стада — средневзвешенное
    # по полам. В API это не видно — там правят норма или влага, поэтому — ядро
    from backend.app.core.calc_core import CalcInput, CalcParams, FlockGroup, HouseThermal, compute_with
    params, thermal = CalcParams(total_mortality_pct=0.0, cycle_days=154), HouseThermal()
    mixed = compute_with(CalcInput(birds=4000, age_days=98, outside_t=-10, growth_profile_id="converter-toms",
                                   companion=FlockGroup("converter-hens", 2000)), params, thermal)
    toms = compute_with(CalcInput(birds=4000, age_days=98, outside_t=-10, growth_profile_id="converter-toms"),
                        params, thermal)
    hens = compute_with(CalcInput(birds=2000, age_days=98, outside_t=-10, growth_profile_id="converter-hens"),
                        params, thermal)
    expected = (4000 * toms.rates_per_bird_min + 2000 * hens.rates_per_bird_min) / 6000
    assert mixed.rates_per_bird_min == pytest.approx(expected)
    assert (mixed.birds_alive, mixed.companion_alive) == (6000, 2000)
