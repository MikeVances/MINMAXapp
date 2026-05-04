from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict

APP_CONFIG_PATH = os.getenv("APP_CONFIG_JSON", "data/app_config.json")


@dataclass
class AppConfig:
    # Общий падёж за цикл (1..42 дни), в % (по умолчанию ~4%)
    total_mortality_pct: float = 4.0

    # Единица измерения для норм вентиляции: "per_bird" (м³/ч/бр) или "per_kg" (м³/ч/кг ЖМ)
    ventilation_unit: str = "per_bird"

    # DEPRECATED: старые поля, оставлены для обратной совместимости
    min_floor_unit: str = "per_bird"
    min_floor_0_7: float = 0.15
    min_floor_7_14: float = 0.25
    # Максимальная вентиляция по сезонам (м³/ч на кг живой массы)
    max_per_kg_winter: float = 2.0
    max_per_kg_spring_autumn: float = 3.0
    max_per_kg_summer: float = 4.0
    max_per_kg_tropical: float = 5.0
    # Использовать температурное смешивание режимов (по умолчанию True)
    use_temp_blend: bool = True

    # Температурные точки для смешивания режимов (°C)
    # Используются в calc_core.py для определения режима по температуре
    temp_winter_c: float = -5.0      # Температура зимы (≤ этого значения)
    temp_spring_c: float = 10.0      # Температура весны/осени (середина диапазона)
    temp_summer_c: float = 25.0      # Температура лета (≥ этого значения)

    # Длина производственного цикла (последний день выращивания)
    cycle_days: int = 42

    # Параметры расчёта норм вентиляции из первых принципов (CIGR 1984)
    n_birds_initial: int = 30000         # посадочное поголовье, гол.
    v_tunnel_ms: float = 2.5            # целевая скорость туннеля, м/с
    safety_factor_qmin: float = 1.5     # коэффициент запаса к CO₂-расчёту q_min

    # Ограничения туннельного режима вентиляции
    tunnel_min_day: int = 14            # минимальный возраст (дней) для включения туннеля
    tunnel_min_temp_c: float = 18.0     # минимальная наружная температура для туннеля (°C)


def load_app_config(path: str = APP_CONFIG_PATH) -> AppConfig:
    if not os.path.exists(path):
        return AppConfig()
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        # Back-compat: если раньше хранили daily_mortality_pct
        if raw and "daily_mortality_pct" in raw and "total_mortality_pct" not in raw:
            # Преобразуем условно, как 0.1%/сутки ≈ 4% за цикл
            daily = float(raw.get("daily_mortality_pct", 0)) / 100.0
            total = 1.0 - (1.0 - daily) ** 41
            raw["total_mortality_pct"] = round(total * 100.0, 4)
        defaults = asdict(AppConfig())
        return AppConfig(**{**defaults, **(raw or {})})
    except Exception:
        return AppConfig()


def save_app_config(cfg: AppConfig, path: str = APP_CONFIG_PATH) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(asdict(cfg), f, ensure_ascii=False, indent=2)
