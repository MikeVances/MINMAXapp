"""
Калибровка UA по кривой остывания (отметка на каждом градусе).

Синтетические кривые строятся ЧИСЛЕННЫМ интегрированием (Рунге–Кутта 4) системы
«воздух + конструкции», а не аналитической формулой модуля: эталон не должен
повторять проверяемый код.
"""
from __future__ import annotations

import random

import pytest

from backend.app.core.cooling_fit import fit_cooling_curve

VOLUME = 96 * 17 * 4.25          # м³ — корпус из реальной калибровки пользователя
T_OUT = -5.0
T_START = 25.0


def _c_air():
    t_mean = T_START - 3.0
    return VOLUME * 353.05 / (t_mean + 273.15) * 1006


def _simulate_taps(ua, k, c_struct, floor_lag=0.0, steps=6, noise_s=0.0, seed=1):
    """Время, когда воздух проходит каждый градус ниже старта (RK4, шаг 1 с)."""
    rng = random.Random(seed)
    c_air = _c_air()
    ta, ts = T_START, T_START - floor_lag
    t, dt = 0.0, 1.0
    out = [(0.0, T_START)]
    next_mark = T_START - 1

    def deriv(a, s):
        return ((-ua * (a - T_OUT) - k * (a - s)) / c_air, k * (a - s) / c_struct)

    while len(out) <= steps and t < 5 * 86400:
        k1 = deriv(ta, ts)
        k2 = deriv(ta + dt / 2 * k1[0], ts + dt / 2 * k1[1])
        k3 = deriv(ta + dt / 2 * k2[0], ts + dt / 2 * k2[1])
        k4 = deriv(ta + dt * k3[0], ts + dt * k3[1])
        ta_new = ta + dt / 6 * (k1[0] + 2 * k2[0] + 2 * k3[0] + k4[0])
        ts += dt / 6 * (k1[1] + 2 * k2[1] + 2 * k3[1] + k4[1])
        if ta_new <= next_mark:
            # линейная интерполяция внутри шага + «человеческая» погрешность нажатия
            frac = (ta - next_mark) / (ta - ta_new)
            stamp = round(t + frac * dt + rng.uniform(-noise_s, noise_s))
            out.append((float(stamp), next_mark))
            next_mark -= 1
        ta, t = ta_new, t + dt
    return out


@pytest.mark.parametrize(
    "ua, k, c_struct",
    [(3000, 18000, 6e7), (3000, 18000, 2e8), (5000, 10000, 5e7), (2000, 25000, 1e8)],
)
def test_ua_recovered_from_taps_with_human_timing_error(ua, k, c_struct):
    """±3 с на каждом нажатии — UA в пределах 3 %."""
    taps = _simulate_taps(ua, k, c_struct, noise_s=3)

    fit = fit_cooling_curve(VOLUME, T_OUT, taps)

    assert fit.ua_w_per_k == pytest.approx(ua, rel=0.03)


def test_air_only_estimate_would_be_off_by_several_times():
    """
    Зачем всё это: прежний расчёт по теплоёмкости одного воздуха на той же кривой
    занижает UA в разы (у пола и стен своя теплоёмкость, она подпитывает воздух).
    """
    import math
    taps = _simulate_taps(3000, 18000, 6e7)
    t_last, temp_last = taps[-1]
    air_only = _c_air() / t_last * math.log((T_START - T_OUT) / (temp_last - T_OUT))

    fit = fit_cooling_curve(VOLUME, T_OUT, taps)

    assert air_only < 0.5 * fit.ua_w_per_k


def test_unheated_floor_overstates_ua_and_is_not_visible_in_fit():
    """
    Пол холоднее воздуха на 5 °C (горелки только что выключены): модель подгоняется
    без заметной ошибки, но UA завышен ~вдвое. Поэтому прогрев — обязательное условие,
    а приложение может лишь косвенно предупредить по скорости остывания.
    """
    taps = _simulate_taps(3000, 18000, 6e7, floor_lag=5.0)

    fit = fit_cooling_curve(VOLUME, T_OUT, taps)

    assert fit.ua_w_per_k > 1.5 * 3000
    assert fit.rms_c < 0.1


def test_fast_cooling_and_small_delta_t_are_flagged():
    taps = [(0, 25.0), (30, 24.0), (65, 23.0), (100, 22.0), (140, 21.0)]

    fit = fit_cooling_curve(VOLUME, 15.0, taps)   # ΔT = 10 °C

    assert "fast_cooling" in fit.warnings
    assert "small_delta_t" in fit.warnings


@pytest.mark.parametrize(
    "taps, why",
    [
        ([(0, 25), (60, 24), (130, 23)], "мало отметок"),
        ([(0, 25), (60, 24), (50, 23), (200, 22), (300, 21)], "время не растёт"),
        ([(0, 25), (60, 24), (130, 24.5), (200, 22), (300, 21)], "температура выросла"),
        ([(10, 25), (60, 24), (130, 23), (200, 22), (300, 21)], "нет точки старта"),
    ],
)
def test_invalid_taps_rejected(taps, why):
    with pytest.raises(ValueError):
        fit_cooling_curve(VOLUME, T_OUT, taps)


# ─── API ──────────────────────────────────────────────────────────────────────

import json
from pathlib import Path

from backend.app.core.building_thermal import THERMAL_CONFIG_PATH


@pytest.fixture
def house_config():
    path = Path(THERMAL_CONFIG_PATH)

    def write(height_m):
        path.write_text(json.dumps({"house_id": "1", "building":
                                    {"length_m": 96, "width_m": 17, "height_m": height_m}}),
                        encoding="utf-8")
    yield write
    path.unlink(missing_ok=True)


def _api_points(taps):
    return [{"t_s": t, "temp_c": temp} for t, temp in taps]


def test_api_curve_calibration(client, house_config):
    house_config(4.25)
    taps = _simulate_taps(3000, 18000, 6e7, noise_s=2)

    r = client.post("/thermal/calibrate-curve", json={"t_outside_c": T_OUT, "points": _api_points(taps)})

    assert r.status_code == 200
    body = r.json()
    assert body["method"] == "cooling_curve"
    assert body["ua_coefficient"] == pytest.approx(3000, rel=0.03)
    assert body["c_struct_j_per_k"] > body["c_air_j_per_k"]   # пол и стены тяжелее воздуха


def test_saved_curve_is_recomputed_for_new_volume(client, house_config):
    """
    Модель однородна по теплоёмкости воздуха: при тех же отметках удвоение объёма
    удваивает UA. Сервер пересчитывает UA из сохранённых точек.
    """
    taps = _simulate_taps(3000, 18000, 6e7)
    cal = {"t_initial_c": T_START, "t_final_c": taps[-1][1], "t_outside_c": T_OUT,
           "time_minutes": taps[-1][0] / 60, "method": "cooling_curve", "points": _api_points(taps)}

    house_config(4.25)
    assert client.put("/thermal/config", json={"house_id": "1", "building":
                      {"length_m": 96, "width_m": 17, "height_m": 4.25}, "calibration": cal}).status_code == 200
    ua_1 = client.get("/thermal/config").json()["calibration"]["ua_coefficient"]

    assert client.put("/thermal/config", json={"house_id": "1", "building":
                      {"length_m": 96, "width_m": 17, "height_m": 8.5}, "calibration": cal}).status_code == 200
    saved = client.get("/thermal/config").json()["calibration"]

    assert saved["method"] == "cooling_curve"
    assert len(saved["points"]) == len(taps)
    assert saved["ua_coefficient"] == pytest.approx(2 * ua_1, rel=1e-3)
