from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..api_errors import api_error, from_calc_error
from ..core.calc_core import compute, CalcInput, CalcResult
from ..core.growth_profiles import ProfileNotFound
from ..core.survival import survival_fraction
from ..core.tunnel_speed_calc import target_speed_range
from ..core.app_config import load_app_config


router = APIRouter()


class CalcIn(BaseModel):
    house: str = Field(..., min_length=1, max_length=64)
    birds: int = Field(..., ge=1, le=60000)
    age_days: int = Field(..., ge=1, le=63)
    # Профиль роста из библиотеки; не задан → профиль по умолчанию из настроек
    growth_profile_id: str | None = Field(None, pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    # Целевая RH в корпусе (таблица ощущаемой температуры Ross Handbook 2025 — 40–70 %)
    target_rh: float | None = Field(None, ge=40, le=70)
    outside_t: float = Field(..., ge=-40, le=50, description="Outside air temperature, °C")
    outside_rh: float = Field(60.0, ge=0, le=100, description="Outside relative humidity, %")
    heater_on: bool = Field(False, description="Heater correction enabled")
    user_max_m3h: float | None = Field(None, ge=0, description="System maximum capacity (m3/hour). Optional")
    # Сечение корпуса для туннельного расхода (ширина и средняя высота стена/конёк)
    house_width_m: float | None = Field(None, gt=0, le=200)
    house_height_m: float | None = Field(None, gt=0, le=30)


class CalcOut(BaseModel):
    q_min_m3h: float
    q_max_m3h: float  # final (capped if capacity provided)
    q_max_nominal_m3h: float  # before capacity capping
    weight_used_g: float
    profile_day_resolved: int
    rates: dict
    day_setpoints: dict | None = None  # {min_temp_c, rv_percent}
    heater_air_m3h: float | None = None  # Additional air for gas heaters
    heater_duty_cycle: float | None = None  # Heater duty cycle (0..1)
    tunnel_active: bool = False  # Tunnel mode active under current conditions
    qmin_basis: str = "co2"  # "co2" | "moisture"
    growth_profile_id: str | None = None  # профиль роста, по которому шёл расчёт
    # Снаружи воздух не суше целевого: вентиляцией RH не удержать (Qmin — по CO₂)
    humidity_uncontrollable: bool = False
    heater_insufficient: bool = False   # горелок не хватает даже на 100 %
    heater_note: str | None = None
    calibration_ignored: dict | None = None   # почему UA калибровки не применён: {code, params}
    # Qmin больше заданной мощности установки: вентиляторов не хватает даже на минимум
    capacity_insufficient: bool = False
    # Требуемый туннельный расход корпуса v × S × 3600 (None — размеры не заданы)
    tunnel_requirement_m3h: float | None = None
    # Нужен туннельный расход, а размеров нет: Qmax не посчитан (равен Qmin)
    house_geometry_missing: bool = False


@router.post("/minmax", response_model=CalcOut)
def minmax(payload: CalcIn):
    ci = CalcInput(
        birds=payload.birds,
        age_days=payload.age_days,
        outside_t=payload.outside_t,
        outside_rh=payload.outside_rh,
        heater_on=payload.heater_on,
        house_width_m=payload.house_width_m,
        house_height_m=payload.house_height_m,
        growth_profile_id=payload.growth_profile_id,
        target_rh=payload.target_rh,
        house_id=payload.house,
    )
    cr = _compute_or_http_error(ci)

    q_min = round(cr.q_min_m3h, 3)
    q_max_nominal = round(cr.q_max_m3h, 3)
    q_max_final = q_max_nominal
    capacity_insufficient = False
    if payload.user_max_m3h is not None:
        q_max_final = min(q_max_nominal, float(payload.user_max_m3h))
        # Qmin — биологическое требование (CO₂/влага), его НЕ подгоняем под железо:
        # раньше здесь было q_min = min(q_min, q_max_final), и нехватка вентиляторов
        # маскировалась заниженным минимумом. Теперь отдаём честный Qmin и флаг.
        capacity_insufficient = q_min > q_max_final

    return CalcOut(
        q_min_m3h=q_min,
        q_max_m3h=q_max_final,
        q_max_nominal_m3h=q_max_nominal,
        weight_used_g=cr.weight_used_g,
        profile_day_resolved=cr.profile_day_resolved,
        rates={
            "per_bird": {
                "min": round(cr.rates_per_bird_min, 4),
                "max": round(cr.rates_per_bird_max, 4),
            },
            "per_kg": {
                "min": round(cr.rates_per_kg_min, 4),
                "max": round(cr.rates_per_kg_max, 4),
            },
        },
        day_setpoints=(
            {
                "min_temp_c": cr.min_temp_c,
                "rv_percent": cr.rv_percent,
            }
            if (cr.min_temp_c is not None or cr.rv_percent is not None)
            else None
        ),
        heater_air_m3h=cr.heater_air_m3h,
        heater_duty_cycle=cr.heater_duty_cycle,
        tunnel_active=cr.tunnel_active,
        qmin_basis=cr.qmin_basis,
        capacity_insufficient=capacity_insufficient,
        tunnel_requirement_m3h=cr.tunnel_requirement_m3h,
        house_geometry_missing=cr.house_geometry_missing,
        growth_profile_id=cr.growth_profile_id,
        humidity_uncontrollable=cr.humidity_uncontrollable,
        heater_insufficient=cr.heater_insufficient,
        heater_note=cr.heater_note,
        calibration_ignored=cr.calibration_ignored,
    )


def _compute_or_http_error(ci: CalcInput) -> CalcResult:
    """Ошибки данных профиля → понятный HTTP-ответ вместо 500."""
    try:
        return compute(ci)
    except ProfileNotFound as e:
        raise api_error(404, "profile_not_found", id=str(e))
    except ValueError as e:
        raise from_calc_error(e)


# ---- Summary for 7 points by season ----
class SummaryIn(BaseModel):
    house: str = Field(..., min_length=1, max_length=64)
    birds: int = Field(..., ge=1, le=60000)
    # Профиль роста из библиотеки; не задан → профиль по умолчанию из настроек
    growth_profile_id: str | None = Field(None, pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    # Целевая RH в корпусе (таблица ощущаемой температуры Ross Handbook 2025 — 40–70 %)
    target_rh: float | None = Field(None, ge=40, le=70)
    outside_t: float = Field(15.0, ge=-40, le=50, description="Outside air temperature, °C")
    outside_rh: float = Field(60.0, ge=0, le=100, description="Outside relative humidity, %")
    user_max_m3h: float | None = Field(None, ge=0)
    heater_on: bool = Field(False)
    # Сечение корпуса для туннельного расхода (ширина и средняя высота стена/конёк)
    house_width_m: float | None = Field(None, gt=0, le=200)
    house_height_m: float | None = Field(None, gt=0, le=30)


class SummaryRow(BaseModel):
    day: int
    min_temp_c: float | None
    weight_g: float | None
    birds_eff: float | None = None
    q_min_m3h: float
    q_min_pct: float | None = None
    q_max_nominal_m3h: float
    q_max_m3h: float
    q_max_pct: float | None = None
    # Qmin больше заданной мощности установки (см. CalcOut.capacity_insufficient)
    capacity_insufficient: bool = False
    house_geometry_missing: bool = False
    humidity_uncontrollable: bool = False
    heater_insufficient: bool = False   # горелок не хватает даже на 100 %
    heater_note: str | None = None      # горелки без загрузки: heater_data_missing | heater_full_duty_estimate
    condensation_risk: bool = False     # поверхность ограждения холоднее точки росы внутри
    surface_temp_c: float | None = None
    dew_point_inside_c: float | None = None
    calibration_ignored: dict | None = None   # почему UA калибровки не применён: {code, params}


class SummaryOut(BaseModel):
    house: str
    birds: int
    user_max_m3h: float | None
    growth_profile_id: str | None = None  # профиль роста, по которому шёл расчёт
    rows: list[SummaryRow]
    # Цель скорости туннеля на последний день цикла — та же таблица, что у вкладки
    # туннеля: физическая проверка профиля судит установленную мощность по ней
    tunnel_target_day: int = 0
    tunnel_target_v_min_ms: float = 0.0
    tunnel_target_v_max_ms: float = 0.0


@router.post("/summary7", response_model=SummaryOut)
def summary7(payload: SummaryIn):
    outside_t = payload.outside_t
    # load_app_config не бросает исключений: битый файл → умолчания с записью в лог
    cfg = load_app_config()
    cycle = max(cfg.cycle_days, 7)
    # Еженедельные контрольные точки + последний день цикла
    days = sorted(set([1] + list(range(7, cycle, 7)) + [cycle]))
    rows: list[SummaryRow] = []

    for d in days:
        ci = CalcInput(
            birds=payload.birds,
            age_days=d,
            outside_t=outside_t,
            outside_rh=payload.outside_rh,
            heater_on=payload.heater_on,
            house_width_m=payload.house_width_m,
            house_id=payload.house,
            house_height_m=payload.house_height_m,
            growth_profile_id=payload.growth_profile_id,
            target_rh=payload.target_rh,
        )
        cr = _compute_or_http_error(ci)
        q_min = round(cr.q_min_m3h, 3)
        q_max_nominal = round(cr.q_max_m3h, 3)
        q_max_final = q_max_nominal
        q_min_pct = None
        q_max_pct = None
        capacity_insufficient = False
        # Эффективное число птиц на этот день (для последующих представлений на голову/кг)
        birds_eff = payload.birds * survival_fraction(d, cfg.total_mortality_pct, cfg.cycle_days)
        if payload.user_max_m3h is not None:
            q_max_final = min(q_max_nominal, float(payload.user_max_m3h))
            # Qmin не обрезаем — см. комментарий в minmax(); q_min_pct может быть > 100 %
            capacity_insufficient = q_min > q_max_final
            if payload.user_max_m3h > 0:
                q_min_pct = round(100.0 * q_min / payload.user_max_m3h, 3)
                q_max_pct = round(100.0 * q_max_final / payload.user_max_m3h, 3)
        rows.append(
            SummaryRow(
                day=d,
                min_temp_c=cr.min_temp_c,
                weight_g=cr.weight_used_g,
                birds_eff=birds_eff,
                q_min_m3h=q_min,
                q_min_pct=q_min_pct,
                q_max_nominal_m3h=q_max_nominal,
                q_max_m3h=q_max_final,
                q_max_pct=q_max_pct,
                capacity_insufficient=capacity_insufficient,
                house_geometry_missing=cr.house_geometry_missing,
                humidity_uncontrollable=cr.humidity_uncontrollable,
                heater_insufficient=cr.heater_insufficient,
                heater_note=cr.heater_note,
                condensation_risk=cr.condensation_risk,
                surface_temp_c=None if cr.surface_temp_c is None else round(cr.surface_temp_c, 1),
                dew_point_inside_c=None if cr.dew_point_inside_c is None else round(cr.dew_point_inside_c, 1),
                calibration_ignored=cr.calibration_ignored,
            )
        )

    v_min_target, v_max_target = target_speed_range(cycle)
    return SummaryOut(
        house=payload.house,
        birds=payload.birds,
        user_max_m3h=payload.user_max_m3h,
        growth_profile_id=cr.growth_profile_id,
        rows=rows,
        tunnel_target_day=cycle,
        tunnel_target_v_min_ms=v_min_target,
        tunnel_target_v_max_ms=v_max_target,
    )
