"""
Проектный расчёт вентиляции и обогрева на цикл — API v1, POST /ventilation-designs.

Сценарий: корпуса ещё нет (или считают новый) — «помещение такое, поголовье такое,
регион такой: сколько воздуха и киловатт мне нужно иметь?». Ничего из сохранённых
настроек хозяйства не читается: всё приходит в DesignInput, давление площадки —
из высоты в запросе (psychro.site_pressure).

Расчёт по дням идёт через ТУ ЖЕ модель, что и интерфейс (calc_core.compute_with):
  • зима (расчётная 99.6 %) → Qmin (CO₂, влага), потребность в тепле, конденсат;
  • лето (расчётная 0.4 %) → Qmax (тепловой баланс / туннель).
Отличия проекта от интерфейса — только во входных данных, а не в формулах:
  • UA — из измерения или из конструкции по слоям (construction);
  • утечки — пол обмена воздуха для обогрева: max(Qmin, Q при 4 Па);
  • клетки — деление тепла по худшему краю для каждой величины и туннель по
    свободному сечению (docs/api/v1/README.md, «Клетки»).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from .bird_heat import animal_heat_per_bird, house_heat_per_bird
from .building_thermal import HeaterConfig
from .calc_core import CalcInput, CalcParams, HouseThermal, compute_with
from .construction import (
    EnvelopeUA, HouseGeometry, Surface, envelope_areas, envelope_ua,
    surface_resistance_si,
)
from .errors import CalcError
from .growth_profiles import load_profile
from .leakage_calc import RHO_AIR_KG_M3, _TIGHTNESS_THRESHOLDS
from .psychro import dew_point_c, pressure_at_altitude_pa, site_pressure


# ─── Нормы ────────────────────────────────────────────────────────────────────

# Cobb Broiler Management Guide 2021, гл. 9 (сверено с PDF 2026-10-19):
#   §9.1 (с. 69): установленная мощность вентиляторов минвентиляции — 0.3 м³/мин
#     на м² (18 м³/ч·м²) в жарком климате, 0.61–0.77 (36.6–46.2) — в холодном;
#   §9.7 (с. 77): мощность туннеля 165–200 м³/ч на м² пола И смена воздуха за
#     40–50 с. Критерии разные: по площади не видно высоты корпуса, а корпус без
#     потолка (объём вдвое больше) при 200 м³/ч·м² продувается за ~60 с и всего
#     ~1.9 м/с. Берём больший из двух — оба из одного источника.
MIN_VENT_INSTALLED_HOT_M3H_M2 = (18.0, 18.0)
MIN_VENT_INSTALLED_COLD_M3H_M2 = (36.6, 46.2)
TUNNEL_CAPACITY_M3H_M2 = (165.0, 200.0)
TUNNEL_AIR_EXCHANGE_S = (50.0, 40.0)     # (нижняя граница расхода, верхняя)

# Граница «холодного климата» для нормы §9.1 — у Cobb числа нет: берём зиму
# ниже нуля и отдаём это допущением (min_vent_climate_class)
COLD_CLIMATE_WINTER_C = 0.0

# Клеточный зал (практика эксплуатации владельца, 2026-10-19): 4–5 м/с в
# проходах, чтобы у птицы в клетках было ~2–2.5 м/с
CAGE_AISLE_SPEED_MS = (4.0, 5.0)

# Батареи выше стены или почти без прохода — опечатка в сечении, а не корпус
CAGE_MIN_FREE_SHARE = 0.15

# Классы UGA → относительная утечка (м²/1000 м² пола) по ВЕРХНЕЙ границе класса:
# в безопасную для обогрева сторону. Границы — те же, что у теста герметичности
# (leakage_calc); у very_leaky верхней границы нет — 1.2 из таблицы UGA 2014
# («0.65–1.2» — третий класс), то есть оценка снизу
AIRTIGHTNESS_CLASS_RELATIVE = {cls: thr for thr, cls in _TIGHTNESS_THRESHOLDS}
AIRTIGHTNESS_CLASS_RELATIVE["very_leaky"] = 1.2
DEFAULT_AIRTIGHTNESS_CLASS = "moderate"

# Давление, при котором утечка греется всегда: ветер и тяга (~4 Па)
NATURAL_LEAK_PRESSURE_PA = 4.0

DEFAULT_HEATING_MARGIN_PCT = 15.0

SOURCES = {
    "cigr_1984": "CIGR (1984, rev. 1999) Climatization of Animal Houses, Report No. 2 — CO₂ norm",
    "cigr_2002": "CIGR (2002) Heat and moisture production at animal and house levels",
    "aarnink_2018": "Aarnink et al. (2018) Heat and moisture production in growing-finishing pigs "
                    "and broilers, CIGR Journal art. 4781 — animal-level sensible share 0.67",
    "ross_2025_t2_5": "Aviagen, Ross Broiler Management Handbook 2025, table 2.5 — temperature by RH",
    "cobb_2021_9_1": "Cobb Broiler Management Guide 2021, §9.1 — installed minimum-ventilation capacity",
    "cobb_2021_9_7": "Cobb Broiler Management Guide 2021, §9.7 — tunnel capacity 165–200 m³/h·m², "
                     "air exchange 40–50 s",
    "uga_leakage": "UGA Poultry House Leakage Estimating Spreadsheet 2014; Poultry411 Tightness Calculator",
    "ashrae_2017_ch1": "ASHRAE Handbook Fundamentals 2017, ch. 1 — psychrometrics, standard atmosphere",
    "practice_cage_tunnel_2026": "Owner's operating practice for cage houses, 2026-10-19: "
                                 "4–5 m/s in aisles for ~2–2.5 m/s at the birds",
}


# ─── Входные данные ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class CageRow:
    width_m: float
    height_m: float
    count: int = 1


@dataclass(frozen=True)
class Airtightness:
    """Одно из трёх: класс UGA, относительная утечка, утечка при 4 Па из теста."""
    tightness_class: Optional[str] = None
    relative_leakage: Optional[float] = None
    leak_at_4pa_m3h: Optional[float] = None


@dataclass(frozen=True)
class DesignInput:
    geometry: HouseGeometry
    birds: int
    growth_profile_id: str
    cycle_days: int
    winter_design_c: float
    summer_design_db_c: float
    summer_design_rh_pct: float
    housing: str = "floor_litter"
    altitude_m: float = 0.0
    # Ограждения: измеренный UA ИЛИ конструкции (walls и roof обязательны вместе)
    ua_w_per_k: Optional[float] = None
    walls: Optional[Surface] = None
    roof: Optional[Surface] = None
    end_walls: Optional[Surface] = None
    airtightness: Optional[Airtightness] = None
    cage_rows: tuple[CageRow, ...] = ()
    mortality_pct: float = 4.0
    target_rh_pct: Optional[float] = None
    heater: Optional[HeaterConfig] = None
    heating_margin_pct: float = DEFAULT_HEATING_MARGIN_PCT


# ─── Результат ────────────────────────────────────────────────────────────────

@dataclass
class DesignDay:
    day: int
    weight_g: float
    target_temp_c: float
    qmin_m3h: float
    qmin_basis: str
    qmax_m3h: float
    heating_need_kw: float
    air_exchange_m3h: float
    air_exchange_basis: str


@dataclass
class Note:
    """Находка или допущение: машинный код + параметры (текст — у клиента)."""
    code: str
    params: dict = field(default_factory=dict)
    severity: Optional[str] = None      # только у находок: info | warning | critical
    source_id: Optional[str] = None


@dataclass
class DesignResult:
    envelope_ua_w_per_k: float
    days: list[DesignDay]
    peak: dict
    equipment: dict
    warnings: list[Note]
    assumptions: list[Note]
    source_ids: list[str]
    heaters_sufficient: Optional[bool] = None
    profile_source: Optional[str] = None


# ─── Части расчёта ────────────────────────────────────────────────────────────

def _mean_height_m(g: HouseGeometry) -> float:
    """Средняя высота сечения (стена + конёк) / 2 — как у туннеля в интерфейсе."""
    return (g.wall_height_m + (g.ridge_height_m or g.wall_height_m)) / 2.0


def cage_free_section_m2(g: HouseGeometry, rows: tuple[CageRow, ...]) -> float:
    """Свободное сечение клеточного зала = сечение корпуса − батареи, м²."""
    if not rows:
        raise CalcError("cage_section_missing")
    section = g.width_m * _mean_height_m(g)
    blocked = sum(r.count * r.width_m * r.height_m for r in rows)
    free = section - blocked
    too_tall = any(r.height_m > g.wall_height_m for r in rows)
    # Ряды стоят поперёк корпуса бок о бок — шире корпуса их не поставить
    too_wide = sum(r.count * r.width_m for r in rows) > g.width_m
    if too_tall or too_wide or free < CAGE_MIN_FREE_SHARE * section:
        raise CalcError("cage_section_implausible",
                        free_pct=round(100.0 * max(free, 0.0) / section, 1),
                        min_pct=round(100.0 * CAGE_MIN_FREE_SHARE))
    return free


def leak_at_4pa_m3h(floor_area_m2: float, airtight: Optional[Airtightness]) -> tuple[float, Optional[str]]:
    """
    Утечка при 4 Па, м³/ч, и класс, если он взят по умолчанию.

    ELA = относительная утечка × площадь пола / 1000; Q = ELA·√(2ΔP/ρ) с Cd = 1 и
    ρ = 1.184 — как в калькуляторе UGA (leakage_calc), иначе класс, определённый
    тестом, и класс, заданный здесь, означали бы разную утечку.
    """
    assumed: Optional[str] = None
    if airtight is not None and airtight.leak_at_4pa_m3h is not None:
        return airtight.leak_at_4pa_m3h, None
    if airtight is not None and airtight.relative_leakage is not None:
        relative = airtight.relative_leakage
    else:
        cls = airtight.tightness_class if airtight is not None and airtight.tightness_class else None
        if cls is None:
            cls = assumed = DEFAULT_AIRTIGHTNESS_CLASS
        relative = AIRTIGHTNESS_CLASS_RELATIVE[cls]
    ela_m2 = relative * floor_area_m2 / 1000.0
    q_m3s = ela_m2 * math.sqrt(2.0 * NATURAL_LEAK_PRESSURE_PA / RHO_AIR_KG_M3)
    return q_m3s * 3600.0, assumed


def _coldest_surface(env: Optional[EnvelopeUA]) -> Optional[tuple[str, float, float]]:
    """(элемент, U, R_si) с самой холодной внутренней поверхностью: наибольшее U·R_si."""
    if env is None:
        return None
    parts = [
        ("side_walls", env.side_walls_u, surface_resistance_si("wall")),
        ("end_walls", env.end_walls_u, surface_resistance_si("wall")),
        ("roof", env.roof_u, surface_resistance_si("roof", env.areas.roof_pitch_deg)),
    ]
    return max(parts, key=lambda p: p[1] * p[2])


# ─── Расчёт ───────────────────────────────────────────────────────────────────

def design(inp: DesignInput) -> DesignResult:
    with site_pressure(pressure_at_altitude_pa(inp.altitude_m)):
        return _design(inp)


def _design(inp: DesignInput) -> DesignResult:
    g = inp.geometry
    warnings: list[Note] = []
    assumptions: list[Note] = []
    source_ids = {"cigr_1984", "cigr_2002", "ross_2025_t2_5", "cobb_2021_9_1", "uga_leakage"}
    cages = inp.housing == "cages"

    # ── Ограждения ──
    env: Optional[EnvelopeUA] = None
    if inp.ua_w_per_k is not None:
        ua = inp.ua_w_per_k
    else:
        if inp.walls is None or inp.roof is None:
            raise CalcError("validation_failed", field="envelope")
        env = envelope_ua(g, inp.walls, inp.roof, inp.end_walls)
        ua = env.ua_w_per_k
        source_ids |= {"br443_2019_s3", "br443_2019_s4_3"}
        assumptions.append(Note("materials_iso_10456"))
        assumptions.append(Note("floor_not_included"))

    # ── Утечки ──
    floor_m2 = g.length_m * g.width_m
    q4_m3h, assumed_class = leak_at_4pa_m3h(floor_m2, inp.airtightness)
    if assumed_class:
        assumptions.append(Note("airtightness_class_assumed", {
            "class": assumed_class, "relative_leakage": AIRTIGHTNESS_CLASS_RELATIVE[assumed_class]}))

    # ── Туннель: сечение и цель скорости ──
    house_section = g.width_m * _mean_height_m(g)
    if cages:
        section = cage_free_section_m2(g, inp.cage_rows)
        speed_range = CAGE_AISLE_SPEED_MS
        tunnel_range = tuple(v * section * 3600.0 for v in speed_range)
        tunnel_source = "practice_cage_tunnel_2026"
        source_ids |= {"aarnink_2018", tunnel_source}
        assumptions += [Note("cages_heat_split_bounded"), Note("cages_bird_speed_from_aisle"),
                        Note("cage_through_flow_not_included")]
    else:
        section = house_section
        volume_m3 = house_section * g.length_m
        tunnel_range = tuple(max(n * floor_m2, volume_m3 * 3600.0 / t)
                             for n, t in zip(TUNNEL_CAPACITY_M3H_M2, TUNNEL_AIR_EXCHANGE_S))
        speed_range = tuple(q / 3600.0 / section for q in tunnel_range)
        tunnel_source = "cobb_2021_9_7"
    source_ids.add(tunnel_source)

    # Параметры модели: падёж и цикл — из запроса; туннель в днях — на верхней
    # границе цели (проектная мощность), остальное — значения интерфейса по умолчанию
    winter_params = CalcParams(total_mortality_pct=inp.mortality_pct, cycle_days=inp.cycle_days,
                               v_tunnel_ms=speed_range[1])
    # Клетки летом — явное тепло на уровне птицы (верхний край вилки): больше воздуха
    summer_params = CalcParams(total_mortality_pct=inp.mortality_pct, cycle_days=inp.cycle_days,
                               v_tunnel_ms=speed_range[1],
                               bird_heat_model=animal_heat_per_bird if cages else house_heat_per_bird)
    winter_thermal = HouseThermal(ua_w_per_k=ua, heater=inp.heater)
    summer_thermal = HouseThermal(ua_w_per_k=ua)

    # Зимой наружный воздух — насыщенный: при −10 °C это 1.6 г/кг против 1.3 при
    # 80 %, а большее влагосодержание даёт больший влажностный Qmin
    winter_rh = 100.0
    assumptions.append(Note("winter_rh_saturated"))

    common = dict(birds=inp.birds, growth_profile_id=inp.growth_profile_id,
                  target_rh=inp.target_rh_pct, tunnel_section_m2=section,
                  house_width_m=g.width_m, house_height_m=_mean_height_m(g))

    profile = load_profile(inp.growth_profile_id)
    last_profile_day = max(profile.daily()) if profile.points else 0
    if inp.cycle_days > last_profile_day:
        warnings.append(Note("cycle_beyond_profile", {"last_day": last_profile_day}, "info"))

    days: list[DesignDay] = []
    humid_days, short_days, leak_days, condensation_days = [], [], [], []
    coldest = _coldest_surface(env)
    worst_condensation: Optional[tuple[float, float]] = None

    for d in range(1, inp.cycle_days + 1):
        w = compute_with(CalcInput(age_days=d, outside_t=inp.winter_design_c, outside_rh=winter_rh,
                                   heater_on=inp.heater is not None,
                                   air_exchange_floor_m3h=q4_m3h, **common),
                         winter_params, winter_thermal)
        s = compute_with(CalcInput(age_days=d, outside_t=inp.summer_design_db_c,
                                   outside_rh=inp.summer_design_rh_pct, **common),
                         summer_params, summer_thermal)

        exchange = max(w.q_min_m3h, q4_m3h)
        days.append(DesignDay(
            day=d, weight_g=w.weight_used_g, target_temp_c=round(w.min_temp_c, 2),
            qmin_m3h=round(w.q_min_m3h), qmin_basis=w.qmin_basis,
            qmax_m3h=round(max(s.q_max_m3h, w.q_min_m3h)),
            heating_need_kw=round((w.heat_need_w or 0.0) / 1000.0, 1),
            air_exchange_m3h=round(exchange),
            air_exchange_basis="leakage" if q4_m3h > w.q_min_m3h else "qmin",
        ))
        if w.humidity_uncontrollable:
            humid_days.append(d)
        if w.heater_insufficient:
            short_days.append(d)
        if q4_m3h > w.q_min_m3h:
            leak_days.append(d)

        # Конденсат — на самой холодной поверхности: T_si = T_in − U·R_si·ΔT
        if coldest is not None and w.rv_percent is not None and w.min_temp_c > inp.winter_design_c:
            _, u, r_si = coldest
            t_si = w.min_temp_c - u * r_si * (w.min_temp_c - inp.winter_design_c)
            t_dew = dew_point_c(w.min_temp_c, w.rv_percent)
            if t_si < t_dew:
                condensation_days.append(d)
                if worst_condensation is None or t_dew - t_si > worst_condensation[1] - worst_condensation[0]:
                    worst_condensation = (t_si, t_dew)

    # ── Находки ──
    if humid_days:
        warnings.append(Note("humidity_uncontrollable", {"days": humid_days}, "critical"))
    if short_days:
        warnings.append(Note("heater_insufficient", {
            "days": short_days, "power_kw": inp.heater.total_power_kw}, "critical"))
    if leak_days:
        warnings.append(Note("leakage_exceeds_min_vent", {
            "days": leak_days, "leak_4pa_m3h": round(q4_m3h)}, "info"))
    if worst_condensation is not None:
        warnings.append(Note("condensation_risk", {
            "days": condensation_days, "surface": coldest[0],
            "surface_c": round(worst_condensation[0], 1), "dew_point_c": round(worst_condensation[1], 1)},
            "warning"))

    # ── Пики ──
    p_qmin = max(days, key=lambda x: x.qmin_m3h)
    p_qmax = max(days, key=lambda x: x.qmax_m3h)
    p_heat = max(days, key=lambda x: x.heating_need_kw)
    peak = dict(qmin_m3h=p_qmin.qmin_m3h, qmin_day=p_qmin.day,
                qmax_m3h=p_qmax.qmax_m3h, qmax_day=p_qmax.day,
                heating_kw=p_heat.heating_need_kw, heating_day=p_heat.day)

    # ── Оборудование ──
    cold = inp.winter_design_c < COLD_CLIMATE_WINTER_C
    norm = MIN_VENT_INSTALLED_COLD_M3H_M2 if cold else MIN_VENT_INSTALLED_HOT_M3H_M2
    assumptions.append(Note("min_vent_climate_class", {
        "class": "cold" if cold else "hot", "winter_design_c": inp.winter_design_c}))
    margin = inp.heating_margin_pct
    assumptions.append(Note("heating_safety_margin", {"pct": margin}))
    if inp.heater is None:
        assumptions.append(Note("heating_without_combustion_products"))
    if inp.altitude_m > 0:
        assumptions.append(Note("site_pressure_from_altitude", {"altitude_m": inp.altitude_m}))
        source_ids.add("ashrae_2017_ch1")

    equipment = dict(
        min_vent_fans_m3h=dict(min=round(max(p_qmin.qmin_m3h, norm[0] * floor_m2)),
                               max=round(max(p_qmin.qmin_m3h, norm[1] * floor_m2)),
                               source_id="cobb_2021_9_1"),
        tunnel_fans_m3h=dict(min=round(tunnel_range[0]), max=round(tunnel_range[1]), source_id=tunnel_source),
        tunnel_air_speed_ms=dict(min=round(speed_range[0], 2), max=round(speed_range[1], 2),
                                 source_id=tunnel_source),
        tunnel_free_section_m2=round(section, 2),
        heating_kw=round(p_heat.heating_need_kw * (1.0 + margin / 100.0), 1),
    )

    return DesignResult(
        envelope_ua_w_per_k=round(ua, 1),
        days=days, peak=peak, equipment=equipment,
        warnings=warnings, assumptions=assumptions, source_ids=sorted(source_ids),
        heaters_sufficient=(not short_days) if inp.heater is not None else None,
        profile_source=_profile_citation(profile),
    )


def _profile_citation(profile) -> Optional[str]:
    """Ссылка на источник массы из встроенного профиля (для sources ответа)."""
    weight = profile.source.get("weight") if isinstance(profile.source, dict) else None
    if isinstance(weight, dict):
        return weight.get("ref")
    return weight if isinstance(weight, str) else None
