from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import List, Optional

from ..core.day_master import DayInfo, load_day_master, save_day_master
from ..core.app_config import AppConfig, load_app_config, save_app_config
from ..core.interpolation import interpolate_to_42_days, extract_anchor_points, ANCHOR_DAYS
from ..core.ventilation_calc import calc_q_min_per_bird, calc_q_max_per_bird


router = APIRouter()


class DayItem(BaseModel):
    day: int = Field(..., ge=1, le=63)
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
        days_to_return = sorted(data.keys())  # все доступные дни из файла

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

    # Интерполируем если передан разреженный набор опорных точек (меньше 42),
    # независимо от того какие именно дни — поддерживает любой cycle_days.
    is_sparse = auto_interpolate and 2 <= len(items) < 42 and 1 in items
    if is_sparse:
        anchor_set = set(items.keys())  # запоминаем опорные дни ДО расширения
        # Читаем до записи — нужно сохранить CIGR-нормы для не-опорных дней
        existing = load_day_master()
        try:
            items = interpolate_to_42_days(items)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Interpolation failed: {str(e)}")

        # Для промежуточных дней восстанавливаем q_min/q_max из файла.
        # Это сохраняет шаговую функцию CIGR (скачок на tunnel_min_day)
        # и не даёт линейной интерполяции опорных точек её разгладить.
        for day, info in items.items():
            if day in anchor_set:
                continue
            ex = existing.get(day)
            if ex:
                if ex.q_min_per_bird is not None:
                    info.q_min_per_bird = ex.q_min_per_bird
                if ex.q_max_per_bird is not None:
                    info.q_max_per_bird = ex.q_max_per_bird

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

    # Длина производственного цикла
    cycle_days: int = Field(42, ge=21, le=56)

    # Параметры расчёта из первых принципов (CIGR 1984)
    n_birds_initial: int = Field(30000, ge=1, le=500000)
    v_tunnel_ms: float = Field(2.5, ge=0.5, le=5.0)
    safety_factor_qmin: float = Field(1.5, ge=1.0, le=3.0)

    # Ограничения туннельного режима
    tunnel_min_day: int = Field(14, ge=1, le=42)
    tunnel_min_temp_c: float = Field(18.0, ge=0.0, le=35.0)


@router.post("/recalculate-ventilation", response_model=List[DayItem])
def recalculate_ventilation():
    """
    Пересчитать q_min и q_max для всех дней профиля из первых принципов.

    q_min: метод CO₂ (CIGR 1984)
      H_total = 10.62 × W^0.75 Вт/гол
      VCO₂    = H_total × 0.153 л/ч/гол
      q_min   = VCO₂ / 2.6 × safety_factor м³/ч/гол

    q_max:
      дни < tunnel_min_day  → q_min × 4  (переходный потолок, Aviagen 3–5×)
      дни ≥ tunnel_min_day  → v_tunnel × (width × height) × 3600 / N_birds
                               (физическая мощность туннеля на голову)

    Скачок q_max происходит ровно на дне tunnel_min_day, а не на хардкоде.
    Размеры птичника берутся из thermal_config (страница Калибровка).
    Поголовье учитывает суточный падёж нарастающим итогом.
    """
    from ..core.building_thermal import load_thermal_config

    cfg     = load_app_config()
    thermal = load_thermal_config()

    if not thermal.building:
        raise HTTPException(
            status_code=400,
            detail="Размеры птичника не заданы. Укажите их на странице Калибровка → Шаг 1."
        )

    width_m  = thermal.building.width_m
    height_m = thermal.building.height_m

    safety       = float(getattr(cfg, "safety_factor_qmin", 1.5))
    v_tunnel     = float(getattr(cfg, "v_tunnel_ms", 2.5))
    n_initial    = int(getattr(cfg, "n_birds_initial", 30000))
    total_m      = float(getattr(cfg, "total_mortality_pct", 4.0)) / 100.0
    daily_m      = 1.0 - (1.0 - total_m) ** (1.0 / 41.0)
    tunnel_min_d = int(getattr(cfg, "tunnel_min_day", 14))

    dm = load_day_master()
    for day, info in dm.items():
        if info.body_weight_g is None:
            continue
        W_kg     = info.body_weight_g / 1000.0
        survival = (1.0 - daily_m) ** max(day - 1, 0)
        N_day    = n_initial * survival

        q_min_b = calc_q_min_per_bird(W_kg, safety)
        info.q_min_per_bird = q_min_b

        if day < tunnel_min_d:
            # Переходный режим: максимум = 4× минимальная вентиляция
            # Значение не зависит от k_temp — это потолок при нейтральных условиях.
            # calc_core умножит на k_temp при расчёте уставки.
            info.q_max_per_bird = round(q_min_b * 4.0, 3)
        else:
            # Туннельный режим: физическая мощность на голову
            info.q_max_per_bird = calc_q_max_per_bird(width_m, height_m, N_day, v_tunnel)

    save_day_master(dm)
    return get_day_master(mode="full")


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
        n_birds_initial=getattr(cfg, "n_birds_initial", 30000),
        v_tunnel_ms=getattr(cfg, "v_tunnel_ms", 2.5),
        safety_factor_qmin=getattr(cfg, "safety_factor_qmin", 1.5),
        tunnel_min_day=getattr(cfg, "tunnel_min_day", 14),
        tunnel_min_temp_c=getattr(cfg, "tunnel_min_temp_c", 18.0),
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
        cycle_days=payload.cycle_days,
        n_birds_initial=payload.n_birds_initial,
        v_tunnel_ms=payload.v_tunnel_ms,
        safety_factor_qmin=payload.safety_factor_qmin,
        tunnel_min_day=payload.tunnel_min_day,
        tunnel_min_temp_c=payload.tunnel_min_temp_c,
    )
    save_app_config(cfg)
    return payload
