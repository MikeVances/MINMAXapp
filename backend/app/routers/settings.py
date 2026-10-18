from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..api_errors import api_error
from ..write_access import require_write_token
from ..core.app_config import AppConfig, load_app_config, save_app_config
from ..core.growth_profiles import ProfileNotFound, load_profile


router = APIRouter()


# ---- App config (mortality etc.) ----
class AppCfg(BaseModel):
    """Настройки хозяйства (см. core/app_config.AppConfig — поля совпадают)."""
    total_mortality_pct: float = Field(4.0, ge=0, le=100)

    # Длина производственного цикла
    cycle_days: int = Field(42, ge=21, le=56)

    # Профиль роста по умолчанию (id из библиотеки /profiles)
    default_growth_profile: str = Field("ross308", pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")

    # Параметры расчёта из первых принципов (CIGR 1984)
    v_tunnel_ms: float = Field(2.5, ge=0.5, le=5.0)
    safety_factor_qmin: float = Field(1.5, ge=1.0, le=3.0)

    # Ограничения туннельного режима
    tunnel_min_day: int = Field(14, ge=1, le=42)
    tunnel_min_temp_c: float = Field(18.0, ge=0.0, le=35.0)


@router.get("/app-config", response_model=AppCfg)
def get_app_cfg():
    """Получить настройки хозяйства."""
    return AppCfg(**asdict(load_app_config()))


@router.put("/app-config", response_model=AppCfg, dependencies=[Depends(require_write_token)])
def put_app_cfg(payload: AppCfg):
    """Сохранить настройки хозяйства."""
    # Профиль по умолчанию берут все расчёты главной, где корпус не выбрал свой.
    # Несуществующий id сохранялся с ответом 200 — и после этого каждый расчёт
    # у каждого посетителя отвечал 404 profile_not_found, пока кто-то не исправит
    try:
        load_profile(payload.default_growth_profile)
    except ProfileNotFound:
        raise api_error(422, "profile_not_found", id=payload.default_growth_profile)
    save_app_config(AppConfig(**payload.model_dump()))
    return payload
