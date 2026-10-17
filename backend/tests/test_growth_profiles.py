"""
Библиотека профилей роста (решение 2026-10-16: выбор кросса + свои профили).

Встроенные профили производителей только читаются; пользователь копирует кросс,
правит и сохраняет под своим id. Расчёт идёт по выбранному профилю.
"""
from __future__ import annotations

import shutil

import pytest

from backend.app.core.growth_profiles import GROWTH_PROFILES_DIR

BUILTIN_ID = "test-breed"   # синтетический встроенный профиль из conftest
CUSTOM_ID = "my-farm-ross"

CUSTOM_PROFILE = {
    "name": "Моя площадка",
    "breed": "Ross 308",
    "points": [
        {"day": 1,  "body_weight_g": 45.0,   "min_temp_c": 32.0, "rv_percent": 60.0},
        {"day": 21, "body_weight_g": 900.0,  "min_temp_c": 24.0, "rv_percent": 60.0},
        {"day": 42, "body_weight_g": 2700.0, "min_temp_c": 19.0, "rv_percent": 60.0},
    ],
}


@pytest.fixture(autouse=True)
def clean_custom_profiles():
    yield
    shutil.rmtree(GROWTH_PROFILES_DIR / "custom", ignore_errors=True)


# ─── Чтение ───────────────────────────────────────────────────────────────────

def test_list_contains_builtin_profile(client):
    profiles = {p["id"]: p for p in client.get("/profiles").json()}

    assert profiles[BUILTIN_ID]["builtin"] is True
    assert profiles[BUILTIN_ID]["first_day"] == 1
    assert profiles[BUILTIN_ID]["last_day"] == 42


def test_get_profile_returns_daily_interpolation_and_qmin_norm(client):
    """
    Д.10 между д.1 (50 г) и д.21 (1012 г): 50 + 962 × 9/20 = 482.9 г.
    Норма Qmin д.21 — та же формула, что в расчёте: 0.946 м³/ч·гол (см. golden).
    """
    body = client.get(f"/profiles/{BUILTIN_ID}").json()
    days = {d["day"]: d for d in body["days"]}

    assert sorted(days) == list(range(1, 43))
    assert days[10]["body_weight_g"] == pytest.approx(482.9)
    assert days[21]["q_min_per_bird"] == pytest.approx(0.946)
    assert len(body["points"]) == 4   # исходные точки отдаются как есть


def test_unknown_profile_is_404(client):
    assert client.get("/profiles/no-such-breed").status_code == 404


def test_profile_id_with_path_characters_is_rejected(client):
    """id становится именем файла — точки и заглавные буквы не допускаются."""
    assert client.get("/profiles/Bad.Id").status_code == 422


# ─── Пользовательские профили ─────────────────────────────────────────────────

def test_custom_profile_roundtrip(client):
    r = client.put(f"/profiles/{CUSTOM_ID}", json=CUSTOM_PROFILE)
    assert r.status_code == 200

    listed = {p["id"]: p for p in client.get("/profiles").json()}
    assert listed[CUSTOM_ID]["builtin"] is False
    assert listed[CUSTOM_ID]["name"] == "Моя площадка"

    days = {d["day"]: d for d in client.get(f"/profiles/{CUSTOM_ID}").json()["days"]}
    assert days[21]["body_weight_g"] == 900.0

    # Запись атомарная: временных файлов не остаётся
    assert not list((GROWTH_PROFILES_DIR / "custom").glob("*.tmp"))


def test_builtin_profile_cannot_be_overwritten(client):
    before = client.get(f"/profiles/{BUILTIN_ID}").json()

    r = client.put(f"/profiles/{BUILTIN_ID}", json=CUSTOM_PROFILE)

    assert r.status_code == 403
    assert client.get(f"/profiles/{BUILTIN_ID}").json() == before


def test_builtin_profile_cannot_be_deleted(client):
    assert client.delete(f"/profiles/{BUILTIN_ID}").status_code == 403
    assert client.get(f"/profiles/{BUILTIN_ID}").status_code == 200


def test_custom_profile_delete(client):
    client.put(f"/profiles/{CUSTOM_ID}", json=CUSTOM_PROFILE)

    assert client.delete(f"/profiles/{CUSTOM_ID}").status_code == 200
    assert client.get(f"/profiles/{CUSTOM_ID}").status_code == 404
    assert client.delete(f"/profiles/{CUSTOM_ID}").status_code == 404


def test_custom_file_cannot_declare_itself_builtin(client):
    """Признак «встроенный» определяется каталогом, а не содержимым файла."""
    path = GROWTH_PROFILES_DIR / "custom" / f"{CUSTOM_ID}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"name": "x", "builtin": true, "points": [{"day": 1, "body_weight_g": 40}]}',
                    encoding="utf-8")

    listed = {p["id"]: p for p in client.get("/profiles").json()}
    assert listed[CUSTOM_ID]["builtin"] is False
    assert client.delete(f"/profiles/{CUSTOM_ID}").status_code == 200


@pytest.mark.parametrize(
    "points, reason",
    [
        ([{"day": 1, "body_weight_g": 40}, {"day": 1, "body_weight_g": 50}], "повтор дня"),
        ([{"day": 1, "body_weight_g": 40}, {"day": 7, "min_temp_c": 30}], "одна точка с массой"),
    ],
)
def test_invalid_points_are_rejected(client, points, reason):
    r = client.put(f"/profiles/{CUSTOM_ID}", json={"name": "x", "points": points})

    assert r.status_code == 422, reason


# ─── Расчёт по выбранному профилю ─────────────────────────────────────────────

_CALC = dict(house="1", birds=10_000, age_days=21, outside_t=25.0, outside_rh=60.0)


def test_calc_uses_selected_profile(client):
    client.put(f"/profiles/{CUSTOM_ID}", json=CUSTOM_PROFILE)

    default = client.post("/calc/minmax", json=_CALC).json()
    custom = client.post("/calc/minmax", json={**_CALC, "growth_profile_id": CUSTOM_ID}).json()

    assert default["weight_used_g"] == 1012.0
    assert default["growth_profile_id"] == BUILTIN_ID
    assert custom["weight_used_g"] == 900.0
    assert custom["growth_profile_id"] == CUSTOM_ID


def test_calc_with_unknown_profile_is_404_not_silent_fallback(client):
    r = client.post("/calc/minmax", json={**_CALC, "growth_profile_id": "no-such-breed"})

    assert r.status_code == 404


# ─── Источник профиля: структура вместо текста на одном языке ─────────────────

def test_builtin_profile_sources_are_structured_and_language_neutral():
    """
    Подпись источника встроенного профиля собирает клиент на языке интерфейса,
    поэтому в данных — только поля (ref/page/url …) без фраз на русском.
    """
    import json
    import re
    from pathlib import Path

    builtin_dir = Path(__file__).resolve().parents[2] / "data" / "growth_profiles" / "builtin"
    files = sorted(builtin_dir.glob("*.json"))
    assert files, builtin_dir

    for path in files:
        source = json.loads(path.read_text(encoding="utf-8"))["source"]
        assert isinstance(source["weight"], dict) and {"ref", "page", "url"} <= source["weight"].keys(), path.name
        assert isinstance(source["climate"], dict) and {"ref", "table", "page", "url"} <= source["climate"].keys(), path.name
        assert not re.search(r"[А-Яа-яЁё]", json.dumps(source, ensure_ascii=False)), path.name


def test_custom_profile_source_accepts_structured_and_plain_values(client):
    """API принимает и структурированный источник, и свободный текст, и отдаёт их как есть."""
    source = {
        "weight": {"ref": "Farm scales 2026", "page": 1, "url": "https://example.org/w.pdf"},
        "notes": "free text",
        "copied_from": "ross308",
    }
    r = client.put(f"/profiles/{CUSTOM_ID}", json={**CUSTOM_PROFILE, "source": source})

    assert r.status_code == 200, r.json()
    assert client.get(f"/profiles/{CUSTOM_ID}").json()["source"] == source
