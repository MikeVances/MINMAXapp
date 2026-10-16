from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..write_access import require_write_token
from ..core.app_config import AppConfig, load_app_config, save_app_config


router = APIRouter()


# ---- App config (mortality etc.) ----
class AppCfg(BaseModel):
    """Расширенная конфигурация приложения."""
    total_mortality_pct: float = Field(4.0, ge=0, le=100)
    ventilation_unit: str = Field("per_bird", pattern="^(per_bird|per_kg)$")

    # DEPRECATED: для обратной совместимости
    min_floor_unit: str = Field("per_bird", pattern="^(per_bird|per_kg)$")
    min_floor_0_7: float = Field(0.15, ge=0)
    min_floor_7_14: float = Field(0.25, ge=0)

    # Сезонные коэффициенты Qmax
    max_per_kg_winter: float = Field(2.0, ge=0)
    max_per_kg_spring_autumn: float = Field(3.0, ge=0)
    max_per_kg_summer: float = Field(4.0, ge=0)
    max_per_kg_tropical: float = Field(5.0, ge=0)

    # Температурное смешивание
    use_temp_blend: bool = Field(True)
    temp_winter_c: float = Field(-5.0, ge=-50, le=50)
    temp_spring_c: float = Field(10.0, ge=-50, le=50)
    temp_summer_c: float = Field(25.0, ge=-50, le=50)

    # Длина производственного цикла
    cycle_days: int = Field(42, ge=21, le=56)

    # Профиль роста по умолчанию (id из библиотеки /profiles)
    default_growth_profile: str = Field("ross308", pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")

    # Параметры расчёта из первых принципов (CIGR 1984)
    n_birds_initial: int = Field(30000, ge=1, le=500000)
    v_tunnel_ms: float = Field(2.5, ge=0.5, le=5.0)
    safety_factor_qmin: float = Field(1.5, ge=1.0, le=3.0)

    # Ограничения туннельного режима
    tunnel_min_day: int = Field(14, ge=1, le=42)
    tunnel_min_temp_c: float = Field(18.0, ge=0.0, le=35.0)


@router.get("/app-config", response_model=AppCfg)
def get_app_cfg():
    """Получить полную конфигурацию приложения."""
    cfg = load_app_config()
    return AppCfg(
        total_mortality_pct=cfg.total_mortality_pct,
        ventilation_unit=cfg.ventilation_unit,
        min_floor_unit=cfg.min_floor_unit,
        min_floor_0_7=cfg.min_floor_0_7,
        min_floor_7_14=cfg.min_floor_7_14,
        max_per_kg_winter=cfg.max_per_kg_winter,
        max_per_kg_spring_autumn=cfg.max_per_kg_spring_autumn,
        max_per_kg_summer=cfg.max_per_kg_summer,
        max_per_kg_tropical=cfg.max_per_kg_tropical,
        use_temp_blend=cfg.use_temp_blend,
        temp_winter_c=cfg.temp_winter_c,
        temp_spring_c=cfg.temp_spring_c,
        temp_summer_c=cfg.temp_summer_c,
        cycle_days=cfg.cycle_days,
        default_growth_profile=getattr(cfg, "default_growth_profile", "ross308"),
        n_birds_initial=getattr(cfg, "n_birds_initial", 30000),
        v_tunnel_ms=getattr(cfg, "v_tunnel_ms", 2.5),
        safety_factor_qmin=getattr(cfg, "safety_factor_qmin", 1.5),
        tunnel_min_day=getattr(cfg, "tunnel_min_day", 14),
        tunnel_min_temp_c=getattr(cfg, "tunnel_min_temp_c", 18.0),
    )


@router.put("/app-config", response_model=AppCfg, dependencies=[Depends(require_write_token)])
def put_app_cfg(payload: AppCfg):
    """Сохранить конфигурацию приложения."""
    cfg = AppConfig(
        total_mortality_pct=payload.total_mortality_pct,
        ventilation_unit=payload.ventilation_unit,
        min_floor_unit=payload.min_floor_unit,
        min_floor_0_7=payload.min_floor_0_7,
        min_floor_7_14=payload.min_floor_7_14,
        max_per_kg_winter=payload.max_per_kg_winter,
        max_per_kg_spring_autumn=payload.max_per_kg_spring_autumn,
        max_per_kg_summer=payload.max_per_kg_summer,
        max_per_kg_tropical=payload.max_per_kg_tropical,
        use_temp_blend=payload.use_temp_blend,
        temp_winter_c=payload.temp_winter_c,
        temp_spring_c=payload.temp_spring_c,
        temp_summer_c=payload.temp_summer_c,
        cycle_days=payload.cycle_days,
        default_growth_profile=payload.default_growth_profile,
        n_birds_initial=payload.n_birds_initial,
        v_tunnel_ms=payload.v_tunnel_ms,
        safety_factor_qmin=payload.safety_factor_qmin,
        tunnel_min_day=payload.tunnel_min_day,
        tunnel_min_temp_c=payload.tunnel_min_temp_c,
    )
    save_app_config(cfg)
    return payload
