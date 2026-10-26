"""
Нормы руководств по индейке, которые не выводятся из физики: минимальная вентиляция
производителя, тоннель, установленная мощность минвентиляции и плотность посадки.

Почему отдельно от бройлерных норм (ventilation_design, breed_climate): у индейки
другие производители и другие единицы — Aviagen задаёт минимум на кг живой массы,
Hybrid — на голову по неделям возраста, плотность — в головах на м², а не в кг/м².
Сведённые в одну таблицу с бройлерными, эти числа выглядели бы сопоставимыми,
а они нет.

Первоисточники — refs/turkey/ (локально), пересказ и ограничения — core/sources.py.
Решения владельца по пробелам источников — 2026-10-26.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional


# ─── Минимальная вентиляция производителя ────────────────────────────────────

# Aviagen Turkeys CL23 V4, с. 30: «a constant minimum ratio of 1m3 of air /kg live
# weight/hour. This is applicable throughout the production cycle»
AVIAGEN_PER_KG = "aviagen_turkey_per_kg"
AVIAGEN_M3H_PER_KG = 1.0

# Hybrid CMG 2023, с. 46 «Air renewal depending on the density of animals»: 1-я неделя
# 0.17 м³/ч на индейку (плотность > 10 гол/м²) или 1.7 м³/ч на м² (< 10 гол/м²),
# 2-я — вдвое, 3-я — втрое, «etc.»; с. 68: «1.7 m3/h/m²/week of age»
HYBRID_PER_WEEK = "hybrid_turkey_per_week"
HYBRID_M3H_PER_HEAD_WEEK = 0.17
HYBRID_M3H_PER_M2_WEEK = 1.7
HYBRID_DENSITY_SPLIT_HEAD_M2 = 10.0

GUIDE_NORM_SOURCE = {
    AVIAGEN_PER_KG: "aviagen_turkey_cl23_min_vent",
    HYBRID_PER_WEEK: "hybrid_turkey_cmg_p46",
}


def week_of_age(age_days: int) -> int:
    """Неделя возраста: дни 1–7 — 1-я неделя, 8–14 — 2-я (как строки таблиц)."""
    return max(1, math.ceil(age_days / 7))


def guide_min_vent_m3h(norm: str, birds: float, weight_kg: float, age_days: int,
                       floor_m2: Optional[float]) -> float:
    """
    Минимальная вентиляция корпуса по норме производителя, м³/ч.

    Hybrid: по площади, когда посадка редкая (< 10 гол/м²), иначе на голову — как в
    таблице. Площадь не известна (интерфейс без размеров, клетки) — на голову: у
    редкой посадки это меньше, чем по площади, то есть минимум не завышаем выдумкой.
    """
    if norm == AVIAGEN_PER_KG:
        return AVIAGEN_M3H_PER_KG * weight_kg * birds
    if norm == HYBRID_PER_WEEK:
        week = week_of_age(age_days)
        if floor_m2 and birds / floor_m2 < HYBRID_DENSITY_SPLIT_HEAD_M2:
            return HYBRID_M3H_PER_M2_WEEK * week * floor_m2
        return HYBRID_M3H_PER_HEAD_WEEK * week * birds
    # Код нормы из файла профиля, которого код не знает, — ошибка данных, а не «нормы нет»
    raise ValueError(f"unknown min_vent_norm: {norm}")


# ─── Тоннель ─────────────────────────────────────────────────────────────────

# Hybrid CMG 2023, с. 51: «An air speed of 2 m/s (approximately 7 kph) reduces
# perceived temperature by 6 to 10°C», расход VP = S × A × 3600. Это иллюстрация,
# а не норма; другой цифры у индюшиных источников нет (Aviagen — только график
# wind chill). Решение владельца 2026-10-26: проектная скорость 2 м/с
TUNNEL_SPEED_MS = 2.0
TUNNEL_SOURCE = "hybrid_turkey_cmg_p51"


# ─── Установленная мощность минвентиляции ────────────────────────────────────

# Hybrid Ventilation Calculator Metric v28032022: «Hybrid recommends a minimum of
# 18.3 m3h/m2 for brooders»; справочно Finish 27.5 м³/ч·м² (там же, со ссылкой на
# Czarick, UGA). Решение владельца 2026-10-26 — по типу корпуса
BROODER = "brooder"
GROW_OUT = "grow_out"
STAGES = (BROODER, GROW_OUT)
MIN_VENT_INSTALLED_M3H_M2 = {BROODER: 18.3, GROW_OUT: 27.5}
MIN_VENT_INSTALLED_SOURCE = "hybrid_turkey_ventcalc"


# ─── Плотность посадки ───────────────────────────────────────────────────────

# Aviagen CL23 V4, с. 13 («brood and move»): в брудерном корпусе не больше
# «8–10 birds/m²», на откорме «2.8–3.2 males/m2 or 5–6 females/m2». Предел —
# ВЕРХНЯЯ граница диапазона: предупреждаем, когда плотнее, чем допускает руководство
@dataclass(frozen=True)
class DensityLimit:
    head_per_m2: float
    source_id: str = "aviagen_turkey_cl23_density"


def density_limit(stage: str, sex: Optional[str]) -> Optional[DensityLimit]:
    """Предел плотности; None — руководство его не даёт (смешанное стадо на откорме)."""
    if stage == BROODER:
        return DensityLimit(10.0)
    if sex == "male":
        return DensityLimit(3.2)
    if sex == "female":
        return DensityLimit(6.0)
    return None
