"""
Роутер /calc/tools — инструментальные калькуляторы (UGA).

Каждый эндпоинт — отдельный инженерный калькулятор, не зависящий
от дневника стада или профиля роста.
"""

from fastapi import APIRouter
from pydantic import BaseModel, Field
from typing import Literal, Optional

from ..core.leakage_calc import LeakageInput, LeakageResult, calculate_leakage
from ..core.evap_cooling_calc import (
    EvapCoolingInput, EvapCoolingResult, calculate_evap_cooling,
)
from ..core.tunnel_speed_calc import (
    TunnelSpeedInput, TunnelSpeedResult, calculate_tunnel_speed,
)

router = APIRouter()


# ─────────────────────────────────────────────
# POST /calc/tools/leakage
# Калькулятор герметичности птичника (ELA)
# ─────────────────────────────────────────────

class LeakageRequest(BaseModel):
    # Размеры птичника
    house_length_m: float = Field(..., gt=0, description="Длина птичника, м")
    house_width_m:  float = Field(..., gt=0, description="Ширина птичника, м")

    # Параметры теста
    fan_capacity_m3h: float = Field(
        ..., gt=0,
        description="Производительность тестового вентилятора при 25 Па (≈ 0.10\" вод. ст.), м³/ч"
    )
    measured_pressure_pa: float = Field(
        ..., gt=0, le=250,
        description="Статическое давление при тесте, Па (рекомендуемый диапазон 25–65 Па)"
    )

    # Анализ впускной системы (опционально — не используется в тесте герметичности)
    min_vent_fan_m3h: Optional[float] = Field(None, gt=0, description="Суммарный расход вентиляторов минвентиляции, м³/ч")
    num_inlets: Optional[int] = Field(None, gt=0, description="Количество боковых приточных клапанов, шт")
    inlet_height_cm: Optional[float] = Field(None, gt=0, description="Максимальная высота открытия клапана, см")
    inlet_length_cm: Optional[float] = Field(None, gt=0, description="Длина одного клапана, см")


class LeakageResponse(BaseModel):
    # Тест герметичности
    fan_corrected_m3h:      float
    ela_m2:                 float
    house_area_m2:          float
    relative_leakage:       float
    tightness_class:        str
    tightness_label_ru:     str

    static_pressure_pa:     float


# ─────────────────────────────────────────────
# POST /calc/tools/evap_cooling
# Калькулятор испарительного охлаждения (Pad & Fan)
# ─────────────────────────────────────────────

class EvapCoolingRequest(BaseModel):
    # Птичник (для контекста/аудита)
    house_length_m: float = Field(..., gt=0, description="Длина птичника, м")

    # Климат
    t_outdoor_db_c: float = Field(
        ..., ge=-10, le=55,
        description="Температура наружного воздуха (сухой термометр), °C"
    )
    rh_outdoor_pct: float = Field(
        ..., ge=5, le=100,
        description="Относительная влажность наружного воздуха, %"
    )

    # Вентиляция
    total_fan_m3h: float = Field(
        ..., gt=0,
        description="Суммарная производительность туннельных вентиляторов, м³/ч"
    )

    # Пэд — тип и размеры установленных панелей
    pad_type: str = Field(
        "7090",
        pattern="^(7090|7060|5090)$",
        description="Тип пэда SANHE: 7090 (макс. η), 7060 (стандарт, низкое ΔP), 5090 (компакт)"
    )
    pad_thickness_mm: int = Field(
        100, ge=50, le=300,
        description="Толщина пэда, мм. Доступные значения: 7090/7060: 75,100,150,200,300; 5090: 50,75,100,150"
    )
    pad_length_m: float = Field(
        ..., gt=0,
        description="Суммарная длина установленных панелей охлаждения, м"
    )
    pad_height_m: float = Field(
        ..., gt=0,
        description="Высота панелей охлаждения, м"
    )

    # Цель
    t_inside_target_c: float = Field(
        28.0,
        description="Целевая температура внутри птичника, °C"
    )

    # Опционально: температура воды подачи
    water_supply_t_c: Optional[float] = Field(
        None, ge=1, le=40,
        description="Температура воды подачи на пэд, °C (скважина ≈ 8–12, бак летом до 35)"
    )


class EvapCoolingResponse(BaseModel):
    # Психрометрика
    t_wb_c:              float
    t_pad_out_c:         float
    cooling_achieved_c:  float
    pad_efficiency:      float

    # Геометрия пэда
    pad_area_m2:             float
    air_velocity_ms:         float
    velocity_ok:             bool
    velocity_status:         str
    pad_pressure_drop_pa:    float

    # Вода
    water_flow_lpm:     float
    water_per_hour_l:   float

    # Оценка
    cooling_sufficient:      bool
    temp_margin_c:           float
    recommended_pad_area_m2: float
    status_label:            str

    # Психрометрика — точка росы (всегда)
    t_dew_c:             float
    # Режим подачи воды (None если не задана)
    water_supply_t_c:    Optional[float]
    water_regime:        Optional[str]   # 'safe' | 'condensation_risk'


@router.post(
    "/evap_cooling",
    response_model=EvapCoolingResponse,
    summary="Испарительное охлаждение — Pad & Fan (UGA)",
)
def calc_evap_cooling(req: EvapCoolingRequest) -> EvapCoolingResponse:
    """
    Рассчитывает параметры системы испарительного охлаждения (Pad & Fan).

    **Физика:**
    Воздух охлаждается, испаряя воду в целлюлозном пэде.
    Предел охлаждения — температура мокрого термометра (T_wb).
    Фактическая температура после пэда: T_pad = T_db − η × (T_db − T_wb).

    **Эффективность насыщения η (saturation efficiency):**
    η = (T_db_in − T_db_out) / (T_db_in − T_wb_in) — степень приближения к T_wb.
    Интерполируется из таблиц SANHE по фактической скорости воздуха через пэд.
    Типы: 7090 (макс. η, выше ΔP), 7060 (стандарт), 5090 (компакт).

    **Водопотребление:** психрометрический массовый баланс ΔW = η × (W_sat(T_wb) − W_outside), точность ±2% vs UGA Excel.

    **Формула мокрого термометра:** Stull (2011), точность ±0.3°C.
    """
    inp = EvapCoolingInput(
        house_length_m    = req.house_length_m,
        t_outdoor_db_c    = req.t_outdoor_db_c,
        rh_outdoor_pct    = req.rh_outdoor_pct,
        total_fan_m3h     = req.total_fan_m3h,
        pad_type          = req.pad_type,
        pad_thickness_mm  = req.pad_thickness_mm,
        pad_length_m      = req.pad_length_m,
        pad_height_m      = req.pad_height_m,
        t_inside_target_c = req.t_inside_target_c,
        water_supply_t_c  = req.water_supply_t_c,
    )
    r: EvapCoolingResult = calculate_evap_cooling(inp)
    return EvapCoolingResponse(
        t_wb_c                  = r.t_wb_c,
        t_pad_out_c             = r.t_pad_out_c,
        cooling_achieved_c      = r.cooling_achieved_c,
        pad_efficiency          = r.pad_efficiency,
        pad_area_m2             = r.pad_area_m2,
        air_velocity_ms         = r.air_velocity_ms,
        velocity_ok             = r.velocity_ok,
        velocity_status         = r.velocity_status,
        pad_pressure_drop_pa    = r.pad_pressure_drop_pa,
        water_flow_lpm          = r.water_flow_lpm,
        water_per_hour_l        = r.water_per_hour_l,
        cooling_sufficient      = r.cooling_sufficient,
        temp_margin_c           = r.temp_margin_c,
        recommended_pad_area_m2 = r.recommended_pad_area_m2,
        status_label            = r.status_label,
        t_dew_c                 = r.t_dew_c,
        water_supply_t_c        = r.water_supply_t_c,
        water_regime            = r.water_regime,
    )


# ─────────────────────────────────────────────
# POST /calc/tools/tunnel_speed
# Калькулятор скорости воздуха в туннеле (ветровое охлаждение)
# ─────────────────────────────────────────────

class TunnelSpeedRequest(BaseModel):
    house_width_m:    float = Field(..., gt=0, description="Ширина птичника, м")
    tunnel_height_m:  float = Field(
        ..., gt=0,
        description="Высота свободного сечения туннеля (≈70–85% высоты стены), м"
    )
    num_fans:         int   = Field(..., gt=0, description="Количество туннельных вентиляторов")
    fan_capacity_m3h: float = Field(
        ..., gt=0,
        description="Производительность одного вентилятора при 0 Па, м³/ч"
    )
    t_outdoor_db_c:   float = Field(
        ..., ge=0, le=55,
        description="Температура наружного воздуха (сухой термометр), °C"
    )
    rh_outdoor_pct:   float = Field(
        ..., ge=5, le=100,
        description="Относительная влажность, %"
    )
    bird_age_days:    int   = Field(
        ..., ge=1, le=60,
        description="Возраст птицы, дней (влияет на рекомендуемую скорость)"
    )
    num_inlets:    int   = Field(1,   ge=1, le=500, description="Количество приточных секций/проёмов, шт")
    inlet_width_m:  float = Field(0.0, ge=0, le=50,  description="Ширина одного проёма, м (0 = авто: ширина птичника)")
    inlet_height_m: float = Field(0.0, ge=0, le=10,  description="Высота одного проёма, м (0 = авто: высота туннеля)")


class TunnelSpeedResponse(BaseModel):
    cross_section_m2:       float
    total_airflow_m3h:      float
    air_velocity_ms:        float
    air_velocity_fpm:       float
    wind_chill_c:           float
    effective_temp_c:       float
    thi_value:              float
    thi_status:             str
    dynamic_pressure_pa:    float
    inlet_area_m2:          float
    inlet_velocity_ms:      float
    inlet_sp_pa:            float
    inlet_status:           str
    total_pressure_pa:      float
    target_v_min_ms:        float
    target_v_max_ms:        float
    velocity_status:        str
    fans_needed_for_target: int
    status_label:           str
    bird_comfort_target_c:    float
    tunnel_sufficient:        bool
    t_outdoor_tunnel_limit_c: float
    temp_margin_c:            float


@router.post(
    "/tunnel_speed",
    response_model=TunnelSpeedResponse,
    summary="Скорость воздуха в туннеле — ветровое охлаждение (UGA)",
)
def calc_tunnel_speed(req: TunnelSpeedRequest) -> TunnelSpeedResponse:
    """
    Рассчитывает скорость воздуха в туннеле, ветровое охлаждение и THI.

    **Ветровое охлаждение:**
    Ощущаемая температура рассчитывается по российской нормативной таблице
    (трилинейная интерполяция по T × RH × V), учитывающей испарение со слизистых.
    Эффект значительно сильнее линейного UGA-приближения (100 FPM = -1°F).

    **THI (Temperature Humidity Index):**
    - < 74 — Комфорт
    - 74–78 — Тревога
    - 79–83 — Опасность
    - > 83 — Критично

    **Рекомендуемая скорость по возрасту:**
    - 1–21 день: 1.5–2.0 м/с
    - 22–35 дней: 2.0–2.5 м/с
    - 36–42 дня: 2.5–3.0 м/с
    """
    inp = TunnelSpeedInput(
        house_width_m    = req.house_width_m,
        tunnel_height_m  = req.tunnel_height_m,
        num_fans         = req.num_fans,
        fan_capacity_m3h = req.fan_capacity_m3h,
        t_outdoor_db_c   = req.t_outdoor_db_c,
        rh_outdoor_pct   = req.rh_outdoor_pct,
        bird_age_days    = req.bird_age_days,
        num_inlets       = req.num_inlets,
        inlet_width_m    = req.inlet_width_m,
        inlet_height_m   = req.inlet_height_m,
    )
    r: TunnelSpeedResult = calculate_tunnel_speed(inp)
    return TunnelSpeedResponse(
        cross_section_m2          = r.cross_section_m2,
        total_airflow_m3h         = r.total_airflow_m3h,
        air_velocity_ms           = r.air_velocity_ms,
        air_velocity_fpm          = r.air_velocity_fpm,
        wind_chill_c              = r.wind_chill_c,
        effective_temp_c          = r.effective_temp_c,
        thi_value                 = r.thi_value,
        thi_status                = r.thi_status,
        dynamic_pressure_pa       = r.dynamic_pressure_pa,
        inlet_area_m2             = r.inlet_area_m2,
        inlet_velocity_ms         = r.inlet_velocity_ms,
        inlet_sp_pa               = r.inlet_sp_pa,
        inlet_status              = r.inlet_status,
        total_pressure_pa         = r.total_pressure_pa,
        target_v_min_ms           = r.target_v_min_ms,
        target_v_max_ms           = r.target_v_max_ms,
        velocity_status           = r.velocity_status,
        fans_needed_for_target    = r.fans_needed_for_target,
        status_label              = r.status_label,
        bird_comfort_target_c     = r.bird_comfort_target_c,
        tunnel_sufficient         = r.tunnel_sufficient,
        t_outdoor_tunnel_limit_c  = r.t_outdoor_tunnel_limit_c,
        temp_margin_c             = r.temp_margin_c,
    )


@router.post("/leakage", response_model=LeakageResponse, summary="Герметичность птичника (ELA)")
def calc_leakage(req: LeakageRequest) -> LeakageResponse:
    """
    Рассчитывает герметичность птичника по результату теста на статическое давление.

    **Методика теста:**
    1. Закрыть все ворота, люки, шторы, впускные клапаны.
    2. Запустить один или несколько туннельных вентиляторов.
    3. Зафиксировать статическое давление в птичнике.
    4. Ввести параметры — получить ELA и класс герметичности.

    **Рекомендуемое давление теста:** 25–65 Па (0.10–0.25 дюйма вод. ст.).

    **Классификация (относительная утечка, м²/1000м²):**
    - < 0.25 — Герметичный ✅
    - 0.25–0.50 — Умеренный 🟡
    - 0.50–1.00 — Негерметичный ⚠️
    - > 1.00 — Критически негерметичный 🔴
    """
    inp = LeakageInput(
        house_length_m        = req.house_length_m,
        house_width_m         = req.house_width_m,
        fan_capacity_m3h      = req.fan_capacity_m3h,
        measured_pressure_pa  = req.measured_pressure_pa,
    )
    result: LeakageResult = calculate_leakage(inp)

    return LeakageResponse(
        fan_corrected_m3h  = result.fan_corrected_m3h,
        ela_m2             = result.ela_m2,
        house_area_m2      = result.house_area_m2,
        relative_leakage   = result.relative_leakage,
        tightness_class    = result.tightness_class,
        tightness_label_ru = result.tightness_label_ru,
        static_pressure_pa = result.static_pressure_pa,
    )
