"""
Правдоподобие калибровки UA и привязка к корпусу (аудит 2026-10-18).

В рабочем data/thermal_config.json нашёлся UA 21 090 Вт/К по «тесту» длиной
1.017 мин старым методом по одной точке, и он применялся к расчёту ЛЮБОГО
корпуса фермы. Такая калибровка не должна попадать в расчёт и сохраняться.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.app.core.building_thermal import (
    THERMAL_CONFIG_PATH, BuildingDimensions, CalibrationTest, calibration_problem, envelope_area_m2,
)
from backend.app.core.calc_core import CalcInput, compute

HOUSE_DIMS = {"length_m": 96.0, "width_m": 17.0, "height_m": 4.25}   # как в рабочем конфиге
# Ровно запись из рабочего конфига: метода нет → старый «air_only_cooling»
PRODUCTION_CALIBRATION = {"t_initial_c": 30.0, "t_final_c": 25.0, "t_outside_c": -5.0,
                          "time_minutes": 1.017, "ua_coefficient": 21089.72}
GOOD_CALIBRATION = {"t_initial_c": 20.0, "t_final_c": 15.0, "t_outside_c": 0.0,
                    "time_minutes": 90.0, "ua_coefficient": 3000.0, "method": "cooling_curve"}


@pytest.fixture
def thermal_file():
    path = Path(THERMAL_CONFIG_PATH)

    def write(**cfg):
        path.write_text(json.dumps(cfg), encoding="utf-8")
    yield write
    path.unlink(missing_ok=True)


def _cal(**kw) -> CalibrationTest:
    return CalibrationTest(**{**GOOD_CALIBRATION, **kw})


# ─── Правила ──────────────────────────────────────────────────────────────────

def test_envelope_area_excludes_floor():
    # кровля 96×17 + стены 2×96×4.25 + торцы 2×17×4.25
    assert envelope_area_m2(BuildingDimensions(**HOUSE_DIMS)) == pytest.approx(1632 + 816 + 144.5)


def test_production_calibration_is_rejected_on_every_count():
    b = BuildingDimensions(**HOUSE_DIMS)
    assert calibration_problem(CalibrationTest(**PRODUCTION_CALIBRATION), b)["code"] == "calibration_method_obsolete"
    assert calibration_problem(_cal(time_minutes=1.017), b)["code"] == "calibration_too_short"
    # 21 090 / 2 592.5 = 8.13 Вт/(м²·К) — хуже одинарной шторы (≈ 5.9)
    problem = calibration_problem(_cal(ua_coefficient=21089.72), b)
    assert problem == {"code": "calibration_implausible", "params": {"u": 8.13, "min": 0.1, "max": 8.0}}


def test_realistic_curve_calibration_is_accepted():
    # 3 000 / 2 592.5 = 1.16 Вт/(м²·К) — неутеплённые стены с утеплённой кровлей
    assert calibration_problem(_cal(), BuildingDimensions(**HOUSE_DIMS)) is None


# ─── Расчёт ───────────────────────────────────────────────────────────────────

def _qmax(house_id: str | None, **kw) -> tuple[float, dict | None]:
    # 35 дней, 10 °C: туннель выключен, потолка нет — Qmax задаёт тепловой баланс с UA
    r = compute(CalcInput(birds=20_000, age_days=35, outside_t=10.0, outside_rh=50.0, house_id=house_id, **kw))
    return r.q_max_m3h, r.calibration_ignored


def test_production_calibration_does_not_change_the_result(thermal_file):
    """Раньше UA 21 090 «помогал» стенам охлаждать корпус и менял Qmax; теперь — как без калибровки."""
    thermal_file()
    no_cal, _ = _qmax("1")
    thermal_file(house_id="1", building=HOUSE_DIMS, calibration=PRODUCTION_CALIBRATION)

    q, ignored = _qmax("1")

    assert q == pytest.approx(no_cal)
    assert ignored["code"] == "calibration_method_obsolete"


def test_calibration_applies_only_to_its_own_house(thermal_file):
    """Теплотехника хранится по корпусам: у корпуса 2 своей калибровки нет — расчёт без UA."""
    thermal_file()
    no_cal, _ = _qmax("2")
    thermal_file(house_id="1", building=HOUSE_DIMS, calibration=GOOD_CALIBRATION)

    q_other, ignored = _qmax("2")
    q_own, own_ignored = _qmax("1")

    assert q_other == pytest.approx(no_cal)
    assert ignored is None                       # нечего отклонять: запись чужого корпуса не видна
    assert own_ignored is None
    assert q_own != pytest.approx(no_cal)        # UA своего корпуса участвует в балансе


# ─── API ──────────────────────────────────────────────────────────────────────

def test_short_curve_test_is_not_saved(client, thermal_file):
    thermal_file(house_id="1", building=HOUSE_DIMS)
    points = [{"t_s": 60 * i, "temp_c": 20.0 - i} for i in range(6)]          # 5 минут

    r = client.put("/thermal/config", json={"house_id": "1", "building": HOUSE_DIMS, "calibration": {
        "t_initial_c": 20, "t_final_c": 15, "t_outside_c": 0, "time_minutes": 5,
        "method": "cooling_curve", "points": points}})

    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "calibration_too_short"


def test_new_single_point_calibration_is_refused(client, thermal_file):
    thermal_file(house_id="1", building=HOUSE_DIMS)

    r = client.put("/thermal/config", json={"house_id": "1", "building": HOUSE_DIMS, "calibration": {
        "t_initial_c": 20, "t_final_c": 18, "t_outside_c": 0, "time_minutes": 30}})

    assert r.status_code == 422
    assert r.json()["detail"] == "calibration_method_obsolete"


def test_stored_obsolete_record_does_not_block_saving_heaters(client, thermal_file):
    """Клиент возвращает старую запись как есть вместе с горелками — сохранение проходит."""
    thermal_file(house_id="1", building=HOUSE_DIMS, calibration=PRODUCTION_CALIBRATION)

    r = client.put("/thermal/config", json={"house_id": "1", "building": HOUSE_DIMS,
                                            "heater": {"heater_type": "gas_open", "total_power_kw": 300},
                                            "calibration": PRODUCTION_CALIBRATION})
    cfg = client.get("/thermal/config", params={"house_id": "1"}).json()

    assert r.status_code == 200
    assert cfg["heater"]["total_power_kw"] == 300
    assert cfg["calibration_problem"]["code"] == "calibration_method_obsolete"


def test_heater_analysis_refuses_implausible_calibration(client, thermal_file):
    thermal_file(house_id="1", building=HOUSE_DIMS, calibration=PRODUCTION_CALIBRATION,
                 heater={"heater_type": "gas_open", "total_power_kw": 300})

    r = client.post("/thermal/analyze-heaters", json={
        "house_id": "1", "t_inside_target": 30, "t_outside": -5, "q_min_m3h": 3000, "num_birds": 20000, "bird_weight_kg": 0.2})

    assert r.status_code == 400
    assert r.json()["detail"] == "calibration_method_obsolete"


def test_client_save_gate_uses_server_minimum_duration():
    """
    Кнопка «Сохранить» гасится на клиенте по тому же порогу, по которому сервер
    откажет (иначе отказ всплывает только после нажатия). Порог продублирован в
    calibration.js — следим, чтобы не разошёлся, в том числе с fast_cooling.
    """
    import re
    from pathlib import Path
    from backend.app.core.building_thermal import MIN_CALIBRATION_MINUTES
    from backend.app.core.cooling_fit import FAST_TEST_S

    js = (Path(__file__).resolve().parents[1] / "app" / "static" / "calibration.js").read_text(encoding="utf-8")
    client_min = float(re.search(r"const MIN_CALIBRATION_MINUTES = ([\d.]+);", js).group(1))

    assert client_min == MIN_CALIBRATION_MINUTES == FAST_TEST_S / 60
