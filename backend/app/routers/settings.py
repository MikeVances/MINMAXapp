from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional

from ..core.day_master import DayInfo, load_day_master, save_day_master
from ..core.app_config import AppConfig, load_app_config, save_app_config


router = APIRouter()


class DayItem(BaseModel):
    day: int = Field(..., ge=1, le=42)
    body_weight_g: Optional[float] = Field(None, ge=0)
    min_temp_c: Optional[float] = None
    rv_percent: Optional[float] = None


@router.get("/day-master", response_model=List[DayItem])
def get_day_master():
    data = load_day_master()
    # Вернём полные 1..42 с пустыми значениями там, где не задано
    out: List[DayItem] = []
    for d in range(1, 43):
        info = data.get(d)
        out.append(
            DayItem(
                day=d,
                body_weight_g=(info.body_weight_g if info else None),
                min_temp_c=(info.min_temp_c if info else None),
                rv_percent=(info.rv_percent if info else None),
            )
        )
    return out


@router.put("/day-master", response_model=List[DayItem])
def put_day_master(payload: List[DayItem]):
    # Простейшая валидация набора дней
    items = {x.day: DayInfo(day=x.day, body_weight_g=x.body_weight_g, min_temp_c=x.min_temp_c, rv_percent=x.rv_percent) for x in payload}
    save_day_master(items)
    return get_day_master()


# ---- App config (mortality etc.) ----
class AppCfg(BaseModel):
    total_mortality_pct: float = Field(4.0, ge=0, le=100)
    min_floor_0_7: float = Field(0.15, ge=0)
    min_floor_7_14: float = Field(0.25, ge=0)


@router.get("/app-config", response_model=AppCfg)
def get_app_cfg():
    cfg = load_app_config()
    return AppCfg(
        total_mortality_pct=cfg.total_mortality_pct,
        min_floor_0_7=cfg.min_floor_0_7,
        min_floor_7_14=cfg.min_floor_7_14,
    )


@router.put("/app-config", response_model=AppCfg)
def put_app_cfg(payload: AppCfg):
    cfg = AppConfig(
        total_mortality_pct=payload.total_mortality_pct,
        min_floor_0_7=payload.min_floor_0_7,
        min_floor_7_14=payload.min_floor_7_14,
    )
    save_app_config(cfg)
    return payload
