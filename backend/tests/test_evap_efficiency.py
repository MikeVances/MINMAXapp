"""
КПД панели: по паспорту — зависит от скорости воздуха через панель; вручную (аудит
2026-10-18, [~] «КПД из паспорта оптимистичнее поля»).

Паспорт — новая панель (7090/150 мм, Munters CELdek: 83 % при 2 м/с); в работе UGA даёт
70–75 %, FSA-1068 — 75 % для 150 мм. Коэффициента пересчёта нет ни в одном
источнике — поэтому пользователь может задать свой КПД, по умолчанию — паспорт.
"""
from __future__ import annotations

BODY = dict(house_length_m=120, t_outdoor_db_c=35, rh_outdoor_pct=30, total_fan_m3h=400_000,
            pad_type="7090", pad_thickness_mm=150, pad_length_m=24, pad_height_m=1.5, t_inside_target_c=28)


def test_default_is_the_passport(client):
    r = client.post("/calc/tools/evap_cooling", json=BODY).json()
    # 400 000 м³/ч через 36 м² — 3.09 м/с, край кривой CELdek 150 мм: 79 %
    assert r["efficiency_basis"] == "passport" and r["pad_efficiency"] == 0.79


def _eta_at(client, thickness_mm, velocity_ms):
    """КПД по паспорту при заданной скорости через панель 7090 (24 × 1.5 = 36 м²)."""
    body = {**BODY, "pad_thickness_mm": thickness_mm, "total_fan_m3h": velocity_ms * 36 * 3600}
    r = client.post("/calc/tools/evap_cooling", json=body).json()
    assert r["air_velocity_ms"] == velocity_ms      # проба дошла до нужной скорости
    return r["pad_efficiency"]


def test_passport_efficiency_falls_with_air_velocity(client):
    # Замечание владельца 2026-10-28: КПД вёл себя как один порог насыщения. У прежних
    # кривых SANHE 7090 на 2.5–3 м/с он стоял на месте (200 мм: 89 и 89 %, 300 мм: 96 и 96 %);
    # у Munters CELdek 7090-15 падает: 200 мм 88.2 → 86.7 %, 300 мм 94.9 → 94.4 %
    assert _eta_at(client, 200, 3.0) < _eta_at(client, 200, 2.5)
    assert _eta_at(client, 300, 3.0) < _eta_at(client, 300, 2.5)


def test_pad_curves_fall_with_velocity_everywhere():
    # Любая строка таблицы 7090, взятая с CELdek, строго убывает по скорости — плоский
    # участок значил бы, что расчёт перестал чувствовать скорость
    from backend.app.core.evap_cooling_calc import SANHE_PADS
    pad = SANHE_PADS["7090"]
    for thickness in (100, 150, 200, 300):
        eta = pad["efficiency_pct"][thickness]
        assert all(a > b for a, b in zip(eta, eta[1:])), thickness


def test_user_efficiency_reaches_the_calculation(client):
    passport = client.post("/calc/tools/evap_cooling", json=BODY).json()
    field = client.post("/calc/tools/evap_cooling", json={**BODY, "pad_efficiency_pct": 75}).json()
    assert field["efficiency_basis"] == "user" and field["pad_efficiency"] == 0.75
    # Ниже КПД — теплее после панели и меньше воды
    assert field["t_pad_out_c"] > passport["t_pad_out_c"]
    assert field["water_flow_lpm"] < passport["water_flow_lpm"]


def test_efficiency_outside_range_is_rejected(client):
    assert client.post("/calc/tools/evap_cooling", json={**BODY, "pad_efficiency_pct": 120}).status_code == 422
