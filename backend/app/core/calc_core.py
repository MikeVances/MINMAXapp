from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

from .profile_loader import VentProfile, Mode, ProfilePoint
from .day_master import load_day_master
from .app_config import load_app_config


DisplayUnit = Literal["per_bird", "per_kg"]


@dataclass
class CalcInput:
    birds: int
    age_days: int
    mode: Mode
    display_unit: DisplayUnit
    outside_t: float  # °C
    heater_on: bool = False


@dataclass
class CalcResult:
    q_min_m3h: float
    q_max_m3h: float
    basis_used: DisplayUnit
    weight_used_g: float
    profile_day_resolved: int
    rates_per_bird_min: float
    rates_per_bird_max: float
    rates_per_kg_min: float
    rates_per_kg_max: float
    min_temp_c: Optional[float] = None
    rv_percent: Optional[float] = None


def compute(profile: VentProfile, ci: CalcInput) -> CalcResult:
    # Посуточный режим (floor по дню) + интерполяция по температуре наружного воздуха
    # Три опорных режима: winter (<=0°C), spring_autumn (0..15°C), summer (>=15°C)
    p_w = profile.get_point("winter", ci.age_days, strategy="floor")
    p_m = profile.get_point("spring_autumn", ci.age_days, strategy="floor")
    p_s = profile.get_point("summer", ci.age_days, strategy="floor")

    t = ci.outside_t
    if t <= 0:
        p = p_w
    elif t >= 15:
        p = p_s
    else:
        # линейная смесь между spring_autumn (при 0°C) и summer (при 15°C)
        alpha = (t - 0.0) / 15.0
        def lerp(x: float, y: float) -> float:
            return x + (y - x) * alpha
        p = ProfilePoint(
            day=ci.age_days,
            body_weight_g=p_m.body_weight_g,  # вес одинаков в рамках того же дня
            min_per_bird=lerp(p_m.min_per_bird, p_s.min_per_bird),
            max_per_bird=lerp(p_m.max_per_bird, p_s.max_per_bird),
            min_per_kg=lerp(p_m.min_per_kg, p_s.min_per_kg),
            max_per_kg=lerp(p_m.max_per_kg, p_s.max_per_kg),
            min_temp_c=p_m.min_temp_c,
            rv_percent=p_m.rv_percent,
        )

    # Override из Day Master (если задан) — вес/уставки на конкретный день
    dm = load_day_master()
    if dm and ci.age_days in dm:
        info = dm[ci.age_days]
        if info.body_weight_g is not None:
            p.body_weight_g = info.body_weight_g
        if info.min_temp_c is not None:
            p.min_temp_c = info.min_temp_c
        if info.rv_percent is not None:
            p.rv_percent = info.rv_percent
    weight_kg = max(p.body_weight_g / 1000.0, 0.0001)

    # Эффективное количество птиц с учётом суточной смертности
    cfg = load_app_config()
    # Рассчитываем эквивалентную суточную смертность так, чтобы к 42 дню общий падёж был total_mortality_pct
    total_m = max(cfg.total_mortality_pct, 0.0) / 100.0
    daily_m = 1.0 - (1.0 - total_m) ** (1.0 / max(41, 1))
    # выживаемость в конкретный день (день 1 → множитель 1.0)
    survival = (1.0 - daily_m) ** max(ci.age_days - 1, 0)
    birds_eff = ci.birds * survival

    per_bird_min = p.min_per_bird
    per_bird_max = p.max_per_bird
    per_kg_min = p.min_per_kg
    per_kg_max = p.max_per_kg

    # Учёт метаболической массы для минимальной вентиляции: W^0.75
    try:
        if per_kg_min and float(per_kg_min) > 0:
            per_bird_from_kg = float(per_kg_min) * (weight_kg ** 0.75)
            if per_bird_from_kg > per_bird_min:
                per_bird_min = per_bird_from_kg
    except Exception:
        pass

    # Минимальная вентиляция — нижние пороги (per broiler) из правил 0–7 и 7–14
    if ci.age_days <= 7:
        per_bird_min = max(per_bird_min, cfg.min_floor_0_7)
    elif ci.age_days <= 14:
        per_bird_min = max(per_bird_min, cfg.min_floor_7_14)

    # Коррекция отопления (если включено): добавка к min per broiler
    if ci.heater_on:
        if ci.age_days <= 14:
            per_bird_min += 0.10
        elif ci.age_days <= 28:
            per_bird_min += 0.05
        else:
            per_bird_min += 0.025

    # Qmin всегда считаем по эффективной ставке per broiler (после порогов/коррекций)
    q_min = birds_eff * per_bird_min

    # Qmax — по сезонной формуле Excel: фиксированная ставка м³/ч на кг живой массы
    season_factor = {
        "winter": getattr(cfg, "max_per_kg_winter", 2.0),
        "spring_autumn": getattr(cfg, "max_per_kg_spring_autumn", 3.0),
        "summer": getattr(cfg, "max_per_kg_summer", 4.0),
        "tropical": getattr(cfg, "max_per_kg_tropical", 5.0),
    }.get(ci.mode, getattr(cfg, "max_per_kg_summer", 4.0))
    total_kg = birds_eff * weight_kg
    q_max = total_kg * season_factor
    basis = "per_bird"

    return CalcResult(
        q_min_m3h=float(q_min),
        q_max_m3h=float(q_max),
        basis_used=basis, 
        weight_used_g=p.body_weight_g,
        profile_day_resolved=p.day,
        rates_per_bird_min=per_bird_min,
        rates_per_bird_max=per_bird_max,
        rates_per_kg_min=per_kg_min,
        rates_per_kg_max=per_kg_max,
        min_temp_c=p.min_temp_c,
        rv_percent=p.rv_percent,
    )
