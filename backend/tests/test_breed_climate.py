"""
Уставка температуры по методике производителя кросса (core/breed_climate.py).

Эталоны посчитаны руками по таблицам производителей, а не вызовом модуля:
  Cobb 2021 §5.2 (с. 40): дни 0/7/14 при 60 % RH — 31/29/26 °C, 1 °C на 10 % RH;
      по плотности 28 кг/м² → 22 … 42 → 15, больше 42 → 14 °C.
  Hubbard Efficiency Plus V-2026-09, прил. 1 (с. 10): по возрасту, без поправки на RH.

Профили — НАСТОЯЩИЕ встроенные файлы Cobb 500 и Hubbard из data/: на время модуля
они копируются во временный каталог профилей тестов (conftest), рабочий data/
не трогается. Корпус запроса: пол 120 × 16 = 1920 м², 30 000 голов → 15.625 гол/м².
"""
from __future__ import annotations

import json
import os
import shutil
from copy import deepcopy
from pathlib import Path

import pytest

from backend.app.core import breed_climate as bc

ROOT = Path(__file__).resolve().parents[2]
PROFILES = Path(os.environ["GROWTH_PROFILES_DIR"])
BUILTIN = ("cobb500", "hubbard-efficiency-plus")

HEADS_PER_M2 = 30_000 / 1920.0
# Масса профиля Cobb 500 (Cobb 2022 as-hatched): 14-й день 570 г
DENSITY_D14 = HEADS_PER_M2 * 0.570

REQ = {
    "house": {"length_m": 120, "width_m": 16, "wall_height_m": 2.5, "ridge_height_m": 4.5},
    "flock": {"birds": 30_000, "growth_profile_id": "cobb500", "age_days": 30, "housing": "floor_litter"},
    "conditions": {"outdoor_t_c": 25.0, "outdoor_rh_pct": 5.0},
}
DESIGN = {
    "house": {"length_m": 120, "width_m": 16, "wall_height_m": 2.5, "ridge_height_m": 4.5},
    "envelope": {"walls": {"u_w_m2k": 0.4}, "roof": {"u_w_m2k": 0.21}},
    "flock": {"birds": 30_000, "growth_profile_id": "cobb500", "cycle_days": 42,
              "housing": "floor_litter", "mortality_pct": 0},
    "climate": {"winter_design_c": -9.8, "summer_design_db_c": 35.6, "summer_design_rh_pct": 28},
}
CAGES = {"housing": "cages"}
ROWS = [{"count": 4, "width_m": 1.6, "height_m": 2.2}]


@pytest.fixture(scope="module", autouse=True)
def builtin_profiles():
    """Настоящие встроенные профили Cobb и Hubbard — на время модуля, потом убрать."""
    copied = []
    for pid in BUILTIN:
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


def _requirement(client, **patch) -> dict:
    r = client.post("/api/v1/ventilation-requirements", json=_with(REQ, **patch))
    assert r.status_code == 201, r.text
    return r.json()


def _codes(notes) -> set:
    return {n["code"] for n in notes}


def _source_ids(j) -> set:
    return {s["id"] for s in j["sources"]}


# ─── Таблицы Cobb ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("density, temp", [(28, 22.0), (31, 20.5), (42, 15.0), (42.5, 14.0), (60, 14.0)])
def test_cobb_density_table(density, temp):
    assert bc.cobb_temp_by_density(density) == pytest.approx(temp)


@pytest.mark.parametrize("rh, shift", [(60, 0.0), (40, 2.0), (70, -1.0), (30, 3.0), (80, 0.0)])
def test_cobb_rh_shift(rh, shift):
    # 1 °C на 10 % RH внутри таблицы 30–70 %; вне её — без сдвига
    assert bc.cobb_rh_shift(rh) == pytest.approx(shift)


def test_cobb_transition_is_by_density():
    # Половина пути по плотности от 14-го дня к 28 кг/м² — половина пути 26 → 22 °C
    assert bc.cobb_temp_after_age_table(26.0, 8.0, 18.0) == pytest.approx(24.0)


# ─── Cobb через API ──────────────────────────────────────────────────────────

def test_cobb_after_day14_follows_stocking_density(client):
    # День 30: 1989 г × 15.625 гол/м² = 31.08 кг/м² → 21 − (1.08/2) = 20.46 °C.
    # По профилю (Ross) было бы 20.7 — метод Cobb даёт другое число
    j = _requirement(client)
    assert j["target_temp_c"] == pytest.approx(21.0 - (HEADS_PER_M2 * 1.989 - 30.0) / 2.0, abs=0.01)
    assert "cobb_2021_5_2" in _source_ids(j)
    assert "ross_2025_t2_5" not in _source_ids(j)


def test_cobb_transition_day21(client):
    # День 21: 1116 г → 17.44 кг/м², доля пути от 8.91 к 28 кг/м² — 0.447 → 24.21 °C
    j = _requirement(client, flock={"age_days": 21})
    share = (HEADS_PER_M2 * 1.116 - DENSITY_D14) / (28.0 - DENSITY_D14)
    assert j["target_temp_c"] == pytest.approx(26.0 - 4.0 * share, abs=0.01)
    assert "cobb_density_transition" in _codes(j["assumptions"])


def test_cobb_early_days_by_age_and_rh(client):
    # День 7: 29 °C при 60 % RH; при 40 % — на 2 °C теплее (таблица Cobb, не Mitchell)
    assert _requirement(client, flock={"age_days": 7})["target_temp_c"] == pytest.approx(29.0)
    dry = _requirement(client, flock={"age_days": 7, "target_rh_pct": 40})
    assert dry["target_temp_c"] == pytest.approx(31.0)


def test_cobb_dense_flock_is_flagged(client):
    # День 42: 3278 г → 51.2 кг/м² — выше предела Cobb 42 кг/м²: 14 °C и предупреждение
    j = _requirement(client, flock={"age_days": 42})
    assert j["target_temp_c"] == pytest.approx(14.0)
    high = [f for f in j["findings"] if f["code"] == "stocking_density_high"]
    assert high and high[0]["params"]["density_kg_m2"] == pytest.approx(HEADS_PER_M2 * 3.278, abs=0.1)


def test_cobb_in_cages_falls_back_to_profile(client):
    # В клетках плотности на м² пола у Cobb нет смысла — значение профиля и допущение
    j = _requirement(client, flock=CAGES, house={"cage_rows": ROWS})
    assert j["target_temp_c"] == pytest.approx(20.7, abs=0.05)
    assert "cobb_density_unavailable" in _codes(j["assumptions"])
    assert "ross_2025_t2_5" in _source_ids(j)


def test_cobb_design_heating_peak_moves_to_brooding(client):
    # Проект на цикл: уставка падает с плотностью — пик обогрева не в конце цикла
    j = client.post("/api/v1/ventilation-designs", json=DESIGN).json()
    days = {d["day"]: d for d in j["days"]}
    assert days[14]["target_temp_c"] == pytest.approx(26.0)
    assert days[42]["target_temp_c"] == pytest.approx(14.0)
    assert {"cobb_density_transition"} <= _codes(j["assumptions"])
    assert "stocking_density_high" in _codes(j["warnings"])
    assert "cobb_2021_5_2" in _source_ids(j)


# ─── Hubbard ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("day, temp", [(1, 32.5), (7, 30.0), (14, 28.0), (21, 25.5), (28, 22.5), (35, 20.0), (42, 20.0)])
def test_hubbard_by_age(client, day, temp):
    j = _requirement(client, flock={"growth_profile_id": "hubbard-efficiency-plus", "age_days": day})
    assert j["target_temp_c"] == pytest.approx(temp, abs=0.05)
    assert "hubbard_2026_app1" in _source_ids(j)


def test_hubbard_ignores_target_rh(client):
    # Hubbard поправки на RH не даёт: 40 % и 70 % — та же уставка
    flock = {"growth_profile_id": "hubbard-efficiency-plus", "age_days": 7}
    dry = _requirement(client, flock={**flock, "target_rh_pct": 40})
    wet = _requirement(client, flock={**flock, "target_rh_pct": 70})
    assert dry["target_temp_c"] == wet["target_temp_c"] == pytest.approx(30.0)


# ─── Свой профиль ────────────────────────────────────────────────────────────

def test_custom_copy_keeps_its_own_temperatures(client):
    # Копия Cobb с объявленной методикой — всё равно СВОЙ профиль: его температуры
    # пользователь мог переписать, методику производителя к ним не применяем
    src = json.loads((ROOT / "data/growth_profiles/builtin/cobb500.json").read_text(encoding="utf-8"))
    dst = PROFILES / "custom" / "my-cobb.json"
    dst.parent.mkdir(exist_ok=True)
    dst.write_text(json.dumps(src), encoding="utf-8")
    try:
        j = _requirement(client, flock={"growth_profile_id": "my-cobb"})
    finally:
        dst.unlink()
    assert j["target_temp_c"] == pytest.approx(20.7, abs=0.05)
    assert "cobb_2021_5_2" not in _source_ids(j)


# ─── Интерфейс ───────────────────────────────────────────────────────────────

def test_ui_takes_floor_from_stored_house_dimensions():
    # Интерфейс не передаёт площадь пола, но хранит размеры корпуса: 120 × 16 м —
    # тот же пол, что в запросах API, поэтому день 30 — те же 20.46 °C, а не 20.7 профиля
    from backend.app.core.building_thermal import THERMAL_CONFIG_PATH
    from backend.app.core.calc_core import CalcInput, compute
    path = Path(THERMAL_CONFIG_PATH)
    path.write_text(json.dumps({"houses": {"1": {
        "building": {"length_m": 120, "width_m": 16, "height_m": 3.5}}}}), encoding="utf-8")
    try:
        r = compute(CalcInput(birds=30_000, age_days=30, outside_t=-5.0,
                              growth_profile_id="cobb500", house_id="1"))
    finally:
        path.unlink()
    assert r.setpoint_method == bc.DAY_COBB_DENSITY
    assert r.min_temp_c == pytest.approx(21.0 - (HEADS_PER_M2 * 1.989 - 30.0) / 2.0, abs=0.01)
