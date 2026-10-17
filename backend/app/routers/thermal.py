"""
API endpoints для калибровки теплотехнических параметров помещения.
"""
from __future__ import annotations

import logging
import re

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..api_errors import api_error, from_calc_error
from ..write_access import require_write_token
from ..core.house_id import HOUSE_ID_PATTERN
from ..core.cooling_fit import fit_cooling_curve
from ..core.building_thermal import (
    BuildingDimensions,
    HeaterConfig,
    CalibrationTest,
    ThermalConfig,
    HeatBalance,
    load_thermal_config,
    save_thermal_config,
    calculate_ua_coefficient,
    calculate_heat_balance,
    heater_air_demand,
)


router = APIRouter()


# ===== Request/Response Models =====

class BuildingDimensionsModel(BaseModel):
    length_m: float = Field(..., gt=0, le=500, description="Длина помещения, м")
    width_m: float = Field(..., gt=0, le=200, description="Ширина помещения, м")
    height_m: float = Field(..., gt=0, le=20, description="Высота помещения, м")


class HeaterConfigModel(BaseModel):
    heater_type: str = Field(..., pattern=r"^(gas_open|electric)$", description="Тип обогревателей")
    total_power_kw: float = Field(..., ge=0, le=10000, description="Общая тепловая мощность, кВт")


class CurvePointModel(BaseModel):
    t_s: float = Field(..., ge=0, le=86_400, description="Секунды от старта теста")
    temp_c: float = Field(..., ge=-20, le=50, description="Температура внутри, °C")


class CalibrationTestModel(BaseModel):
    t_initial_c: float = Field(..., ge=-20, le=50, description="Начальная температура, °C")
    t_final_c: float = Field(..., ge=-20, le=50, description="Конечная температура, °C")
    t_outside_c: float = Field(..., ge=-40, le=50, description="Температура снаружи, °C")
    # Тест по кривой с массивным полом может идти пару часов
    time_minutes: float = Field(..., gt=0, le=600, description="Время теста, минуты")
    # Возвращается только в GET /config (не требуется при PUT — вычисляется на сервере)
    ua_coefficient: float | None = Field(None, description="Рассчитанный коэффициент теплопотерь, Вт/°C")
    method: str = Field("air_only_cooling", pattern=r"^(air_only_cooling|cooling_curve)$")
    # Отметки на каждом градусе (метод cooling_curve), первая — старт
    points: list[CurvePointModel] | None = Field(None, max_length=60)


class CurveCalibrationRequest(BaseModel):
    t_outside_c: float = Field(..., ge=-40, le=50, description="Температура снаружи, °C")
    points: list[CurvePointModel] = Field(..., min_length=2, max_length=60)
    # Объём зоны для многозонного теста; не задан — объём всего корпуса
    volume_m3: float | None = Field(None, gt=0, le=1_000_000)


class CurveCalibrationResult(BaseModel):
    ua_coefficient: float           # Вт/°C
    volume_m3: float
    c_air_j_per_k: float            # теплоёмкость воздуха
    c_struct_j_per_k: float         # эффективная теплоёмкость пола и стен
    rms_c: float                    # расхождение модели с отметками, °C
    duration_minutes: float
    warnings: list[str]             # small_delta_t | fast_cooling | poor_fit
    method: str = "cooling_curve"


logger = logging.getLogger(__name__)



def _safe_stored_house_id(house_id: str | None) -> str | None:
    """
    Имя корпуса из файла, сохранённого ДО появления валидации, может содержать
    разметку. Отдавать его нельзя, а падать с 500 на валидации ответа — тоже:
    сломается вся страница калибровки. Отбрасываем и пишем в лог.
    """
    if house_id is None or re.fullmatch(HOUSE_ID_PATTERN, house_id):
        return house_id
    logger.warning("thermal_config: недопустимый house_id отброшен: %r", house_id)
    return None


class ThermalConfigModel(BaseModel):
    # Имя корпуса показывается в UI: только буквы (в т.ч. кириллица), цифры,
    # пробел, точка, дефис и подчёркивание — без HTML-разметки
    house_id: str | None = Field(None, min_length=1, max_length=64, pattern=HOUSE_ID_PATTERN)
    building: BuildingDimensionsModel | None = None
    heater: HeaterConfigModel | None = None
    calibration: CalibrationTestModel | None = None


class HeaterAnalysisRequest(BaseModel):
    t_inside_target: float = Field(..., ge=-10, le=50, description="Целевая температура внутри, °C")
    t_outside:       float = Field(..., ge=-40, le=50, description="Температура снаружи, °C")
    q_min_m3h:       float = Field(
        ..., ge=0,
        description="Минимальный воздухообмен, м³/ч (минвентиляция для данного поголовья)"
    )
    num_birds:       int   = Field(..., ge=0, description="Количество птицы, гол")
    bird_weight_kg:  float = Field(
        ..., ge=0, le=20,
        description="Средняя живая масса птицы, кг (0.04 для суточных)"
    )


class HeaterAnalysisModel(BaseModel):
    # Потери тепла
    q_walls_kw:          float
    q_ventilation_kw:    float
    q_total_loss_kw:     float
    # Тепло птицы
    q_birds_kw:          float
    q_bird_per_bird_w:   float
    # Баланс
    q_heater_required_kw: float
    heater_covers_need:   bool
    duty_cycle:           float
    duty_cycle_percent:   float
    combustion_air_m3h:   float
    bird_heat_fraction:   float
    status_code:          str   # см. HeatBalance: перевод на клиенте
    status_level:         str   # ok | warn | danger
    heater_deficit_kw:    float


# ===== Endpoints =====

@router.get("/config", response_model=ThermalConfigModel)
def get_thermal_config():
    """Получить текущую конфигурацию теплотехнических параметров"""
    config = load_thermal_config()

    result = ThermalConfigModel(
        house_id=_safe_stored_house_id(config.house_id),
        building=BuildingDimensionsModel(**config.building.__dict__) if config.building else None,
        heater=HeaterConfigModel(**config.heater.__dict__) if config.heater else None,
        calibration=CalibrationTestModel(
            t_initial_c=config.calibration.t_initial_c,
            t_final_c=config.calibration.t_final_c,
            t_outside_c=config.calibration.t_outside_c,
            time_minutes=config.calibration.time_minutes,
            ua_coefficient=config.calibration.ua_coefficient,
            method=config.calibration.method,
            points=([CurvePointModel(t_s=p[0], temp_c=p[1]) for p in config.calibration.points]
                    if config.calibration.points else None),
        ) if config.calibration else None,
    )

    return result


@router.put("/config", dependencies=[Depends(require_write_token)])
def update_thermal_config(payload: ThermalConfigModel):
    """Обновить конфигурацию теплотехнических параметров"""
    config = ThermalConfig(house_id=payload.house_id)

    if payload.building:
        config.building = BuildingDimensions(
            length_m=payload.building.length_m,
            width_m=payload.building.width_m,
            height_m=payload.building.height_m,
        )

    if payload.heater:
        config.heater = HeaterConfig(
            heater_type=payload.heater.heater_type,
            total_power_kw=payload.heater.total_power_kw,
        )

    if payload.calibration:
        cal = payload.calibration
        points = [[p.t_s, p.temp_c] for p in cal.points] if cal.points else None
        if cal.ua_coefficient is not None:
            # UA уже рассчитан (round-trip из loadConfig или явное сохранение) — сохраняем как есть
            config.calibration = CalibrationTest(
                t_initial_c=cal.t_initial_c,
                t_final_c=cal.t_final_c,
                t_outside_c=cal.t_outside_c,
                time_minutes=cal.time_minutes,
                ua_coefficient=cal.ua_coefficient,
                method=cal.method,
                points=points,
            )
        elif points:
            # Кривая остывания: UA подгонкой модели «воздух + конструкции» по объёму корпуса
            if not config.building:
                raise api_error(400, "dimensions_missing")
            try:
                fit = fit_cooling_curve(config.building.volume_m3, cal.t_outside_c, points)
            except ValueError as e:
                raise from_calc_error(e)
            config.calibration = CalibrationTest(
                t_initial_c=points[0][1], t_final_c=points[-1][1], t_outside_c=cal.t_outside_c,
                time_minutes=points[-1][0] / 60.0, ua_coefficient=fit.ua_w_per_k,
                method="cooling_curve", points=points,
            )
        else:
            # UA не задан — рассчитать из данных теста охлаждения
            if not config.building:
                raise api_error(400, "dimensions_missing")
            try:
                ua = calculate_ua_coefficient(
                    volume_m3=config.building.volume_m3,
                    t_initial=payload.calibration.t_initial_c,
                    t_final=payload.calibration.t_final_c,
                    t_outside=payload.calibration.t_outside_c,
                    time_minutes=payload.calibration.time_minutes,
                )
                config.calibration = CalibrationTest(
                    t_initial_c=payload.calibration.t_initial_c,
                    t_final_c=payload.calibration.t_final_c,
                    t_outside_c=payload.calibration.t_outside_c,
                    time_minutes=payload.calibration.time_minutes,
                    ua_coefficient=ua,
                )
            except ValueError as e:
                raise from_calc_error(e)

    save_thermal_config(config)

    return {"status": "ok"}


@router.post("/calibrate-curve", response_model=CurveCalibrationResult)
def run_curve_calibration(req: CurveCalibrationRequest):
    """
    UA по кривой остывания: отметки времени на каждом градусе падения.
    НЕ сохраняет результат — только рассчитывает (сохранение — PUT /config с points).
    """
    volume = req.volume_m3
    if volume is None:
        config = load_thermal_config()
        if not config.building:
            raise api_error(400, "dimensions_missing")
        volume = config.building.volume_m3

    try:
        fit = fit_cooling_curve(volume, req.t_outside_c, [(p.t_s, p.temp_c) for p in req.points])
    except ValueError as e:
        raise from_calc_error(e)

    return CurveCalibrationResult(
        ua_coefficient=fit.ua_w_per_k,
        volume_m3=volume,
        c_air_j_per_k=fit.c_air_j_per_k,
        c_struct_j_per_k=fit.c_struct_j_per_k,
        rms_c=fit.rms_c,
        duration_minutes=fit.duration_s / 60.0,
        warnings=fit.warnings,
    )


@router.post("/analyze-heaters", response_model=HeaterAnalysisModel)
def analyze_heaters(req: HeaterAnalysisRequest):
    """
    Полный тепловой баланс птичника с учётом метаболического тепла птицы.

    **Уравнение баланса:**
    ```
    Q_heater = Q_walls + Q_ventilation − Q_birds
    ```

    - **Q_walls** = UA × (T_inside − T_outside) — теплопотери через ограждения
    - **Q_ventilation** = Q_min × 0.335 × ΔT — потери с вентиляционным воздухом
    - **Q_birds** = 6.90 × W^0.75 × N — метаболическое тепло птицы (CIGR Handbook)

    **Важно:** калибровку UA следует проводить в ПУСТОМ птичнике.
    Тепловая масса птицы и подстилки при тесте в заселённом птичнике
    занижает рассчитанный UA в разы.

    **Требуется:** наличие калибровки и конфигурации обогревателей в `/thermal/config`.
    """
    config = load_thermal_config()

    if not config.calibration:
        raise api_error(400, "calibration_missing")

    if not config.heater:
        raise api_error(400, "heater_config_missing")

    result: HeatBalance = calculate_heat_balance(
        ua_coefficient   = config.calibration.ua_coefficient,
        q_min_m3h        = req.q_min_m3h,
        t_inside_target  = req.t_inside_target,
        t_outside        = req.t_outside,
        num_birds        = req.num_birds,
        bird_weight_kg   = req.bird_weight_kg,
        heater_power_kw  = config.heater.total_power_kw,
        heater_type      = config.heater.heater_type,
    )

    return HeaterAnalysisModel(
        q_walls_kw           = result.q_walls_kw,
        q_ventilation_kw     = result.q_ventilation_kw,
        q_total_loss_kw      = result.q_total_loss_kw,
        q_birds_kw           = result.q_birds_kw,
        q_bird_per_bird_w    = result.q_bird_per_bird_w,
        q_heater_required_kw = result.q_heater_required_kw,
        heater_covers_need   = result.heater_covers_need,
        duty_cycle           = result.duty_cycle,
        duty_cycle_percent   = result.duty_cycle_pct,
        combustion_air_m3h   = result.combustion_air_m3h,
        bird_heat_fraction   = result.bird_heat_fraction,
        status_code          = result.status_code,
        status_level         = result.status_level,
        heater_deficit_kw    = result.heater_deficit_kw,
    )
