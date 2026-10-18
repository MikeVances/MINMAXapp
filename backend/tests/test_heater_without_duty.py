"""
Горелки включены, а загрузку не найти (нет калибровки UA или данных о горелке).

Раньше к Qmin добавлялось 0.10 / 0.05 / 0.025 м³/ч на голову по возрасту — без
источника и даже для электрических обогревателей, у которых CO₂ нет (аудит
2026-10-18). Теперь — только следующее из данных, остальное помечено.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.app.core.building_thermal import THERMAL_CONFIG_PATH, heater_co2_dilution_m3h
from backend.app.core.calc_core import CalcInput, compute

ARGS = dict(birds=30_000, age_days=7, outside_t=-5.0, outside_rh=60.0)
HEATER_KW = 300.0


@pytest.fixture
def thermal(request):
    """Конфиг теплотехники без калибровки UA: только горелка (или ничего)."""
    path = Path(THERMAL_CONFIG_PATH)
    heater_type = request.param
    if heater_type is None:
        path.unlink(missing_ok=True)
    else:
        path.write_text(json.dumps({"heater": {"heater_type": heater_type, "total_power_kw": HEATER_KW}}),
                        encoding="utf-8")
    yield
    path.unlink(missing_ok=True)


@pytest.mark.parametrize("thermal", [None], indirect=True)
def test_no_heater_data_adds_nothing_and_says_so(thermal):
    off = compute(CalcInput(**ARGS, heater_on=False))
    on = compute(CalcInput(**ARGS, heater_on=True))
    assert on.q_min_m3h == pytest.approx(off.q_min_m3h)
    assert on.heater_note == "heater_data_missing" and on.heater_air_m3h is None


@pytest.mark.parametrize("thermal", ["electric"], indirect=True)
def test_electric_heaters_add_no_air(thermal):
    off = compute(CalcInput(**ARGS, heater_on=False))
    on = compute(CalcInput(**ARGS, heater_on=True))
    assert on.q_min_m3h == pytest.approx(off.q_min_m3h)
    assert on.heater_note is None


@pytest.mark.parametrize("thermal", ["gas_open"], indirect=True)
def test_open_flame_without_ua_takes_full_duty_as_upper_estimate(thermal):
    off = compute(CalcInput(**ARGS, heater_on=False))
    on = compute(CalcInput(**ARGS, heater_on=True))
    dilution = heater_co2_dilution_m3h(HEATER_KW, 1.0, "gas_open")   # 300 кВт → 17 308 м³/ч
    assert on.heater_air_m3h == pytest.approx(dilution)
    assert on.q_min_m3h >= off.q_min_m3h
    assert on.heater_note == "heater_full_duty_estimate"


def test_notes_have_texts_in_every_dictionary():
    import re
    static = Path(__file__).resolve().parents[1] / "app" / "static"
    for lang in ("en", "ru", "de", "fr", "pl"):
        text = (static / "i18n" / f"{lang}.js").read_text(encoding="utf-8")
        for code in ("heater_data_missing", "heater_full_duty_estimate"):
            assert re.search(rf"\b{code}_note:", text), (lang, code)
