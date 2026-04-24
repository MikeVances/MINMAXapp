"""
API endpoints для калибровки теплотехнических параметров помещения.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..core.building_thermal import (
    BuildingDimensions,
    HeaterConfig,
    CalibrationTest,
    ThermalConfig,
    HeatBalance,
    load_thermal_config,
    save_thermal_config,
    calculate_ua_coefficient,
    calculate_heater_duty_cycle,
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


class CalibrationTestModel(BaseModel):
    t_initial_c: float = Field(..., ge=-20, le=50, description="Начальная температура, °C")
    t_final_c: float = Field(..., ge=-20, le=50, description="Конечная температура, °C")
    t_outside_c: float = Field(..., ge=-40, le=50, description="Температура снаружи, °C")
    time_minutes: float = Field(..., gt=0, le=60, description="Время теста, минуты")


class ThermalConfigModel(BaseModel):
    building: BuildingDimensionsModel | None = None
    heater: HeaterConfigModel | None = None
    calibration: CalibrationTestModel | None = None


class CalibrationResultModel(BaseModel):
    ua_coefficient: float = Field(..., description="Коэффициент теплопотерь, Вт/°C")
    volume_m3: float = Field(..., description="Объем помещения, м³")
    cooling_rate_per_minute: float = Field(..., description="Скорость охлаждения, °C/мин")


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
    status_label:         str


# ===== Endpoints =====

@router.get("/config", response_model=ThermalConfigModel)
def get_thermal_config():
    """Получить текущую конфигурацию теплотехнических параметров"""
    config = load_thermal_config()

    result = ThermalConfigModel(
        building=BuildingDimensionsModel(**config.building.__dict__) if config.building else None,
        heater=HeaterConfigModel(**config.heater.__dict__) if config.heater else None,
        calibration=CalibrationTestModel(
            t_initial_c=config.calibration.t_initial_c,
            t_final_c=config.calibration.t_final_c,
            t_outside_c=config.calibration.t_outside_c,
            time_minutes=config.calibration.time_minutes,
        ) if config.calibration else None,
    )

    return result


@router.put("/config")
def update_thermal_config(payload: ThermalConfigModel):
    """Обновить конфигурацию теплотехнических параметров"""
    config = ThermalConfig()

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
        # Рассчитать UA коэффициент
        if not config.building:
            raise HTTPException(status_code=400, detail="Building dimensions required for calibration")

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
            raise HTTPException(status_code=400, detail=str(e))

    save_thermal_config(config)

    return {"status": "ok", "message": "Thermal configuration updated"}


@router.post("/calibrate", response_model=CalibrationResultModel)
def run_calibration(test: CalibrationTestModel):
    """
    Выполнить расчет калибровки по результатам теста охлаждения.
    НЕ сохраняет результат - только рассчитывает.
    """
    config = load_thermal_config()

    if not config.building:
        raise HTTPException(status_code=400, detail="Building dimensions not configured")

    try:
        ua = calculate_ua_coefficient(
            volume_m3=config.building.volume_m3,
            t_initial=test.t_initial_c,
            t_final=test.t_final_c,
            t_outside=test.t_outside_c,
            time_minutes=test.time_minutes,
        )

        cooling_rate = (test.t_initial_c - test.t_final_c) / test.time_minutes

        return CalibrationResultModel(
            ua_coefficient=ua,
            volume_m3=config.building.volume_m3,
            cooling_rate_per_minute=cooling_rate,
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


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
        raise HTTPException(status_code=400, detail="Калибровка UA не выполнена. "
                            "Используйте POST /thermal/calibrate и сохраните через PUT /thermal/config")

    if not config.heater:
        raise HTTPException(status_code=400, detail="Конфигурация обогревателей не задана. "
                            "Заполните секцию heater в PUT /thermal/config")

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
        status_label         = result.status_label,
    )
