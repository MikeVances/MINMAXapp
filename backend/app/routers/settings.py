from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import List, Optional

from ..core.day_master import DayInfo, load_day_master, save_day_master
from ..core.app_config import AppConfig, load_app_config, save_app_config
from ..core.interpolation import interpolate_to_42_days, extract_anchor_points, ANCHOR_DAYS


router = APIRouter()


class DayItem(BaseModel):
    day: int = Field(..., ge=1, le=42)
    body_weight_g: Optional[float] = Field(None, ge=0)
    min_temp_c: Optional[float] = None
    rv_percent: Optional[float] = None
    q_min_per_bird: Optional[float] = Field(None, ge=0)  # м³/ч на голову
    q_max_per_bird: Optional[float] = Field(None, ge=0)  # м³/ч на голову


@router.get("/day-master", response_model=List[DayItem])
def get_day_master(mode: str = Query("full", regex="^(full|anchors)$")):
    """
    Получить профиль роста (day_master).

    Args:
        mode: "full" - все 42 дня (по умолчанию)
              "anchors" - только 7 опорных точек (1, 7, 14, 21, 28, 35, 42)
    """
    data = load_day_master()

    # Определить дни для возврата
    if mode == "anchors":
        days_to_return = ANCHOR_DAYS
    else:
        days_to_return = list(range(1, 43))

    # Вернём данные за выбранные дни
    out: List[DayItem] = []
    for d in days_to_return:
        info = data.get(d)
        out.append(
            DayItem(
                day=d,
                body_weight_g=(info.body_weight_g if info else None),
                min_temp_c=(info.min_temp_c if info else None),
                rv_percent=(info.rv_percent if info else None),
                q_min_per_bird=(info.q_min_per_bird if info else None),
                q_max_per_bird=(info.q_max_per_bird if info else None),
            )
        )
    return out


@router.put("/day-master", response_model=List[DayItem])
def put_day_master(payload: List[DayItem], auto_interpolate: bool = Query(True)):
    """
    Сохранить профиль роста (day_master).

    Если передано 7 опорных точек (дни 1,7,14,21,28,35,42) и auto_interpolate=True,
    то автоматически интерполируются промежуточные дни до полного профиля на 42 дня.

    Args:
        payload: Список дней с данными
        auto_interpolate: Автоматически интерполировать до 42 дней (по умолчанию True)
    """
    items = {x.day: DayInfo(day=x.day, body_weight_g=x.body_weight_g, min_temp_c=x.min_temp_c, rv_percent=x.rv_percent, q_min_per_bird=x.q_min_per_bird, q_max_per_bird=x.q_max_per_bird) for x in payload}

    # Проверить, нужна ли интерполяция
    if auto_interpolate and len(items) == len(ANCHOR_DAYS):
        # Проверить, что все опорные дни присутствуют
        if all(day in items for day in ANCHOR_DAYS):
            try:
                # Интерполировать до 42 дней
                items = interpolate_to_42_days(items)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=f"Interpolation failed: {str(e)}")

    save_day_master(items)
    return get_day_master(mode="full")


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
    )


@router.put("/app-config", response_model=AppCfg)
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
    )
    save_app_config(cfg)
    return payload
