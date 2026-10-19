"""
Резервная копия данных фермы (решение владельца 2026-10-19: эфемерный диск
Render принят для теста; защита от потери — выгрузка и загрузка JSON).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from backend.app.core.building_thermal import THERMAL_CONFIG_PATH

CFG = Path(os.environ["APP_CONFIG_JSON"])
THERMAL = Path(THERMAL_CONFIG_PATH)
PROFILE = {"name": "Своя", "points": [{"day": 1, "body_weight_g": 50, "min_temp_c": 33},
                                      {"day": 42, "body_weight_g": 3000, "min_temp_c": 19}]}
DIMS = {"length_m": 100, "width_m": 16, "height_m": 3.25}


@pytest.fixture
def clean_state(client):
    cfg_before = CFG.read_bytes()
    THERMAL.unlink(missing_ok=True)
    yield
    CFG.write_bytes(cfg_before)
    THERMAL.unlink(missing_ok=True)
    client.delete("/profiles/my-backup")


def test_round_trip_restores_profiles_settings_and_thermal(client, clean_state):
    assert client.put("/profiles/my-backup", json=PROFILE).status_code == 200
    cfg = client.get("/settings/app-config").json()
    cfg.update(cycle_days=49, altitude_m=300)
    assert client.put("/settings/app-config", json=cfg).status_code == 200
    assert client.put("/thermal/config", json={"house_id": "A", "building": DIMS,
                      "heater": {"heater_type": "gas_open", "total_power_kw": 250}}).status_code == 200

    backup = client.get("/backup").json()
    assert "my-backup" in backup["profiles"] and "test-breed" not in backup["profiles"]   # встроенные не копируются
    assert backup["thermal"]["A"]["heater"]["total_power_kw"] == 250

    # «Деплой»: всё стёрто
    client.delete("/profiles/my-backup")
    THERMAL.unlink()
    cfg.update(cycle_days=42, altitude_m=0)
    client.put("/settings/app-config", json=cfg)

    r = client.post("/backup", json=backup)
    assert r.status_code == 200 and r.json() == {"profiles": 1, "app_config": True, "thermal_houses": 1}
    assert client.get("/profiles/my-backup").status_code == 200
    restored = client.get("/settings/app-config").json()
    assert restored["cycle_days"] == 49 and restored["altitude_m"] == 300
    assert client.get("/thermal/config", params={"house_id": "A"}).json()["heater"]["total_power_kw"] == 250


def test_damaged_backup_writes_nothing(client, clean_state):
    before = CFG.read_bytes()
    bad = {"version": 1, "app_config": {"cycle_days": 999},
           "profiles": {"ok-profile": PROFILE}, "thermal": {}}
    r = client.post("/backup", json=bad)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "backup_invalid"
    assert CFG.read_bytes() == before
    assert client.get("/profiles/ok-profile").status_code == 404     # профиль из того же файла не записан
