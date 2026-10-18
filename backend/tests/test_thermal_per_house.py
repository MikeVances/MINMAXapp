"""
Теплотехника ПО КОРПУСАМ (аудит 2026-10-18, [~] «калибровка одна на ферму»).

Раньше thermal_config.json — один объект: калибровка второго корпуса затирала
первую, горелка была одна на всех, а «Сохранить горелки» писал её корпусу из
файла, а не выбранному. Теперь {"houses": {id: {...}}}; старый файл читается.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.app.core.building_thermal import (
    THERMAL_CONFIG_PATH, load_thermal_config, load_thermal_store,
)
from backend.app.core.calc_core import CalcInput, compute

DIMS = {"length_m": 100, "width_m": 16, "height_m": 3.25}


@pytest.fixture
def thermal_path():
    path = Path(THERMAL_CONFIG_PATH)
    path.unlink(missing_ok=True)
    yield path
    path.unlink(missing_ok=True)


def test_old_single_object_file_becomes_its_house_record(thermal_path):
    thermal_path.write_text(json.dumps({"house_id": "1", "building": DIMS,
                                        "heater": {"heater_type": "gas_open", "total_power_kw": 200}}))
    assert set(load_thermal_store()) == {"1"}
    assert load_thermal_config(house_id="1").heater.total_power_kw == 200
    assert load_thermal_config(house_id="2").heater is None


def test_saving_one_house_keeps_the_others(client, thermal_path):
    for hid, kw in (("A", 300), ("B", 100)):
        r = client.put("/thermal/config", json={"house_id": hid, "building": DIMS,
                                                "heater": {"heater_type": "gas_open", "total_power_kw": kw}})
        assert r.status_code == 200
    a = client.get("/thermal/config", params={"house_id": "A"}).json()
    b = client.get("/thermal/config", params={"house_id": "B"}).json()
    assert a["heater"]["total_power_kw"] == 300 and b["heater"]["total_power_kw"] == 100
    assert json.loads(thermal_path.read_text())["houses"].keys() == {"A", "B"}


def test_calculation_takes_the_heater_of_its_own_house(client, thermal_path):
    """Горелки корпуса A (газ, открытое пламя) не попадают в расчёт корпуса B."""
    client.put("/thermal/config", json={"house_id": "A", "building": DIMS,
                                        "heater": {"heater_type": "gas_open", "total_power_kw": 300}})
    args = dict(birds=30_000, age_days=7, outside_t=-5.0, outside_rh=60.0, heater_on=True)
    a = compute(CalcInput(**args, house_id="A"))
    b = compute(CalcInput(**args, house_id="B"))
    assert a.heater_note == "heater_full_duty_estimate"    # своя газовая горелка, UA нет
    assert b.heater_note == "heater_data_missing"          # у B своей горелки нет


def test_get_rejects_house_id_with_markup(client, thermal_path):
    assert client.get("/thermal/config", params={"house_id": "<img src=x>"}).status_code == 422


# ─── Переименование корпуса (список корпусов — в браузере, id = имя) ─────────

def test_renaming_a_house_moves_its_thermal_record(client, thermal_path):
    client.put("/thermal/config", json={"house_id": "A", "building": DIMS,
                                        "heater": {"heater_type": "gas_open", "total_power_kw": 300}})
    r = client.post("/thermal/rename-house", json={"old_house_id": "A", "new_house_id": "Корпус 1"})
    assert r.status_code == 200 and r.json() == {"moved": True}
    assert client.get("/thermal/config", params={"house_id": "Корпус 1"}).json()["heater"]["total_power_kw"] == 300
    assert client.get("/thermal/config", params={"house_id": "A"}).json()["heater"] is None


def test_rename_does_not_merge_into_a_house_that_has_data(client, thermal_path):
    for hid in ("A", "B"):
        client.put("/thermal/config", json={"house_id": hid, "building": DIMS})
    r = client.post("/thermal/rename-house", json={"old_house_id": "A", "new_house_id": "B"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "thermal_house_exists"


def test_rename_of_a_house_without_data_is_a_no_op(client, thermal_path):
    r = client.post("/thermal/rename-house", json={"old_house_id": "X", "new_house_id": "Y"})
    assert r.status_code == 200 and r.json() == {"moved": False}
