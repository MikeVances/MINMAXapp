"""
Нормы руководств по родительскому стаду бройлеров (напольное содержание), которые
не выводятся из физики: минимальная вентиляция производителя (Ross PS Table 25),
доля петухов в продуктивном периоде, проектная скорость тоннеля по этапам
и верхние границы плотности посадки.

Первоисточники — refs/breeders/ (локально), пересказ и ограничения — core/sources.py.
Решения владельца по пробелам источников — 2026-11-03.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# ─── Этапы выращивания и содержания ──────────────────────────────────────────

# Ремонтный молодняк (0–20 нед = 1–140 дн) и продуктивный период (с 21 нед = 141 дн
# до выбраковки: 64 нед = 448 дн у Ross 308 PS, 65 нед = 455 дн у Cobb 500 FF / MX)
REARING = "rearing"
PRODUCTION = "production"
STAGES = (REARING, PRODUCTION)
REARING_LAST_DAY = 140


# ─── Минимальная вентиляция производителя (Ross PS Table 25) ─────────────────

# Aviagen, Ross Parent Stock Management Handbook 2023, Table 25, с. 113:
# «Minimum ventilation rates (per bird) for temperatures below -5°C (23°F)»
# У Cobb Breeder Management Guide 2021 таблицы минимальной вентиляции на голову
# по массе нет (с. 118 даёт только установленную мощность 18–36.6 м³/ч·м² и расчёт
# по влаго- и газовому балансу), поэтому у Cobb min_vent_norm = None
ROSS_PS_TABLE25 = "ross_ps_table25"

GUIDE_NORM_SOURCE = {
    ROSS_PS_TABLE25: "ross_ps_2023_t25",
}

# (масса, кг, м³/ч на голову) — все 31 строка Table 25 дословно
TABLE25_WEIGHT_M3H: list[tuple[float, float]] = [
    (0.05, 0.09),
    (0.10, 0.15),
    (0.20, 0.26),
    (0.30, 0.35),
    (0.40, 0.43),
    (0.50, 0.51),
    (0.60, 0.59),
    (0.70, 0.66),
    (0.80, 0.73),
    (0.90, 0.80),
    (1.00, 0.86),
    (1.20, 0.99),
    (1.40, 1.11),
    (1.60, 1.23),
    (1.80, 1.34),
    (2.00, 1.45),
    (2.20, 1.56),
    (2.40, 1.67),
    (2.60, 1.77),
    (2.80, 1.87),
    (3.00, 1.97),
    (3.20, 2.07),
    (3.40, 2.16),
    (3.60, 2.26),
    (3.80, 2.35),
    (4.00, 2.44),
    (4.20, 2.53),
    (4.40, 2.62),
    (4.60, 2.71),
    (4.80, 2.80),
    (5.00, 2.89),
]


def table25_per_bird_m3h(weight_kg: float) -> float:
    """Норма минвентиляции Ross PS Table 25 на одну птицу, м³/ч (линейная интерполяция)."""
    pts = TABLE25_WEIGHT_M3H
    if weight_kg <= pts[0][0]:
        return pts[0][1]
    if weight_kg >= pts[-1][0]:
        return pts[-1][1]
    for (w0, q0), (w1, q1) in zip(pts, pts[1:]):
        if w0 <= weight_kg <= w1:
            t = (weight_kg - w0) / (w1 - w0)
            return q0 + t * (q1 - q0)
    return pts[-1][1]


def guide_min_vent_m3h(norm: str, birds: float, weight_kg: float) -> float:
    """Минимальная вентиляция корпуса по норме производителя родительского стада, м³/ч."""
    if norm == ROSS_PS_TABLE25:
        return birds * table25_per_bird_m3h(weight_kg)
    raise ValueError(f"unknown min_vent_norm: {norm}")


# ─── Тоннель ─────────────────────────────────────────────────────────────────

# Cobb Breeder Management Guide 2021, с. 123: ремонтный молодняк (pullet houses)
# 2.0–2.5 м/с, продуктивный период (breeder houses in production) 2.5–3.0 м/с;
# Ross PS Management Handbook 2023, с. 172: проектная скорость в продуктивном
# корпусе 3.0 м/с. Решение владельца 2026-11-03 — верхняя граница по этапу
TUNNEL_SPEED_MS = {
    REARING: 2.5,
    PRODUCTION: 3.0,
}
TUNNEL_SOURCE = "cobb_breeder_2021_tunnel"


# ─── Доля петухов в продуктивном корпусе (напольное совместное содержание) ───

# Ross PS Management Handbook 2023, Table 18, с. 66: «Typical mating ratios for good
# quality males across the production period» (Males per 100 Females). Берём верхнюю
# границу диапазона — консервативно для вентиляции и тепла:
#   22–24 нед (до 168 дн): 9.25–10.00 % → 10.0 %
#   24–30 нед (169–210 дн): 8.50–9.50 % → 9.5 %
#   30–35 нед (211–245 дн): 8.00–8.50 % → 8.5 %
#   35–40 нед (246–280 дн): 7.50–8.00 % → 8.0 %
#   40–50 нед (281–350 дн): 7.00–7.50 % → 7.5 %
#   50 нед — выбраковка (>350 дн): 6.50–7.00 % → 7.0 %
ROSS_MALE_SHARE_BY_DAY: list[tuple[int, float]] = [
    (168, 0.100),
    (210, 0.095),
    (245, 0.085),
    (280, 0.080),
    (350, 0.075),
]
ROSS_MALE_SHARE_LATE = 0.070
ROSS_MALES_PROFILE_ID = "ross308-ps-males"
ROSS_MALES_SOURCE = "ross_ps_2023_t18"

# Cobb Breeder Management Guide 2021, с. 51: «8 to 9 % males in slatted houses and
# 9 to 10 % males in deep litter houses» — верхняя граница 10.0 % на весь период
COBB_MALE_SHARE = 0.100
COBB_MALES_PROFILE_ID = "cobb-mx-males"
COBB_MALES_SOURCE = "cobb_breeder_2021_males"


def _is_ross_breeder(profile) -> bool:
    norm = getattr(profile, "min_vent_norm", None)
    if norm == ROSS_PS_TABLE25:
        return True
    pid = (getattr(profile, "id", "") or "").lower()
    breed = (getattr(profile, "breed", "") or "").lower()
    return "ross" in pid or "ross" in breed


def ross_male_share(age_days: int) -> float:
    """Верхняя граница доли петухов Ross PS Table 18 (петухов на одну курицу)."""
    for last_day, share in ROSS_MALE_SHARE_BY_DAY:
        if age_days <= last_day:
            return share
    return ROSS_MALE_SHARE_LATE


def production_males(profile, age_days: int) -> Optional[tuple[str, float, str]]:
    """
    Автодобавление петухов к женскому профилю в продуктивном периоде:
    возвращает (id мужского профиля, доля петухов от кур, source_id) или None.
    """
    if getattr(profile, "species", None) != "broiler_breeder":
        return None
    if getattr(profile, "sex", None) != "female":
        return None
    if _is_ross_breeder(profile):
        return (ROSS_MALES_PROFILE_ID, ross_male_share(age_days), ROSS_MALES_SOURCE)
    return (COBB_MALES_PROFILE_ID, COBB_MALE_SHARE, COBB_MALES_SOURCE)


# ─── Плотность посадки (верхняя граница руководств, гол/м²) ──────────────────

# Ross PS Management Handbook 2023:
#   Table 7, с. 30 (rearing, 15–140 days): Males 3–4 birds/m², Females 4–8 birds/m²
#   Table 14, с. 49 (production, 140 days to depletion): Males and Females 4.5–5.5 birds/m²
# Cobb Breeder Management Guide 2021 & Cobb MX Male Supplement 2026:
#   с. 20 (rearing): Females 7–10 birds/m² (dark-out), Males 3.1–3.6 birds/m² (MX supp с. 2)
#   с. 49 (production): 5–7 birds/m²
@dataclass(frozen=True)
class DensityLimit:
    head_per_m2: float
    source_id: str


def density_limit(profile, stage: str) -> Optional[DensityLimit]:
    """Верхний предел плотности посадки родительского стада по кроссу и этапу, гол/м²."""
    sex = getattr(profile, "sex", None)
    if _is_ross_breeder(profile):
        if stage == REARING:
            limit = 4.0 if sex == "male" else 8.0
        else:
            limit = 5.5
        return DensityLimit(limit, "ross_ps_2023_density")
    if stage == REARING:
        limit = 3.6 if sex == "male" else 10.0
    else:
        limit = 7.0
    return DensityLimit(limit, "cobb_breeder_2021_density")
