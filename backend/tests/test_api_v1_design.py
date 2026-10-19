"""
API v1, POST /api/v1/ventilation-designs и справочники (этап 3a).

Ожидаемые числа посчитаны руками по формулам контракта (docs/api/v1/README.md),
а не вызовом модуля. Профиль — синтетический test-breed из conftest (дни 1–42).
"""
from __future__ import annotations

import json
import math
import os
from copy import deepcopy
from pathlib import Path

import pytest

from backend.app.core import calc_core, psychro

CFG_PATH = Path(os.environ["APP_CONFIG_JSON"])
URL = "/api/v1/ventilation-designs"

PANEL_100 = {"layers": [{"material_id": "steel", "thickness_mm": 0.5},
                        {"material_id": "pir_core", "thickness_mm": 100},
                        {"material_id": "steel", "thickness_mm": 0.5}]}
REQ = {
    "house": {"length_m": 120, "width_m": 16, "wall_height_m": 2.5, "ridge_height_m": 4.5},
    "envelope": {"walls": PANEL_100, "roof": {"u_w_m2k": 0.21}},
    "flock": {"birds": 30000, "growth_profile_id": "test-breed", "cycle_days": 42, "housing": "floor_litter"},
    "climate": {"winter_design_c": -9.8, "summer_design_db_c": 35.6, "summer_design_rh_pct": 28},
}

# Геометрия REQ руками: пол 1920 м², сечение 16 × (2.5 + 4.5)/2 = 56 м², объём 6720 м³
FLOOR_M2, SECTION_M2, VOLUME_M3 = 1920.0, 56.0, 6720.0


def _req(**patch) -> dict:
    """Копия REQ с заменой вложенных частей: _req(house={"altitude_m": 500})."""
    r = deepcopy(REQ)
    for part, values in patch.items():
        if isinstance(values, dict) and isinstance(r.get(part), dict):
            r[part].update(values)
        else:
            r[part] = values
    return r


def _codes(notes) -> set:
    return {n["code"] for n in notes}


@pytest.fixture
def restore_config():
    before = CFG_PATH.read_bytes()
    yield
    CFG_PATH.write_bytes(before)


# ─── Ответ по контракту ───────────────────────────────────────────────────────

def test_design_response_has_contract_fields(client):
    r = client.post(URL, json=REQ)
    assert r.status_code == 201
    assert r.headers["cache-control"] == "no-store"
    j = r.json()
    for key in ("envelope_ua_w_per_k", "days", "peak", "equipment", "warnings",
                "assumptions", "sources", "api_version", "app_version"):
        assert key in j, key
    assert [d["day"] for d in j["days"]] == list(range(1, 43))
    for key in ("day", "weight_g", "target_temp_c", "qmin_m3h", "qmin_basis", "qmax_m3h",
                "heating_need_kw", "air_exchange_m3h", "air_exchange_basis"):
        assert key in j["days"][0], key
    for key in ("min_vent_fans_m3h", "tunnel_fans_m3h", "heating_kw"):
        assert key in j["equipment"], key
    # Каждый source_id из ответа расшифрован в sources
    cited = {s["id"] for s in j["sources"]}
    used = {v["source_id"] for v in j["equipment"].values() if isinstance(v, dict)}
    assert used <= cited


def test_envelope_ua_by_layers_by_hand(client):
    u_wall = 1 / (0.13 + 2 * 0.0005 / 50 + 0.100 / 0.022 + 0.04)
    side, ends = 2 * 120 * 2.5, 2 * (16 * 2.5 + 8 * 2.0)
    roof = 2 * 120 * math.hypot(8, 2.0)
    ua = u_wall * (side + ends) + 0.21 * roof
    assert client.post(URL, json=REQ).json()["envelope_ua_w_per_k"] == pytest.approx(ua, abs=0.1)


def test_tunnel_takes_larger_of_cobb_area_and_air_exchange(client):
    # Cobb §9.7: 165–200 м³/ч·м² → 316 800 – 384 000; смена воздуха 50–40 с →
    # 483 840 – 604 800. Корпус без потолка: решает смена воздуха
    eq = client.post(URL, json=REQ).json()["equipment"]
    assert eq["tunnel_fans_m3h"]["min"] == round(VOLUME_M3 * 3600 / 50)
    assert eq["tunnel_fans_m3h"]["max"] == round(VOLUME_M3 * 3600 / 40)
    assert eq["tunnel_air_speed_ms"]["min"] == pytest.approx(2.4, abs=0.01)
    assert eq["tunnel_air_speed_ms"]["max"] == pytest.approx(3.0, abs=0.01)


def test_flat_house_with_low_ceiling_uses_cobb_area_norm(client):
    # Сечение 16 × 2.5 = 40 м², объём 4800: смена за 40 с = 432 000 > 200 м³/ч·м² = 384 000
    # — всё равно решает объём; а при стене 2.0 м (3840 м³): 345 600 < 384 000 — площадь
    j = client.post(URL, json=_req(house={"wall_height_m": 2.0, "ridge_height_m": None})).json()
    assert j["equipment"]["tunnel_fans_m3h"]["max"] == round(200 * FLOOR_M2)


def test_heating_margin_is_applied_to_equipment_only(client):
    j = client.post(URL, json=REQ).json()
    peak = j["peak"]["heating_kw"]
    assert j["equipment"]["heating_kw"] == pytest.approx(peak * 1.15, abs=0.1)
    assert max(d["heating_need_kw"] for d in j["days"]) == peak
    zero = client.post(URL, json={**REQ, "heating_margin_pct": 0}).json()
    assert zero["equipment"]["heating_kw"] == pytest.approx(zero["peak"]["heating_kw"], abs=0.05)
    # Дни — потребность без запаса: от запаса они не зависят
    assert [d["heating_need_kw"] for d in zero["days"]] == [d["heating_need_kw"] for d in j["days"]]


# ─── Утечки ───────────────────────────────────────────────────────────────────

def test_default_airtightness_is_moderate_upper_bound(client):
    # ELA = 0.65 × 1920 / 1000 = 1.248 м²; Q = 1.248 · √(2·4/1.184) · 3600 ≈ 11 678 м³/ч
    q4 = 0.65 * FLOOR_M2 / 1000 * math.sqrt(8 / 1.184) * 3600
    j = client.post(URL, json=REQ).json()
    assert "airtightness_class_assumed" in _codes(j["assumptions"])
    day1 = j["days"][0]
    assert day1["air_exchange_basis"] == "leakage"
    assert day1["air_exchange_m3h"] == pytest.approx(q4, abs=1)


def test_leakage_is_not_added_to_qmin(client):
    # Утечка — пол обмена для обогрева, а не прибавка к Qmin
    tight = client.post(URL, json=_req(house={"airtightness": {"class": "tight"}})).json()
    leaky = client.post(URL, json=_req(house={"airtightness": {"class": "very_leaky"}})).json()
    assert [d["qmin_m3h"] for d in tight["days"]] == [d["qmin_m3h"] for d in leaky["days"]]
    # В первый день греть приходится воздух щелей — у негерметичного больше
    assert leaky["days"][0]["heating_need_kw"] > tight["days"][0]["heating_need_kw"]
    # В конце цикла Qmin больше любой утечки — обогрев одинаковый
    assert leaky["days"][-1]["heating_need_kw"] == tight["days"][-1]["heating_need_kw"]
    assert "airtightness_class_assumed" not in _codes(tight["assumptions"])


def test_measured_leak_is_used_as_is(client):
    j = client.post(URL, json=_req(house={"airtightness": {"leak_at_4pa_m3h": 50_000}})).json()
    assert j["days"][0]["air_exchange_m3h"] == 50_000
    assert "leakage_exceeds_min_vent" in _codes(j["warnings"])


# ─── Без состояния ────────────────────────────────────────────────────────────

def test_saved_farm_settings_do_not_leak_into_design(client, restore_config, monkeypatch):
    """
    Главное свойство v1: тот же запрос — тот же ответ на любой площадке. Меняем
    сохранённые настройки хозяйства (высота, падёж, скорость туннеля) — ответ не
    должен сдвинуться; сохранённую теплотехнику корпуса API не должен даже читать.
    """
    base = client.post(URL, json=REQ).json()

    cfg = json.loads(CFG_PATH.read_text())
    cfg.update(altitude_m=2000, total_mortality_pct=50, v_tunnel_ms=9.0, safety_factor_qmin=3.0,
               cycle_days=21, tunnel_min_day=5)
    CFG_PATH.write_text(json.dumps(cfg))

    def no_saved_thermal(*a, **k):
        raise AssertionError("API v1 прочитал сохранённую теплотехнику корпуса")
    monkeypatch.setattr(calc_core, "load_thermal_config", no_saved_thermal)

    after = client.post(URL, json=REQ).json()
    for key in ("days", "peak", "equipment", "envelope_ua_w_per_k"):
        assert after[key] == base[key], key


def test_request_altitude_is_used_and_released(client):
    sea = client.post(URL, json=REQ).json()
    high = client.post(URL, json=_req(house={"altitude_m": 2000})).json()
    # На 2000 м воздух реже на 21.5 %: тот же объём уносит меньше тепла
    assert high["peak"]["heating_kw"] < sea["peak"]["heating_kw"]
    assert "site_pressure_from_altitude" in _codes(high["assumptions"])
    # Давление запроса не осталось висеть после ответа — интерфейс снова на своём
    assert psychro.site_pressure_pa() == pytest.approx(psychro.pressure_at_altitude_pa(0.0))


# ─── Клетки ───────────────────────────────────────────────────────────────────

CAGES = {"housing": "cages"}
ROWS = [{"count": 4, "width_m": 1.6, "height_m": 2.2}]


def test_cage_tunnel_by_free_section(client):
    # Свободное сечение = 56 − 4·1.6·2.2 = 41.92 м²; 4–5 м/с в проходах
    j = client.post(URL, json=_req(flock=CAGES, house={"cage_rows": ROWS})).json()
    free = SECTION_M2 - 4 * 1.6 * 2.2
    assert j["equipment"]["tunnel_free_section_m2"] == pytest.approx(free, abs=0.01)
    assert j["equipment"]["tunnel_fans_m3h"]["min"] == round(4 * free * 3600)
    assert j["equipment"]["tunnel_fans_m3h"]["max"] == round(5 * free * 3600)
    assert {"cages_heat_split_bounded", "cages_bird_speed_from_aisle",
            "cage_through_flow_not_included"} <= _codes(j["assumptions"])


def test_cage_heat_split_takes_worst_side_per_quantity(client):
    floor = client.post(URL, json=REQ).json()
    cages = client.post(URL, json=_req(flock=CAGES, house={"cage_rows": ROWS})).json()
    # Зима — как подстилка (уровень корпуса: меньше явного тепла, больше пара)
    assert [d["heating_need_kw"] for d in cages["days"]] == [d["heating_need_kw"] for d in floor["days"]]
    assert [d["qmin_m3h"] for d in cages["days"]] == [d["qmin_m3h"] for d in floor["days"]]

    # Лето: явное тепло на уровне птицы (0.67) — больше воздуха. Проявляется, только
    # пока снаружи прохладнее уставки и Qmax задаёт тепловой баланс: при 18 °C в день 9
    # подстилка ≈ 14.9 тыс., клетки ≈ 22.0 тыс. м³/ч. При 35.6 °C баланс вырождается
    # (снаружи жарче), и Qmax одинаков — его задаёт потолок режима
    mild = {"summer_design_db_c": 18.0}
    floor_mild = client.post(URL, json=_req(climate=mild)).json()["days"][8]
    cages_mild = client.post(URL, json=_req(climate=mild, flock=CAGES, house={"cage_rows": ROWS})).json()["days"][8]
    assert cages_mild["qmax_m3h"] > 1.3 * floor_mild["qmax_m3h"]
    assert cages["days"][8]["qmax_m3h"] == floor["days"][8]["qmax_m3h"]


@pytest.mark.parametrize("house, code", [
    ({}, "cage_section_missing"),
    ({"cage_rows": [{"width_m": 1.6, "height_m": 3.0}]}, "cage_section_implausible"),   # выше стены
    ({"cage_rows": [{"count": 10, "width_m": 1.8, "height_m": 2.0}]}, "cage_section_implausible"),  # 18 м > 16
    # Плоская кровля: сечение 40 м², батареи 6·2.4·2.45 = 35.3 → свободно 11.8 % < 15 %
    ({"ridge_height_m": None, "cage_rows": [{"count": 6, "width_m": 2.4, "height_m": 2.45}]},
     "cage_section_implausible"),
])
def test_cage_section_errors(client, house, code):
    r = client.post(URL, json=_req(flock=CAGES, house=house))
    assert r.status_code == 422
    assert r.json()["code"] == code


# ─── Находки ──────────────────────────────────────────────────────────────────

def test_small_heater_is_insufficient(client):
    j = client.post(URL, json={**REQ, "heaters": {"type": "gas_open", "power_kw": 50}}).json()
    assert j["heaters_sufficient"] is False
    assert "heater_insufficient" in _codes(j["warnings"])
    assert "heating_without_combustion_products" not in _codes(j["assumptions"])


def test_bare_brick_wall_condenses(client):
    brick = {"layers": [{"material_id": "brick_exposed", "thickness_mm": 250}]}
    j = client.post(URL, json=_req(envelope={"walls": brick, "roof": brick})).json()
    cond = [w for w in j["warnings"] if w["code"] == "condensation_risk"]
    assert cond and cond[0]["params"]["surface_c"] < cond[0]["params"]["dew_point_c"]


def test_cycle_beyond_profile(client):
    j = client.post(URL, json=_req(flock={"cycle_days": 49})).json()
    assert {"code": "cycle_beyond_profile", "params": {"last_day": 42}, "severity": "info"} in j["warnings"]


# ─── Ошибки: RFC 7807 ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("body, status, code", [
    (_req(flock={"growth_profile_id": "ross999"}), 404, "profile_not_found"),
    (_req(envelope={"walls": {"layers": [{"material_id": "unobtainium", "thickness_mm": 10}]},
                    "roof": {"u_w_m2k": 0.2}}), 404, "material_not_found"),
    (_req(envelope={"walls": {"layers": [{"material_id": "pir_core", "thickness_mm": 1000}]},
                    "roof": {"layers": [{"material_id": "pir_core", "thickness_mm": 1000}]}}),
     422, "envelope_implausible"),
    (_req(envelope={"ua_w_per_k": 500, "walls": PANEL_100, "roof": {"u_w_m2k": 0.2}}), 422, "validation_failed"),
    (_req(house={"wall_heigth_m": 2.0}), 422, "validation_failed"),
])
def test_errors_are_problem_json(client, body, status, code):
    r = client.post(URL, json=body)
    assert r.status_code == status
    assert r.headers["content-type"].startswith("application/problem+json")
    j = r.json()
    assert j["code"] == code and j["status"] == status
    assert j["type"].endswith(f"errors.md#{code}")


def test_field_errors_point_into_request(client):
    j = client.post(URL, json=_req(house={"wall_heigth_m": 2.0})).json()
    assert "house.wall_heigth_m" in {e["field"] for e in j["errors"]}


def test_malformed_json_is_bad_request(client):
    r = client.post(URL, content=b"{not json", headers={"content-type": "application/json"})
    assert r.status_code == 400 and r.json()["code"] == "bad_request"


def test_ui_api_error_format_is_unchanged(client):
    # Обработчики v1 живут в подприложении — ответы интерфейса прежние ({"detail": …})
    r = client.get("/profiles/ross999")
    assert r.status_code == 404
    assert r.json() == {"detail": "profile_not_found"} or "detail" in r.json()
    assert not r.headers["content-type"].startswith("application/problem+json")


# ─── Справочники ──────────────────────────────────────────────────────────────

def test_catalogs(client):
    mats = client.get("/api/v1/construction-materials")
    assert mats.status_code == 200 and "max-age" in mats.headers["cache-control"]
    ids = {m["id"] for m in mats.json()["data"]}
    assert {"pir_core", "brick_exposed", "concrete_reinforced", "timber_softwood"} <= ids
    profiles = client.get("/api/v1/growth-profiles").json()["data"]
    assert {"id": "test-breed", "name": "Тестовый кросс", "breed": "Test", "builtin": True,
            "first_day": 1, "last_day": 42} in profiles
    housing = client.get("/api/v1/housing-systems").json()["data"]
    assert {h["id"] for h in housing} == {"floor_litter", "cages"}
