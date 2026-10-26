"""
Справочник источников /api/v1/sources.

Главное, что он обязан держать: КАЖДАЯ метка источника, которую отдаёт расчёт,
находится в справочнике. Иначе агент получит в ответе `source_id`, вызовет
`getSource` — и на вопрос «откуда это число» ответит 404 или пересказом по памяти.
Пробы — те же запросы, что в тесте контракта: они проходят все ветки расчёта
(пол и клетки, слои и измеренный UA, панели, характеристика вентилятора, «сейчас»).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from backend.app.core import design_climate, sources
from backend.tests.test_api_v1_contract import CASES, _check, _response_ref

ROOT = Path(__file__).resolve().parents[2]
APP_SRC = {p: p.read_text(encoding="utf-8") for p in (ROOT / "backend/app").rglob("*.py")
           if p.name != "sources.py"}

# Не запись справочника: источник массы профиля — свой у каждого кросса, его
# отдаёт getGrowthProfile (sources.weight)
NOT_IN_CATALOG = {"growth_profile"}


def _source_ids(node, found: set) -> set:
    """Все метки источников в ответе: `source_id` на любой глубине и `sources[].id`."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "source_id" and isinstance(v, str):
                found.add(v)
            elif k == "sources" and isinstance(v, list):
                found |= {s["id"] for s in v if isinstance(s, dict) and "id" in s}
            _source_ids(v, found)
    elif isinstance(node, list):
        for v in node:
            _source_ids(v, found)
    return found


@pytest.fixture(scope="module")
def emitted(client) -> set:
    found: set = set()
    for _, path, body in CASES:
        r = client.post(f"/api/v1{path}", json=body)
        if r.status_code == 201:
            _source_ids(r.json(), found)
    for path in ("/construction-materials", "/housing-systems"):
        _source_ids(client.get(f"/api/v1{path}").json(), found)
    for p in client.get("/api/v1/growth-profiles").json()["data"]:
        if p["builtin"]:
            _source_ids(client.get(f"/api/v1/growth-profiles/{p['id']}").json(), found)
    return found - NOT_IN_CATALOG


def test_probe_reaches_every_branch(emitted):
    # Проба доходит до измеряемого: метки из веток клеток, панелей, вентилятора,
    # слоёв, «сейчас» и профилей — иначе «всё нашлось» значило бы «мало спросили»
    assert {"practice_cage_tunnel_2026", "aarnink_2018", "sanhe_pads", "uga_pad_velocity",
            "amca_210", "br443_2019_s3", "cobb_2021_9_7_age", "effective_temp_table",
            "practice_tunnel_rules_2026", "ross_2025_t2_5", "marcegaglia_dop_100p_2022"} <= emitted


def test_every_emitted_source_is_in_the_catalog(emitted):
    missing = emitted - set(sources.CATALOG)
    assert not missing, f"расчёт ссылается на источники без записи в справочнике: {sorted(missing)}"


def test_catalog_has_no_orphans():
    # Запись, на которую код не ссылается, агент будет пересказывать как основу
    # расчёта, хотя калькулятор её не применяет
    orphans = {sid for sid in sources.CATALOG
               if not any(f'"{sid}"' in src for src in APP_SRC.values())}
    assert not orphans, f"записи справочника, которых нет в коде: {sorted(orphans)}"


def test_core_literals_are_in_the_catalog():
    # Сторож ветвей, до которых пробы не доходят: метка в коде ядра рядом с
    # source_id / source_ids — тоже должна быть в справочнике
    pattern = re.compile(r'source_ids?\s*(?:\|=|=|\.add\()\s*\{?([^)\n}]*)|source_id="([a-z0-9_]+)"')
    literals = set()
    for path, src in APP_SRC.items():
        for m in pattern.finditer(src):
            literals |= set(re.findall(r'"([a-z0-9_]+)"', m.group(0)))
    assert literals, "регулярка ничего не нашла — проба не дошла до кода"
    missing = literals - set(sources.CATALOG) - NOT_IN_CATALOG
    assert not missing, f"метки в коде без записи в справочнике: {sorted(missing)}"


def test_list_matches_contract(client):
    r = client.get("/api/v1/sources")
    assert r.status_code == 200
    _check(r.json(), _response_ref("/sources", "get", 200, r.headers["content-type"]))
    assert {s["id"] for s in r.json()["data"]} == set(sources.CATALOG)


@pytest.mark.parametrize("sid", sorted(sources.CATALOG))
def test_each_source_matches_contract(client, sid):
    r = client.get(f"/api/v1/sources/{sid}")
    assert r.status_code == 200
    _check(r.json(), _response_ref("/sources/{source_id}", "get", 200, r.headers["content-type"]))


def test_unknown_source_is_404_problem(client):
    r = client.get("/api/v1/sources/cobb_2099")
    assert r.status_code == 404
    assert r.json()["code"] == "source_not_found"
    assert r.json()["params"] == {"id": "cobb_2099"}
    _check(r.json(), _response_ref("/sources/{source_id}", "get", 404, r.headers["content-type"]))


def test_citation_in_results_is_the_catalog_citation(client):
    # Одна ссылка на источник везде: в ответе расчёта и в справочнике
    _, path, body = CASES[0]
    for s in client.post(f"/api/v1{path}", json=body).json()["sources"]:
        if s["id"] not in NOT_IN_CATALOG:
            assert s["citation"] == sources.CATALOG[s["id"]].citation
    assert design_climate.SOURCE == sources.CATALOG["era5_open_meteo"].citation


def test_unproven_sources_are_marked():
    # Практика владельца и таблица без первоисточника не должны выглядеть нормой
    assert sources.CATALOG["practice_tunnel_rules_2026"].kind == "practice"
    assert sources.CATALOG["practice_cage_tunnel_2026"].kind == "practice"
    assert sources.CATALOG["effective_temp_table"].kind == "unverified"
    assert all(s.limits for s in sources.CATALOG.values() if s.kind in ("practice", "unverified"))


# Методика температуры встроенного профиля → её запись в справочнике. Кроссы Aviagen —
# Ross табл. 2.5; у Cobb и Hubbard свои методики (breed_climate)
PROFILE_METHOD = {
    "ross308": ("mitchell_by_weight", "ross_2025_t2_5"),
    "ross708": ("mitchell_by_weight", "ross_2025_t2_5"),
    "arbor-acres-plus": ("mitchell_by_weight", "ross_2025_t2_5"),
    "cobb500": ("cobb_rh_density", "cobb_2021_5_2"),
    "hubbard-efficiency-plus": ("hubbard_by_age", "hubbard_2026_app1"),
    "but6-toms": ("aviagen_turkey_by_age", "aviagen_turkey_cl23_t5"),
    "but6-hens": ("aviagen_turkey_by_age", "aviagen_turkey_cl23_t5"),
    "converter-toms": ("hybrid_turkey_by_age", "hybrid_turkey_cmg_p56"),
    "converter-hens": ("hybrid_turkey_by_age", "hybrid_turkey_cmg_p56"),
    "converter-novo-toms": ("hybrid_turkey_by_age", "hybrid_turkey_cmg_p56"),
    "converter-novo-hens": ("hybrid_turkey_by_age", "hybrid_turkey_cmg_p56"),
}


def test_profile_temperature_points_to_its_method():
    # Колонка температуры каждого встроенного кросса ссылается на СВОЮ методику:
    # через source_id агент получает её ограничения. Читаем сами файлы: в
    # тестовом окружении вместо встроенных кроссов — синтетический профиль
    files = sorted((ROOT / "data/growth_profiles/builtin").glob("*.json"))
    assert {f.stem for f in files} == set(PROFILE_METHOD), "новый кросс — назначьте ему методику"
    for f in files:
        climate = json.loads(f.read_text(encoding="utf-8"))["source"]["climate"]
        assert (climate["method"], climate["source_id"]) == PROFILE_METHOD[f.stem], f.name
        assert climate["source_id"] in sources.CATALOG
