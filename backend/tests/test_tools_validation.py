"""
Валидация входа инструментов (/calc/tools/*): недопустимые данные → 422, а не 500.
"""
from __future__ import annotations

import pytest

_EVAP = dict(
    house_length_m=120, t_outdoor_db_c=35, rh_outdoor_pct=40, total_fan_m3h=500_000,
    pad_length_m=40, pad_height_m=1.8,
)


@pytest.mark.parametrize(
    "pad_type, thickness",
    [("5090", 200), ("7090", 125), ("7060", 50)],
)
def test_evap_unknown_pad_thickness_is_422(client, pad_type, thickness):
    """
    До исправления (ревью 2026-10-16) таблица SANHE давала KeyError → 500.
    У 5090 нет 200 мм, у 7090 нет 125 мм, у 7060 нет 50 мм.
    """
    r = client.post("/calc/tools/evap_cooling",
                    json={**_EVAP, "pad_type": pad_type, "pad_thickness_mm": thickness})

    assert r.status_code == 422
    assert "pad_thickness_mm" in r.text


def test_evap_valid_pad_still_calculates(client):
    """Валидатор не должен отсекать существующие пары."""
    r = client.post("/calc/tools/evap_cooling",
                    json={**_EVAP, "pad_type": "5090", "pad_thickness_mm": 150})

    assert r.status_code == 200
