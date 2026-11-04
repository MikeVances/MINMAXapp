"""
Справочник направлений производства (2026-10-28): корпус выбирает направление,
калькулятор показывает профили роста только его вида птицы.
"""
from __future__ import annotations

import json
from pathlib import Path

from backend.app.core.production_lines import DEFAULT_LINE, LINES

# Встроенные профили репозитория — те, что уходят на площадку. Тестовый каталог
# профилей (conftest) содержит один бройлерный и для этой проверки не годится
SHIPPED = Path(__file__).resolve().parents[2] / "data" / "growth_profiles" / "builtin"


def test_endpoint_lists_every_line(client):
    j = client.get("/settings/production-lines").json()
    assert j["default"] == DEFAULT_LINE
    assert [l["id"] for l in j["lines"]] == [l.id for l in LINES]
    assert len({l.id for l in LINES}) == len(LINES)


def test_default_line_is_ready():
    # Корпус без направления получает умолчание — оно обязано считаться
    assert next(l for l in LINES if l.id == DEFAULT_LINE).status == "ready"


def test_every_ready_line_has_builtin_profiles():
    # Готовое направление с пустым списком профилей — калькулятор нечем считать
    builtin_species = {json.loads(f.read_text(encoding="utf-8")).get("species", "broiler")
                       for f in SHIPPED.glob("*.json")}
    assert builtin_species, SHIPPED
    for line in LINES:
        if line.status == "ready":
            assert line.species in builtin_species, line.id


def test_ready_and_planned_lines():
    # Готовы: бройлер (пол и клетки), индейка (пол), родители бройлеров (пол) и несушка (клетки).
    # В плане остаются: родители несушек в клетках и утка на полу
    ready_ids = {l.id for l in LINES if l.status == "ready"}
    planned_ids = {l.id for l in LINES if l.status == "planned"}
    assert ready_ids == {
        "broiler_floor",
        "broiler_cages",
        "turkey",
        "broiler_breeders_floor",
        "layers_cages",
    }
    assert planned_ids == {"layer_breeders_cages", "duck"}
