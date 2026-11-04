from __future__ import annotations

import math
from typing import Literal, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..api_errors import api_error, from_calc_error
from ..core.bird_heat import animal_heat_per_bird
from ..core.calc_core import compute, CalcInput, CalcResult
from ..core.construction import HouseGeometry
from ..core.errors import CalcError
from ..core.growth_profiles import ProfileNotFound, load_profile
from ..core import breeder_norms, layer_norms, turkey_norms
from ..core.ventilation_design import (
    CAGE_AISLE_SPEED_MS,
    CAGE_BIRD_SPEED_SHARE,
    CageRow,
    cage_free_section_m2,
    check_species,
)
from ..core.survival import survival_fraction
from ..core.tunnel_speed_calc import target_speed_range
from ..core.app_config import load_app_config


router = APIRouter()


def _resolve_cage_section(payload, housing: str) -> float | None:
    if housing != "cages":
        return None
    if (
        payload.house_width_m
        and payload.house_height_m
        and payload.cage_rows_count
        and payload.cage_row_width_m
        and payload.cage_row_height_m
    ):
        g = HouseGeometry(
            length_m=payload.house_length_m or 100.0,
            width_m=payload.house_width_m,
            wall_height_m=payload.house_height_m,
        )
        row = CageRow(
            width_m=payload.cage_row_width_m,
            height_m=payload.cage_row_height_m,
            count=payload.cage_rows_count,
        )
        return cage_free_section_m2(g, (row,))
    return None


class CalcIn(BaseModel):
    house: str = Field(..., min_length=1, max_length=64)
    birds: int = Field(..., ge=1, le=200000)
    age_days: int = Field(..., ge=1, le=700)
    # Профиль роста из библиотеки; не задан → профиль по умолчанию из настроек
    growth_profile_id: str | None = Field(None, pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    # Целевая RH в корпусе (таблица ощущаемой температуры Ross Handbook 2025 — 40–70 %)
    target_rh: float | None = Field(None, ge=40, le=70)
    outside_t: float = Field(..., ge=-40, le=50, description="Outside air temperature, °C")
    outside_rh: float = Field(60.0, ge=0, le=100, description="Outside relative humidity, %")
    heater_on: bool = Field(False, description="Heater correction enabled")
    user_max_m3h: float | None = Field(None, ge=0, description="System maximum capacity (m3/hour). Optional")
    # Сечение корпуса для туннельного расхода (ширина, средняя высота стена/конёк и длина)
    house_width_m: float | None = Field(None, gt=0, le=200)
    house_height_m: float | None = Field(None, gt=0, le=30)
    house_length_m: float | None = Field(None, gt=0, le=500)
    housing: Literal["floor_litter", "cages"] | None = None
    cage_rows_count: int | None = Field(None, ge=1, le=20)
    cage_row_width_m: float | None = Field(None, gt=0, le=5)
    cage_row_height_m: float | None = Field(None, gt=0, le=10)
    tunnel_mode: Literal["speed", "exchange", "max_both"] = "speed"
    v_tunnel_ms: float | None = Field(None, ge=0.5, le=6.0)
    tunnel_exchange_s: float = Field(45.0, ge=20.0, le=180.0)


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
    tunnel_mode: str = "speed"
    tunnel_basis: str = "speed"


@router.post("/minmax", response_model=CalcOut)
def minmax(payload: CalcIn):
    cfg = load_app_config()
    try:
        profile = load_profile(payload.growth_profile_id or cfg.default_growth_profile)
        housing = payload.housing or ("cages" if profile.species == "layer" else "floor_litter")
        cages = housing == "cages"
        cage_section = _resolve_cage_section(payload, housing)
    except ProfileNotFound as e:
        raise api_error(404, "profile_not_found", id=str(e))
    except ValueError as e:
        raise from_calc_error(e)

    ci = CalcInput(
        birds=payload.birds,
        age_days=payload.age_days,
        outside_t=payload.outside_t,
        outside_rh=payload.outside_rh,
        heater_on=payload.heater_on,
        house_width_m=payload.house_width_m if (not cages or cage_section is not None) else None,
        house_height_m=payload.house_height_m if (not cages or cage_section is not None) else None,
        house_length_m=payload.house_length_m,
        tunnel_section_m2=cage_section,
        growth_profile_id=payload.growth_profile_id,
        target_rh=payload.target_rh,
        house_id=payload.house,
    )
    overrides: dict = dict(tunnel_mode=payload.tunnel_mode, tunnel_exchange_s=payload.tunnel_exchange_s)
    if cages:
        overrides["bird_speed_share"] = CAGE_BIRD_SPEED_SHARE
        overrides["v_tunnel_ms"] = payload.v_tunnel_ms if payload.v_tunnel_ms is not None else 4.5
    elif payload.v_tunnel_ms is not None:
        overrides["v_tunnel_ms"] = payload.v_tunnel_ms
    cr = _compute_or_http_error(ci, **overrides)

    q_min = round(cr.q_min_m3h, 3)
    if cages and profile.species == "broiler":
        cr_hot = _compute_or_http_error(ci, **overrides, bird_heat_model=animal_heat_per_bird)
        q_max_nominal = round(max(cr_hot.q_max_m3h, cr.q_min_m3h), 3)
    else:
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
        tunnel_mode=payload.tunnel_mode,
        tunnel_basis=cr.tunnel_basis,
    )


def _compute_or_http_error(ci: CalcInput, **overrides) -> CalcResult:
    """Ошибки данных профиля → понятный HTTP-ответ вместо 500."""
    try:
        return compute(ci, **overrides)
    except ProfileNotFound as e:
        raise api_error(404, "profile_not_found", id=str(e))
    except ValueError as e:
        raise from_calc_error(e)


# ---- Summary for 7 points by season ----
class SummaryIn(BaseModel):
    house: str = Field(..., min_length=1, max_length=64)
    birds: int = Field(..., ge=1, le=200000)
    # Профиль роста из библиотеки; не задан → профиль по умолчанию из настроек
    growth_profile_id: str | None = Field(None, pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    # Целевая RH в корпусе (таблица ощущаемой температуры Ross Handbook 2025 — 40–70 %)
    target_rh: float | None = Field(None, ge=40, le=70)
    outside_t: float = Field(15.0, ge=-40, le=50, description="Outside air temperature, °C")
    outside_rh: float = Field(60.0, ge=0, le=100, description="Outside relative humidity, %")
    user_max_m3h: float | None = Field(None, ge=0)
    heater_on: bool = Field(False)
    # Сечение корпуса для туннельного расхода (ширина, средняя высота стена/конёк и длина)
    house_width_m: float | None = Field(None, gt=0, le=200)
    house_height_m: float | None = Field(None, gt=0, le=30)
    house_length_m: float | None = Field(None, gt=0, le=500)
    housing: Literal["floor_litter", "cages"] | None = None
    cage_rows_count: int | None = Field(None, ge=1, le=20)
    cage_row_width_m: float | None = Field(None, gt=0, le=5)
    cage_row_height_m: float | None = Field(None, gt=0, le=10)
    # Способ расчёта туннельного режима: по скорости, по времени воздухообмена или по большему из двух
    tunnel_mode: Literal["speed", "exchange", "max_both"] = "speed"
    v_tunnel_ms: float | None = Field(None, ge=0.5, le=6.0)
    tunnel_exchange_s: float = Field(45.0, ge=20.0, le=180.0)
    # Индейка (brooder / grow_out), родительское стадо и несушка (rearing / production): этап и его дни.
    # Второй этап начинается с дня пересадки: с него точки профиля и падёж корпуса.
    # Не заданы дни — у индейки 1–35 и 36..конец, у РС 1–140 и 141..конец, у несушки 1–119 и 120..конец профиля.
    stage: Optional[Literal["brooder", "grow_out", "rearing", "production"]] = None
    first_day: Optional[int] = Field(None, ge=1, le=699)
    last_day: Optional[int] = Field(None, ge=2, le=700)


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
    # Вид птицы профиля и дни, по которым шёл расчёт (у индейки — дни этапа)
    species: str = "broiler"
    housing: str = "floor_litter"
    tunnel_free_section_m2: float | None = None
    stage: Optional[str] = None
    first_day: int = 1
    last_day: int = 0
    tunnel_mode: str = "speed"
    tunnel_basis: str = "speed"
    v_tunnel_ms: float = 2.5
    tunnel_exchange_target_s: float = 45.0
    males_auto_added: bool = False


@router.post("/summary7", response_model=SummaryOut)
def summary7(payload: SummaryIn):
    outside_t = payload.outside_t
    # load_app_config не бросает исключений: битый файл → умолчания с записью в лог
    cfg = load_app_config()
    try:
        profile = load_profile(payload.growth_profile_id or cfg.default_growth_profile)
    except ProfileNotFound as e:
        raise api_error(404, "profile_not_found", id=str(e))
    turkey = profile.species == "turkey"
    breeder = profile.species == "broiler_breeder"
    layer = profile.species == "layer"
    staged = turkey or breeder or layer
    housing = payload.housing or ("cages" if layer else "floor_litter")
    cages = housing == "cages"
    try:
        # Те же проверки, что в API v1: индейке, РС и несушке нужен этап, бройлеру он запрещён.
        # Предел дня бройлера здесь не нужен — дни берутся из настроек хозяйства
        check_species(profile, housing, payload.stage, 0)
        cage_section = _resolve_cage_section(payload, housing)
        if not staged and (payload.first_day or payload.last_day):
            raise CalcError("stage_turkey_only", stage="days")
        if turkey:
            first = payload.first_day or (1 if payload.stage == turkey_norms.BROODER else 36)
            last = payload.last_day or (35 if payload.stage == turkey_norms.BROODER
                                        else max(profile.daily()))
            if first >= last:
                raise CalcError("first_day_after_last", first_day=first, last_day=last)
        elif breeder:
            first = payload.first_day or (1 if payload.stage == breeder_norms.REARING else 141)
            last = payload.last_day or (breeder_norms.REARING_LAST_DAY if payload.stage == breeder_norms.REARING
                                        else max(profile.daily()))
            if first >= last:
                raise CalcError("first_day_after_last", first_day=first, last_day=last)
        elif layer:
            first = payload.first_day or (1 if payload.stage == layer_norms.REARING else 120)
            last = payload.last_day or (layer_norms.REARING_LAST_DAY if payload.stage == layer_norms.REARING
                                        else max(profile.daily()))
            if first >= last:
                raise CalcError("first_day_after_last", first_day=first, last_day=last)
    except ValueError as e:
        raise from_calc_error(e)

    if staged:
        # Этап индейки, РС или несушки — свой цикл: падёж от дня посадки в корпус, проектная скорость тоннеля по этапу
        cycle = last
        if cages:
            v_default = 4.5
        elif turkey:
            v_default = turkey_norms.TUNNEL_SPEED_MS
        else:
            v_default = breeder_norms.TUNNEL_SPEED_MS[payload.stage]
        v_tunnel = payload.v_tunnel_ms if payload.v_tunnel_ms is not None else v_default
        overrides = dict(
            cycle_days=last,
            placement_day=first,
            v_tunnel_ms=v_tunnel,
            stage=payload.stage,
            tunnel_mode=payload.tunnel_mode,
            tunnel_exchange_s=payload.tunnel_exchange_s,
        )
        if cages:
            overrides["bird_speed_share"] = CAGE_BIRD_SPEED_SHARE
        days = sorted({first, last} | {d for d in range(7 * math.ceil(first / 7), last, 7) if d > first})
        survival = lambda d: survival_fraction(d - first + 1, cfg.total_mortality_pct, last - first + 1)
    else:
        first = 1
        cycle = max(cfg.cycle_days, 7)
        v_def_broiler = 4.5 if cages else float(getattr(cfg, "v_tunnel_ms", 2.5))
        v_tunnel = payload.v_tunnel_ms if payload.v_tunnel_ms is not None else v_def_broiler
        overrides = dict(
            v_tunnel_ms=v_tunnel,
            tunnel_mode=payload.tunnel_mode,
            tunnel_exchange_s=payload.tunnel_exchange_s,
        )
        if cages:
            overrides["bird_speed_share"] = CAGE_BIRD_SPEED_SHARE
        # Еженедельные контрольные точки + последний день цикла
        days = sorted(set([1] + list(range(7, cycle, 7)) + [cycle]))
        survival = lambda d: survival_fraction(d, cfg.total_mortality_pct, cfg.cycle_days)
    rows: list[SummaryRow] = []

    for d in days:
        ci = CalcInput(
            birds=payload.birds,
            age_days=d,
            outside_t=outside_t,
            outside_rh=payload.outside_rh,
            heater_on=payload.heater_on,
            house_width_m=payload.house_width_m if (not cages or cage_section is not None) else None,
            house_id=payload.house,
            house_height_m=payload.house_height_m if (not cages or cage_section is not None) else None,
            house_length_m=payload.house_length_m,
            tunnel_section_m2=cage_section,
            growth_profile_id=payload.growth_profile_id,
            target_rh=payload.target_rh,
        )
        cr = _compute_or_http_error(ci, **overrides)
        q_min = round(cr.q_min_m3h, 3)
        if cages and profile.species == "broiler":
            cr_hot = _compute_or_http_error(ci, **overrides, bird_heat_model=animal_heat_per_bird)
            q_max_nominal = round(max(cr_hot.q_max_m3h, cr.q_min_m3h), 3)
        else:
            q_max_nominal = round(cr.q_max_m3h, 3)
        q_max_final = q_max_nominal
        q_min_pct = None
        q_max_pct = None
        capacity_insufficient = False
        # Эффективное число птиц на этот день (в продуктивном периоде РС включает и петухов)
        birds_eff = cr.birds_alive if cr.birds_alive is not None else payload.birds * survival(d)
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

    if cages and payload.tunnel_mode == "speed" and payload.v_tunnel_ms is None:
        v_min_target, v_max_target = CAGE_AISLE_SPEED_MS
    elif cr.v_tunnel_design_ms is not None and (cages or staged or payload.v_tunnel_ms is not None or payload.tunnel_mode != "speed"):
        v_min_target = v_max_target = round(cr.v_tunnel_design_ms, 2)
    elif staged:
        v_min_target = v_max_target = v_tunnel
    else:
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
        species=profile.species,
        housing=housing,
        tunnel_free_section_m2=round(cage_section, 2) if cage_section is not None else None,
        stage=payload.stage,
        first_day=first,
        last_day=cycle,
        tunnel_mode=payload.tunnel_mode,
        tunnel_basis=cr.tunnel_basis,
        v_tunnel_ms=v_tunnel,
        tunnel_exchange_target_s=payload.tunnel_exchange_s,
        males_auto_added=bool(breeder and payload.stage == breeder_norms.PRODUCTION and profile.sex == "female"),
    )
