"""
КПД панели вручную (аудит 2026-10-18, [~] «КПД из паспорта SANHE оптимистичнее поля»).

Паспорт SANHE — новая панель (7090/150 мм при 1.8 м/с ≈ 84 %); в работе UGA даёт
70–75 %, FSA-1068 — 75 % для 150 мм. Коэффициента пересчёта нет ни в одном
источнике — поэтому пользователь может задать свой КПД, по умолчанию — паспорт.
"""
from __future__ import annotations

BODY = dict(house_length_m=120, t_outdoor_db_c=35, rh_outdoor_pct=30, total_fan_m3h=400_000,
            pad_type="7090", pad_thickness_mm=150, pad_length_m=24, pad_height_m=1.5, t_inside_target_c=28)


def test_default_is_the_passport(client):
    r = client.post("/calc/tools/evap_cooling", json=BODY).json()
    assert r["efficiency_basis"] == "passport" and r["pad_efficiency"] > 0.8


def test_user_efficiency_reaches_the_calculation(client):
    passport = client.post("/calc/tools/evap_cooling", json=BODY).json()
    field = client.post("/calc/tools/evap_cooling", json={**BODY, "pad_efficiency_pct": 75}).json()
    assert field["efficiency_basis"] == "user" and field["pad_efficiency"] == 0.75
    # Ниже КПД — теплее после панели и меньше воды
    assert field["t_pad_out_c"] > passport["t_pad_out_c"]
    assert field["water_flow_lpm"] < passport["water_flow_lpm"]


def test_efficiency_outside_range_is_rejected(client):
    assert client.post("/calc/tools/evap_cooling", json={**BODY, "pad_efficiency_pct": 120}).status_code == 422
