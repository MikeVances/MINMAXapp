"""
Роутер /calc/tools — инструментальные калькуляторы (UGA).

Каждый эндпоинт — отдельный инженерный калькулятор, не зависящий
от дневника стада или профиля роста.
"""

from fastapi import APIRouter
from pydantic import BaseModel, Field, model_validator
from typing import Literal, Optional

from ..api_errors import api_error
from ..core.app_config import load_app_config
from ..core.errors import CalcError
from ..core.growth_profiles import ProfileNotFound, load_profile
from ..core.leakage_calc import LeakageInput, LeakageResult, calculate_leakage
from ..core.evap_cooling_calc import (
    SANHE_PADS, EvapCoolingInput, EvapCoolingResult, calculate_evap_cooling,
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

    static_pressure_pa:     float


# ─────────────────────────────────────────────
# POST /calc/tools/evap_cooling
# Калькулятор испарительного охлаждения (Pad & Fan)
# ─────────────────────────────────────────────

def _bird_weight_kg(age_days: int, profile_id: Optional[str]) -> float:
    """Масса птицы на расчётный день из профиля роста, кг — как в расчёте Qmin/Qmax."""
    profile_id = profile_id or load_app_config().default_growth_profile
    try:
        point = load_profile(profile_id).point_for_day(age_days)
    except ProfileNotFound:
        raise api_error(404, "profile_not_found", id=profile_id)
    return (point.body_weight_g or 0.0) / 1000.0


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

    # Панель — тип и размеры установленных панелей
    pad_type: str = Field(
        "7090",
        pattern="^(7090|7060|5090)$",
        description="Тип панели SANHE: 7090 (макс. η), 7060 (стандарт, низкое ΔP), 5090 (компакт)"
    )
    pad_thickness_mm: int = Field(
        100, ge=50, le=300,
        description="Толщина панели, мм. Доступные значения: 7090/7060: 75,100,150,200,300; 5090: 50,75,100,150"
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
        description="Температура воды подачи на панель, °C (скважина ≈ 8–12, бак летом до 35)"
    )
    # Вторая точка паспорта системы вентиляторов: расход в рабочей точке с сопротивлением панели
    total_fan_25pa_m3h: float = Field(0.0, ge=0, description="Суммарный расход вентиляторов при 25 Па, м³/ч (0 = неизвестен)")
    # Поголовье и расчётный день — для нагрева воздуха от панелей до вентиляторов
    num_birds: int = Field(0, ge=0, le=200_000, description="Поголовье (0 = нагрев вдоль корпуса не учитывать)")
    bird_age_days: Optional[int] = Field(None, ge=1, le=63, description="Расчётный день — масса из профиля роста")
    growth_profile_id: Optional[str] = Field(None, description="Профиль роста (по умолчанию — из настроек)")

    @model_validator(mode="after")
    def _fan_25pa_below_free_air(self):
        if self.total_fan_25pa_m3h and self.total_fan_25pa_m3h >= self.total_fan_m3h:
            raise CalcError("fan_25pa_above_free_air")
        return self

    @model_validator(mode="after")
    def _thickness_exists_for_pad_type(self):
        # Толщины берём из той же таблицы SANHE, по которой идёт расчёт: иначе
        # недопустимая пара (5090/200, 7090/125) падала KeyError → 500
        allowed = SANHE_PADS[self.pad_type]["thicknesses"]
        if self.pad_thickness_mm not in allowed:
            raise CalcError("pad_thickness_unavailable", thickness=self.pad_thickness_mm,
                            pad_type=self.pad_type, allowed=", ".join(map(str, allowed)))
        return self


class EvapCoolingResponse(BaseModel):
    # Психрометрика
    t_wb_c:              float
    t_pad_out_c:         float
    cooling_achieved_c:  float
    pad_efficiency:      float

    # Геометрия панели
    pad_area_m2:             float
    air_velocity_ms:         float
    velocity_ok:             bool
    velocity_status:         str    # too_low | ok | too_high
    pad_v_min_ms:            float
    pad_v_max_ms:            float
    pad_pressure_drop_pa:    float

    # Вода
    water_flow_lpm:     float
    water_per_hour_l:   float

    # Оценка
    cooling_sufficient:      bool
    temp_margin_c:           float
    recommended_pad_area_m2: float
    status_code:             str    # код оценки, перевод на клиенте
    status_level:            str    # ok | warn | danger

    # Психрометрика — точка росы (всегда)
    t_dew_c:             float
    # Режим подачи воды (None если не задана)
    water_supply_t_c:    Optional[float]
    water_regime:        Optional[str]   # 'safe' | 'condensation_risk'
    air_temp_rise_c:     float = 0.0     # нагрев воздуха от панелей до вентиляторов
    t_fan_end_c:         float = 0.0     # T у вентиляторов — по ней оценка достаточности
    airflow_m3h:         float = 0.0     # расход, по которому считаны скорость, КПД и вода
    airflow_basis:       str = "rated_0pa"   # operating_point | rated_0pa


@router.post(
    "/evap_cooling",
    response_model=EvapCoolingResponse,
    summary="Испарительное охлаждение — Pad & Fan (UGA)",
)
def calc_evap_cooling(req: EvapCoolingRequest) -> EvapCoolingResponse:
    """
    Рассчитывает параметры системы испарительного охлаждения (Pad & Fan).

    **Физика:**
    Воздух охлаждается, испаряя воду в целлюлозной панели.
    Предел охлаждения — температура мокрого термометра (T_wb).
    Фактическая температура после панели: T_pad = T_db − η × (T_db − T_wb).

    **Эффективность насыщения η (saturation efficiency):**
    η = (T_db_in − T_db_out) / (T_db_in − T_wb_in) — степень приближения к T_wb.
    Интерполируется из таблиц SANHE по фактической скорости воздуха через панель.
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
        num_birds         = req.num_birds if req.bird_age_days else 0,
        total_fan_25pa_m3h = req.total_fan_25pa_m3h,
        bird_weight_kg    = _bird_weight_kg(req.bird_age_days, req.growth_profile_id) if req.num_birds and req.bird_age_days else 0.0,
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
        pad_v_min_ms            = r.pad_v_min_ms,
        pad_v_max_ms            = r.pad_v_max_ms,
        pad_pressure_drop_pa    = r.pad_pressure_drop_pa,
        water_flow_lpm          = r.water_flow_lpm,
        water_per_hour_l        = r.water_per_hour_l,
        cooling_sufficient      = r.cooling_sufficient,
        temp_margin_c           = r.temp_margin_c,
        recommended_pad_area_m2 = r.recommended_pad_area_m2,
        status_code             = r.status_code,
        status_level            = r.status_level,
        t_dew_c                 = r.t_dew_c,
        water_supply_t_c        = r.water_supply_t_c,
        water_regime            = r.water_regime,
        air_temp_rise_c         = r.air_temp_rise_c,
        t_fan_end_c             = r.t_fan_end_c,
        airflow_m3h             = r.airflow_m3h,
        airflow_basis           = r.airflow_basis,
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
    fan_capacity_25pa_m3h: float = Field(
        0.0, ge=0,
        description="Производительность одного вентилятора при 25 Па, м³/ч (0 = неизвестна → расчёт по 0 Па)",
    )

    # Поголовье — для нагрева воздуха вдоль корпуса; масса — из профиля роста по возрасту
    num_birds: int = Field(0, ge=0, le=200_000, description="Поголовье (0 = нагрев вдоль корпуса не учитывать)")
    growth_profile_id: Optional[str] = Field(None, description="Профиль роста для массы птицы (по умолчанию — из настроек)")

    @model_validator(mode="after")
    def _rating_point_below_free_air(self):
        # При 25 Па вентилятор не может дать больше, чем при 0 Па
        if self.fan_capacity_25pa_m3h and self.fan_capacity_25pa_m3h >= self.fan_capacity_m3h:
            raise CalcError("fan_25pa_above_free_air")
        return self


class TunnelSpeedResponse(BaseModel):
    cross_section_m2:       float
    total_airflow_m3h:      float
    air_velocity_ms:        float
    air_velocity_fpm:       float
    wind_chill_c:           float
    effective_temp_c:       float
    thi_value:              float
    thi_status:             str    # normal | alert | danger | critical
    dynamic_pressure_pa:    float
    inlet_area_m2:          float
    inlet_velocity_ms:      float
    inlet_sp_pa:            float
    inlet_status:           str    # good | normal | high | critical
    total_pressure_pa:      float
    target_v_min_ms:        float
    target_v_max_ms:        float
    velocity_status:        str    # too_low | below_target | ok | above_target | too_high
    fans_needed_for_target: int
    status_code:            str    # код оценки, перевод на клиенте
    status_level:           str    # ok | warn | danger
    bird_comfort_target_c:    float
    tunnel_sufficient:        bool
    t_outdoor_tunnel_limit_c: float
    temp_margin_c:            float
    velocity_basis:           str
    fan_operating_m3h:        float
    air_temp_rise_c:          float = 0.0
    t_fan_end_c:              float = 0.0
    end_to_end_rise_excessive: bool = False
    speed_sufficient:         bool = True
    heat_sufficient:          bool = True
    effective_temp_at_target_speed_c: float = 0.0
    tunnel_action:            str = "ok"     # ok | add_fans | add_fans_heat | add_fans_and_pads | pads
    bird_weight_kg:           float = 0.0   # масса из профиля, по которой считан нагрев


@router.post(
    "/tunnel_speed",
    response_model=TunnelSpeedResponse,
    summary="Скорость воздуха в туннеле — ветровое охлаждение (UGA)",
)
def calc_tunnel_speed(req: TunnelSpeedRequest) -> TunnelSpeedResponse:
    """
    Рассчитывает скорость воздуха в туннеле, ветровое охлаждение и THVI (Tao & Xin 2003).

    **Ветровое охлаждение:** таблица T × RH × V; выше 29.4 °C эффект не растёт (UGA),
    к 37.8 °C гаснет (температура поверхности птицы). Оценка — у вентиляторов: воздух
    нагрет теплом птицы по пути (num_birds > 0).

    **THVI (Tao & Xin 2003, бройлеры):** (0.85·T_db + 0.15·T_wb)·V^−0.058
    - < 35 — Норма
    - 35–38 — Тревога
    - 38–40 — Опасность
    - > 40 — Критично

    **Рекомендуемая скорость по возрасту:**
    - 1–21 день: 1.5–2.0 м/с
    - 22–35 дней: 2.0–2.5 м/с
    - 36–42 дня: 2.5–3.0 м/с
    """
    weight_kg = _bird_weight_kg(req.bird_age_days, req.growth_profile_id) if req.num_birds > 0 else 0.0

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
        fan_capacity_25pa_m3h = req.fan_capacity_25pa_m3h,
        num_birds        = req.num_birds,
        bird_weight_kg   = weight_kg,
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
        status_code               = r.status_code,
        status_level              = r.status_level,
        bird_comfort_target_c     = r.bird_comfort_target_c,
        tunnel_sufficient         = r.tunnel_sufficient,
        t_outdoor_tunnel_limit_c  = r.t_outdoor_tunnel_limit_c,
        temp_margin_c             = r.temp_margin_c,
        air_temp_rise_c           = r.air_temp_rise_c,
        t_fan_end_c               = r.t_fan_end_c,
        end_to_end_rise_excessive = r.end_to_end_rise_excessive,
        speed_sufficient          = r.speed_sufficient,
        heat_sufficient           = r.heat_sufficient,
        effective_temp_at_target_speed_c = r.effective_temp_at_target_speed_c,
        tunnel_action             = r.tunnel_action,
        bird_weight_kg            = round(weight_kg, 3),
        velocity_basis            = r.velocity_basis,
        fan_operating_m3h         = r.fan_operating_m3h,
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
        static_pressure_pa = result.static_pressure_pa,
    )
