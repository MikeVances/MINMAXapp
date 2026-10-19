"""
Расчётные наружные условия (ASHRAE Fundamentals гл. 14; данные ERA5 через
Open-Meteo — бесплатно для некоммерческого использования, CC BY 4.0).

Сеть в тестах не используется: проверяются перцентили на синтетике и путь API
с подменённой загрузкой. Живая сверка (2026-10-19, Москва 55.75/37.62, 2015–2024):
−23.2 / 29.3 °C при MCWB 19.3 — у ASHRAE для Москвы около −24 / 29 / 19.6.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from backend.app.core import design_climate
from backend.app.core.design_climate import design_conditions

CFG_PATH = Path(os.environ["APP_CONFIG_JSON"])


def _year(n_years=1):
    """Ровная «пила» −20…+30 °C: 0.4 % / 99.6 % известны заранее."""
    hours = 8760 * n_years
    temps = [-20 + 50 * (i % 1000) / 999 for i in range(hours)]
    return temps, [50.0] * hours


def test_percentiles_on_a_known_distribution():
    temps, rhs = _year()
    d = design_conditions(temps, rhs)
    assert d.heating_996_c == pytest.approx(-20 + 50 * 0.004, abs=0.1)
    assert d.cooling_04_db_c == pytest.approx(-20 + 50 * 0.996, abs=0.1)
    assert d.cooling_04_rh_pct == 50
    assert d.evap_04_wb_c < d.cooling_04_db_c


def test_less_than_a_year_is_refused():
    temps, rhs = _year()
    with pytest.raises(ValueError):
        design_conditions(temps[:1000], rhs[:1000])


@pytest.fixture
def restore_config():
    before = CFG_PATH.read_bytes()
    yield
    CFG_PATH.write_bytes(before)


def test_api_saves_design_conditions_and_altitude(client, monkeypatch, restore_config):
    temps, rhs = _year(2)
    monkeypatch.setattr(design_climate, "fetch_hourly", lambda lat, lon: (temps, rhs, 152.0))
    from backend.app.routers import settings as settings_router
    monkeypatch.setattr(settings_router, "fetch_hourly", lambda lat, lon: (temps, rhs, 152.0))

    r = client.post("/settings/design-climate", json={"latitude": 55.75, "longitude": 37.62})
    assert r.status_code == 200, r.text
    cfg = client.get("/settings/app-config").json()
    assert cfg["design_cool_db_c"] == pytest.approx(29.8, abs=0.2)
    assert cfg["latitude"] == 55.75 and "Open-Meteo" in cfg["design_source"]
    assert cfg["altitude_m"] == 152.0      # высоты не было — взята у точки реанализа


def test_fetch_failure_is_a_coded_error(client, monkeypatch, restore_config):
    from backend.app.core.errors import CalcError
    from backend.app.routers import settings as settings_router

    def boom(lat, lon):
        raise CalcError("climate_unavailable")
    monkeypatch.setattr(settings_router, "fetch_hourly", boom)
    r = client.post("/settings/design-climate", json={"latitude": 0, "longitude": 0})
    assert r.status_code == 502 and r.json()["detail"]["code"] == "climate_unavailable"
