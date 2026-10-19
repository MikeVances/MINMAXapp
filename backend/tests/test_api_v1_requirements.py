"""
API v1, POST /api/v1/ventilation-requirements — потребность «сейчас» (этап 4).

Профиль — синтетический test-breed из conftest: день 21 — 1012 г, уставка 25 °C,
RH 60 %. Опорное число — эталон test_calc_core_golden: 10 000 голов, день 21,
сухой воздух снаружи → Qmin по CO₂ = 10 000 × 0.9458 ≈ 9 458 м³/ч.
"""
from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path

import pytest

URL = "/api/v1/ventilation-requirements"
CFG_PATH = Path(os.environ["APP_CONFIG_JSON"])

REQ = {
    "house": {"length_m": 120, "width_m": 16, "wall_height_m": 2.5, "ridge_height_m": 4.5},
    "flock": {"birds": 10_000, "growth_profile_id": "test-breed", "age_days": 21, "housing": "floor_litter"},
    # 25 °C / 5 %: влажностный Qmin заведомо ниже CO₂ — правит норма CO₂
    "conditions": {"outdoor_t_c": 25.0, "outdoor_rh_pct": 5.0},
}
QMIN_CO2_D21 = 10_000 * 0.9458
GAS_300_DILUTION = 300 / 100 * 10 * 1000 / 2.6 * 1.5     # CO₂ горелок 300 кВт на 100 %


def _req(**patch) -> dict:
    r = deepcopy(REQ)
    for part, values in patch.items():
        if isinstance(values, dict) and isinstance(r.get(part), dict):
            r[part].update(values)
        else:
            r[part] = values
    return r


def _codes(notes) -> set:
    return {n["code"] for n in notes}


def test_response_has_contract_fields(client):
    r = client.post(URL, json=REQ)
    assert r.status_code == 201 and r.headers["cache-control"] == "no-store"
    j = r.json()
    for key in ("qmin_m3h", "qmin_basis", "qmax_m3h", "target_temp_c", "tunnel", "findings",
                "assumptions", "sources", "api_version", "app_version"):
        assert key in j, key
    for key in ("allowed", "active", "target_speed_ms", "free_section_m2", "effective_temp_limit_c"):
        assert key in j["tunnel"], key
    # Без ограждений — без теплового баланса
    assert "heating_need_kw" not in j and "heater_duty_pct" not in j


def test_birds_are_the_current_headcount(client):
    # Падёж не применяется: число голов уже текущее. С падежом 4 % за 42 дня на
    # 21-й день осталось бы 98 % — Qmin был бы ≈ 9 270
    j = client.post(URL, json=REQ).json()
    assert j["qmin_basis"] == "co2"
    assert j["qmin_m3h"] == pytest.approx(QMIN_CO2_D21, abs=5)
    assert j["target_temp_c"] == pytest.approx(25.0, abs=0.01)


@pytest.mark.parametrize("patch, field", [
    ({"flock": {"mortality_pct": 4}}, "flock.mortality_pct"),
    ({"conditions": {"target_rh_pct": 60}}, "conditions.target_rh_pct"),   # целевая RH — во flock
    ({"flock": {"cycle_days": 42}}, "flock.cycle_days"),
])
def test_fields_of_the_design_scenario_are_rejected(client, patch, field):
    r = client.post(URL, json=_req(**patch))
    assert r.status_code == 422 and r.json()["code"] == "validation_failed"
    assert field in {e["field"] for e in r.json()["errors"]}


# ─── Горелки ──────────────────────────────────────────────────────────────────

GAS = {"type": "gas_open", "power_kw": 300}


def test_heaters_are_off_when_it_is_warm(client):
    # Снаружи 30 °C при уставке 25: горелки не горят — их CO₂ в Qmin не попадает
    warm = {"outdoor_t_c": 30.0, "outdoor_rh_pct": 5.0}
    without = client.post(URL, json=_req(conditions=warm)).json()
    with_gas = client.post(URL, json={**_req(conditions=warm), "heaters": GAS}).json()
    assert with_gas["qmin_m3h"] == without["qmin_m3h"]
    assert "heater_load_unknown" not in _codes(with_gas["findings"])


def test_cold_without_envelope_assumes_full_duty(client):
    # Загрузку без UA не найти: CO₂ горелок берём при 100 % — оценка сверху
    cold = {"outdoor_t_c": -5.0, "outdoor_rh_pct": 5.0}
    j = client.post(URL, json={**_req(conditions=cold), "heaters": GAS}).json()
    assert {"code": "heater_load_unknown", "severity": "info"} in j["findings"]
    assert j["qmin_m3h"] == pytest.approx(QMIN_CO2_D21 + GAS_300_DILUTION, abs=5)


def test_heating_with_envelope(client):
    cold = {"outdoor_t_c": -12.0, "outdoor_rh_pct": 85.0}
    body = {**_req(conditions=cold), "envelope": {"ua_w_per_k": 3200}, "heaters": {"type": "electric", "power_kw": 400}}
    j = client.post(URL, json=body).json()
    assert j["heating_need_kw"] > 0
    assert 0 < j["heater_duty_pct"] < 100
    assert j["heater_duty_pct"] == pytest.approx(100 * j["heating_need_kw"] / 400, abs=0.2)
    assert j["air_exchange_m3h"] >= j["qmin_m3h"]
    small = client.post(URL, json={**body, "heaters": {"type": "electric", "power_kw": 20}}).json()
    f = [x for x in small["findings"] if x["code"] == "heater_insufficient"]
    assert f and f[0]["severity"] == "critical" and f[0]["params"]["need_kw"] > 20


def test_condensation_with_measured_ua(client):
    # UA 20 000 Вт/К на 2 690 м² — U ≈ 7.4, как голый профлист: стены ледяные
    body = {**_req(conditions={"outdoor_t_c": -15.0, "outdoor_rh_pct": 80.0}), "envelope": {"ua_w_per_k": 20_000}}
    f = [x for x in client.post(URL, json=body).json()["findings"] if x["code"] == "condensation_risk"]
    assert f and f[0]["params"]["surface"] == "envelope_mean"
    assert f[0]["params"]["surface_c"] < f[0]["params"]["dew_point_c"]


# ─── Туннель ──────────────────────────────────────────────────────────────────

def test_young_birds_cap_the_tunnel_speed(client):
    # Cobb §9.7: 5–14 дней — не больше 0.5 м/с у птицы
    hot10 = {"flock": {"age_days": 10}, "conditions": {"outdoor_t_c": 33.0, "outdoor_rh_pct": 30.0}}
    floor = client.post(URL, json=_req(**hot10)).json()["tunnel"]
    assert floor["target_speed_ms"]["max"] == 0.5 and floor["allowed"] is False
    # Клетки: у птицы — половина скорости в проходах, значит проход до 1.0
    rows = [{"count": 4, "width_m": 1.6, "height_m": 2.2}]
    cages = client.post(URL, json=_req(flock={"age_days": 10, "housing": "cages"},
                                       house={"cage_rows": rows},
                                       conditions=hot10["conditions"])).json()["tunnel"]
    assert cages["target_speed_ms"]["max"] == 1.0 and cages["bird_speed_ms"]["max"] == 0.5


def test_hot_young_flock_explains_why_no_tunnel(client):
    j = client.post(URL, json=_req(flock={"age_days": 10}, conditions={"outdoor_t_c": 33.0, "outdoor_rh_pct": 30.0})).json()
    assert {"code": "tunnel_not_allowed_age", "params": {"min_day": 21}, "severity": "info"} in j["findings"]


def test_effective_temperature_in_tunnel(client):
    hot = {"flock": {"age_days": 35}, "conditions": {"outdoor_t_c": 32.0, "outdoor_rh_pct": 40.0}}
    floor = client.post(URL, json=_req(**hot)).json()
    assert floor["tunnel"]["active"] is True
    assert "effective_temp_c" in floor["tunnel"]
    assert "effective_temp_table" in {s["id"] for s in floor["sources"]}


def test_cage_age_limit_applies_to_bird_speed_not_aisle(client):
    # День 18: Cobb — до 1.8 м/с у ПТИЦЫ. В клетках у птицы половина скорости прохода,
    # значит проход до 3.6 м/с, а расход = 3.6 × 41.92 × 3600 ≈ 543 283 м³/ч.
    # Раньше предел ложился на проход: 1.8 м/с и вдвое меньше воздуха
    # Туннель с 14-го дня — площадка задала свои правила (по умолчанию — с 21-го)
    rows = [{"count": 4, "width_m": 1.6, "height_m": 2.2}]
    body = _req(flock={"age_days": 18, "housing": "cages"}, house={"cage_rows": rows},
                conditions={"outdoor_t_c": 32.0, "outdoor_rh_pct": 40.0})
    j = client.post(URL, json={**body, "tunnel_rules": {"min_day": 14, "min_outdoor_c": 18}}).json()
    free = 56.0 - 4 * 1.6 * 2.2
    assert j["tunnel"]["active"] is True
    assert j["tunnel"]["bird_speed_ms"]["max"] == 1.8
    assert j["qmax_m3h"] == pytest.approx(3.6 * free * 3600, abs=2)


def test_tunnel_rules_default_to_farmers_practice(client):
    # Практика птицеводов (владелец, 2026-10-19): с 21-го дня, снаружи не ниже 24 °C
    j = client.post(URL, json=REQ).json()
    assert {"code": "tunnel_rules_default", "params": {"min_day": 21, "min_temp_c": 24.0},
            "source_id": "practice_tunnel_rules_2026"} in j["assumptions"]
    assert "practice_tunnel_rules_2026" in {s["id"] for s in j["sources"]}


@pytest.mark.parametrize("age, t_out, allowed", [
    (20, 32.0, False),     # моложе 21 дня
    (21, 32.0, True),
    (30, 23.0, False),     # снаружи ниже 24 °C
    (30, 24.0, True),
])
def test_tunnel_allowed_by_default_rules(client, age, t_out, allowed):
    j = client.post(URL, json=_req(flock={"age_days": age}, conditions={"outdoor_t_c": t_out, "outdoor_rh_pct": 40.0})).json()
    assert j["tunnel"]["allowed"] is allowed


def test_request_tunnel_rules_override_defaults(client):
    body = _req(flock={"age_days": 16}, conditions={"outdoor_t_c": 20.0, "outdoor_rh_pct": 40.0})
    assert client.post(URL, json=body).json()["tunnel"]["allowed"] is False
    j = client.post(URL, json={**body, "tunnel_rules": {"min_day": 14, "min_outdoor_c": 18}}).json()
    assert j["tunnel"]["allowed"] is True
    assert "tunnel_rules_default" not in {a["code"] for a in j["assumptions"]}


# ─── Без состояния и ошибки ───────────────────────────────────────────────────

@pytest.fixture
def restore_config():
    before = CFG_PATH.read_bytes()
    yield
    CFG_PATH.write_bytes(before)


def test_saved_farm_settings_do_not_leak(client, restore_config):
    base = client.post(URL, json=REQ).json()
    cfg = json.loads(CFG_PATH.read_text())
    cfg.update(altitude_m=2000, total_mortality_pct=50, safety_factor_qmin=3.0, tunnel_min_day=5)
    CFG_PATH.write_text(json.dumps(cfg))
    after = client.post(URL, json=REQ).json()
    for key in ("qmin_m3h", "qmax_m3h", "target_temp_c", "tunnel"):
        assert after[key] == base[key], key


def test_cages_need_rows(client):
    r = client.post(URL, json=_req(flock={"housing": "cages"}))
    assert r.status_code == 422 and r.json()["code"] == "cage_section_missing"


def test_unknown_profile(client):
    r = client.post(URL, json=_req(flock={"growth_profile_id": "ross999"}))
    assert r.status_code == 404 and r.headers["content-type"].startswith("application/problem+json")


def test_cage_qmax_uses_animal_level_heat_in_mild_weather(client):
    # 18 °C снаружи, день 9: Qmax задаёт тепловой баланс. У клеток явное тепло —
    # уровня птицы (0.67 полного, Aarnink 2018), у подстилки — уровня корпуса: воздуха больше
    mild = {"outdoor_t_c": 18.0, "outdoor_rh_pct": 50.0}
    rows = [{"count": 4, "width_m": 1.6, "height_m": 2.2}]
    floor = client.post(URL, json=_req(flock={"age_days": 9}, conditions=mild)).json()
    cages = client.post(URL, json=_req(flock={"age_days": 9, "housing": "cages"}, house={"cage_rows": rows},
                                       conditions=mild)).json()
    assert cages["qmax_m3h"] > 1.3 * floor["qmax_m3h"]
    # Qmin — уровня корпуса у обоих
    assert cages["qmin_m3h"] == floor["qmin_m3h"]
