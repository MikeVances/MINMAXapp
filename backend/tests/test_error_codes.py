"""
Ошибки API — машинные коды, а не текст (аудит i18n 2026-10-17).

Сервер не знает языка интерфейса: наружу уходит ``detail`` в виде кода
(строка или ``{"code", "params"}``), фразу подставляет клиент из словаря
``srv_<code>``. Здесь закреплён контракт и отсутствие русских строк в ошибках.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from backend.app.core.errors import CalcError
from backend.app.core.cooling_fit import MIN_TAPS, fit_cooling_curve

CYRILLIC = re.compile(r"[А-Яа-яЁё]")

_TUNNEL_BODY = {
    "house_width_m": 15, "house_height_m": 2.5, "tunnel_height_m": 2.5,
    "num_fans": 10, "fan_capacity_m3h": 40_000,
    "t_outdoor_db_c": 30, "rh_outdoor_pct": 50, "bird_age_days": 40, "outside_temp_c": 30,
}


def test_calc_error_carries_code_and_params():
    with pytest.raises(CalcError) as info:
        fit_cooling_curve(1000.0, 0.0, [(0, 20.0), (60, 19.0)])

    assert info.value.code == "too_few_taps"
    assert info.value.params == {"min": MIN_TAPS}
    assert info.value.detail == {"code": "too_few_taps", "params": {"min": MIN_TAPS}}
    # str(e) идёт в журнал и в msg pydantic — там тоже только код
    assert not CYRILLIC.search(str(info.value))


def test_calibrate_curve_returns_code_detail(client):
    r = client.post("/thermal/calibrate-curve", json={
        "t_outside_c": 0, "volume_m3": 1000,
        "points": [{"t_s": 0, "temp_c": 20}, {"t_s": 60, "temp_c": 19}],
    })

    assert r.status_code == 400
    assert r.json()["detail"] == {"code": "too_few_taps", "params": {"min": MIN_TAPS}}


def test_analyze_heaters_without_calibration_returns_code(client):
    # thermal_config в тестах не создаётся (conftest) — калибровки нет
    r = client.post("/thermal/analyze-heaters", json={
        "t_inside_target": 20, "t_outside": 0, "q_min_m3h": 1000,
        "num_birds": 100, "bird_weight_kg": 1,
    })

    assert r.status_code == 400
    assert r.json()["detail"] == "calibration_missing"


def test_unknown_growth_profile_returns_code_with_id(client):
    r = client.post("/calc/summary7", json={
        "house": "1", "birds": 1000, "age_days": 21, "outside_t": 10,
        "growth_profile_id": "no-such-breed",
    })

    assert r.status_code == 404
    assert r.json()["detail"] == {"code": "profile_not_found", "params": {"id": "no-such-breed"}}


def test_invalid_profile_id_returns_code(client):
    r = client.get("/profiles/BAD%20ID")

    assert r.status_code == 422
    assert r.json()["detail"] == {"code": "profile_id_invalid", "params": {"id": "BAD ID"}}


def test_pydantic_validator_exposes_code_in_ctx(client):
    """
    CalcError внутри model_validator: pydantic заворачивает его в 422, а FastAPI
    сериализует само исключение в ctx.error — клиент читает код оттуда.
    """
    r = client.post("/calc/tools/tunnel_speed", json={**_TUNNEL_BODY, "fan_capacity_25pa_m3h": 50_000})

    assert r.status_code == 422
    (item,) = r.json()["detail"]
    assert item["type"] == "value_error"
    assert item["ctx"]["error"] == {"code": "fan_25pa_above_free_air", "params": {}}
    assert not CYRILLIC.search(item["msg"])


def test_no_cyrillic_in_raised_errors_source():
    """
    Страховка от возврата русских строк в ошибки: любая строка с raise или
    detail= в коде приложения не должна содержать кириллицу (текст — в словарях).
    """
    app_dir = Path(__file__).resolve().parents[1] / "app"
    offenders = []
    for path in app_dir.rglob("*.py"):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("#", 1)[0]   # комментарии по-русски — норма проекта
            if ("raise " in code or "detail=" in code) and CYRILLIC.search(code):
                offenders.append(f"{path.relative_to(app_dir)}:{lineno}: {line.strip()}")

    assert not offenders, "\n".join(offenders)


# ─── Стадо, дневник, аналитика, обратная связь ───────────────────────────────

def test_flock_and_diary_errors_are_codes(client):
    assert client.get("/flock/no-such-house/info").json()["detail"] == {
        "code": "flock_not_found", "params": {"house_id": "no-such-house"}}
    assert client.get("/flock/no-such-house/diary/3").json()["detail"] == {
        "code": "diary_entry_not_found", "params": {"house_id": "no-such-house", "day": 3}}
    assert client.get("/flock/no-such-house/analytics/summary").json()["detail"] == {
        "code": "flock_not_found", "params": {"house_id": "no-such-house"}}


def test_diary_validation_returns_list_of_codes():
    """
    Границы полей через API держит pydantic (422), а validate() дата-класса —
    вторая линия для записей, созданных не через API. Её ошибки — тоже коды:
    роутер отдаёт этот список как detail, клиент переводит каждую строку.
    """
    from backend.app.models.flock import FlockDiaryEntry

    entry = FlockDiaryEntry(house_id="h", date="2026-10-05", day_of_cycle=5,
                            mortality_count=-1, feed_consumption_kg=-2.0)

    assert entry.validate() == [
        {"code": "diary_mortality_negative", "params": {"count": -1}},
        {"code": "diary_feed_negative", "params": {"kg": -2.0}},
    ]


def test_bad_iso_date_exposes_code_in_ctx(client):
    r = client.post("/flock/codes-house/info", json={
        "house_id": "codes-house", "flock_name": "f", "placement_date": "10/01/2026", "initial_bird_count": 100})

    assert r.status_code == 422
    (item,) = r.json()["detail"]
    assert item["ctx"]["error"] == {"code": "date_not_iso", "params": {"field": "placement_date", "value": "10/01/2026"}}


def test_feedback_rate_limit_is_a_code(client, monkeypatch):
    from backend.app.routers import feedback
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t"); monkeypatch.setenv("TELEGRAM_CHAT_ID", "c")
    monkeypatch.setattr(feedback, "_post_telegram", lambda *a: 200)
    headers = {"X-Forwarded-For": "10.9.9.9"}
    for _ in range(feedback.RATE_LIMIT):
        client.post("/feedback", json={"message": "hi"}, headers=headers)

    r = client.post("/feedback", json={"message": "hi"}, headers=headers)

    assert r.status_code == 429
    assert r.json()["detail"] == "feedback_rate_limited"
