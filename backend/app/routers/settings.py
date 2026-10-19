from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends
from typing import Optional

from pydantic import BaseModel, Field

from ..api_errors import api_error
from ..write_access import require_write_token
from ..core.app_config import AppConfig, load_app_config, save_app_config
from ..core.growth_profiles import ProfileNotFound, load_profile
from ..core.design_climate import design_conditions, fetch_hourly
from ..core.errors import CalcError
from ..api_errors import from_calc_error


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
    # По умолчанию — практика птицеводов: с 21-го дня, снаружи не ниже 24 °C
    tunnel_min_day: int = Field(21, ge=1, le=42)
    tunnel_min_temp_c: float = Field(24.0, ge=0.0, le=35.0)

    # Высота над уровнем моря: на 1000 м воздух на 11 % реже (ASHRAE, станд. атмосфера)
    altitude_m: float = Field(0.0, ge=0.0, le=4000.0)

    # Координаты и расчётные условия: пишет POST /settings/design-climate, PUT сохраняет как есть
    latitude: Optional[float] = Field(None, ge=-90, le=90)
    longitude: Optional[float] = Field(None, ge=-180, le=180)
    design_heat_c: Optional[float] = Field(None, ge=-60, le=40)
    design_cool_db_c: Optional[float] = Field(None, ge=-10, le=60)
    design_cool_rh_pct: Optional[float] = Field(None, ge=0, le=100)
    design_cool_mcwb_c: Optional[float] = Field(None, ge=-20, le=40)
    design_evap_wb_c: Optional[float] = Field(None, ge=-20, le=40)
    design_source: Optional[str] = Field(None, max_length=120)


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


class DesignClimateRequest(BaseModel):
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)


@router.post("/design-climate", response_model=AppCfg, dependencies=[Depends(require_write_token)])
def put_design_climate(req: DesignClimateRequest):
    """
    Расчётные наружные условия по координатам фермы: 10 лет часовых данных ERA5
    (Open-Meteo, CC BY 4.0, некоммерческое использование) → 99.6 % / 0.4 % по
    ASHRAE, гл. 14. Результат и координаты сохраняются в настройках хозяйства.
    """
    try:
        temps, rhs, elevation = fetch_hourly(req.latitude, req.longitude)
        dc = design_conditions(temps, rhs, elevation)
    except CalcError as e:
        raise from_calc_error(e, 502)
    cfg = load_app_config()
    cfg.latitude, cfg.longitude = req.latitude, req.longitude
    cfg.design_heat_c, cfg.design_cool_db_c = dc.heating_996_c, dc.cooling_04_db_c
    cfg.design_cool_rh_pct, cfg.design_cool_mcwb_c = dc.cooling_04_rh_pct, dc.cooling_04_mcwb_c
    cfg.design_evap_wb_c, cfg.design_source = dc.evap_04_wb_c, dc.source
    # Высоту фермы не трогаем, если её уже задали; иначе — высота точки реанализа
    if not cfg.altitude_m:
        cfg.altitude_m = float(dc.elevation_m)
    save_app_config(cfg)
    return AppCfg(**asdict(cfg))
