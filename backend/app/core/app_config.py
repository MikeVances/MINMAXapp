from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, fields

from .json_store import atomic_write_json
from .survival import daily_mortality_to_total
from .paths import data_path

logger = logging.getLogger(__name__)

APP_CONFIG_PATH = str(data_path("APP_CONFIG_JSON", "data/app_config.json"))


@dataclass
class AppConfig:
    # Общий падёж за цикл, % (по умолчанию ~4 %)
    total_mortality_pct: float = 4.0

    # Длина производственного цикла (последний день выращивания)
    cycle_days: int = 42

    # Профиль роста по умолчанию (id из библиотеки data/growth_profiles)
    default_growth_profile: str = "ross308"

    # Параметры расчёта из первых принципов (CIGR 1984)
    v_tunnel_ms: float = 2.5            # целевая скорость туннеля, м/с
    safety_factor_qmin: float = 1.5     # коэффициент запаса к CO₂-расчёту q_min

    # Ограничения туннельного режима вентиляции
    tunnel_min_day: int = 14            # минимальный возраст (дней) для включения туннеля
    tunnel_min_temp_c: float = 18.0     # минимальная наружная температура для туннеля (°C)

    # Высота фермы над уровнем моря, м — давление площадки (psychro.site_pressure_pa)
    altitude_m: float = 0.0


def load_app_config(path: str = APP_CONFIG_PATH) -> AppConfig:
    if not os.path.exists(path):
        return AppConfig()
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f) or {}
        # Back-compat: если раньше хранили daily_mortality_pct
        if "daily_mortality_pct" in raw and "total_mortality_pct" not in raw:
            total = daily_mortality_to_total(
                float(raw.get("daily_mortality_pct", 0)), int(raw.get("cycle_days", 42))
            )
            raw["total_mortality_pct"] = round(total, 4)

        # Устаревшие ключи (сезонный режим, min_floor_*, n_birds_initial …) отбрасываем.
        # Без этого AppConfig(**raw) падал бы на старом файле, и конфиг молча
        # откатывался на умолчания — вместе с падежом и длиной цикла
        known = {f.name for f in fields(AppConfig)}
        obsolete = sorted(set(raw) - known)
        if obsolete:
            logger.info("app_config: устаревшие ключи пропущены: %s", ", ".join(obsolete))
        return AppConfig(**{k: v for k, v in raw.items() if k in known})
    except Exception:
        # Битый конфиг: работаем на умолчаниях, но не молча
        logger.exception("app_config не читается: %s — используются значения по умолчанию", path)
        return AppConfig()


def save_app_config(cfg: AppConfig, path: str = APP_CONFIG_PATH) -> None:
    atomic_write_json(path, asdict(cfg))
