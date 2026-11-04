"""
Направления производства — как их различают на птицефабриках: бройлеры на полу и в
клетках, родительские стада, промышленное стадо несушек, индейка, утка.

Почему справочник, а не просто вид птицы профиля: направление задаёт сразу и вид
птицы (какие профили роста к нему подходят), и способ содержания (подстилка или
клеточные батареи). Корпус в интерфейсе выбирает направление, а список профилей
роста фильтруется по его виду — бройлерный профиль не попадёт в корпус индейки.

Готовность честно разная: часть направлений считается в интерфейсе, клетки бройлеров —
пока только в проектном расчёте API v1, остальные ждут источников (сбор 2026-10-28,
решения владельца — тепло по CIGR 2002, РД-АПК только для сверки). Неготовое
направление видно в списке, но выбрать его нельзя: пустой расчёт выглядел бы как готовый.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# ready   — считается в интерфейсе (вентиляционный профиль)
# api     — считается только в проектном расчёте API v1, в интерфейсе ещё нет полей
# planned — источники собраны или ищутся, расчёта нет
Status = Literal["ready", "api", "planned"]


@dataclass(frozen=True)
class ProductionLine:
    id: str
    species: str        # вид птицы профиля роста: по нему фильтруется список профилей
    housing: str        # floor_litter | cages — как в API v1 (flock.housing)
    status: Status


# Порядок — как в списке интерфейса: от готового к планируемому
LINES: tuple[ProductionLine, ...] = (
    ProductionLine("broiler_floor",          "broiler",         "floor_litter", "ready"),
    ProductionLine("turkey",                 "turkey",          "floor_litter", "ready"),
    ProductionLine("broiler_breeders_floor", "broiler_breeder", "floor_litter", "ready"),
    ProductionLine("broiler_cages",          "broiler",         "cages",        "ready"),
    ProductionLine("layers_cages",           "layer",           "cages",        "ready"),
    ProductionLine("layer_breeders_cages",   "layer_breeder",   "cages",        "planned"),
    ProductionLine("duck",                   "duck",            "floor_litter", "planned"),
)

# Корпус без направления (сохранён до 2026-10-28) — бройлеры на полу: другого
# интерфейс тогда не считал
DEFAULT_LINE = "broiler_floor"
