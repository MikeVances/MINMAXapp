"""
Потребность «сейчас» — API v1, POST /ventilation-requirements (сценарий 2).

Внешняя система или агент знает возраст, текущее поголовье и погоду и спрашивает:
сколько воздуха и тепла нужно сейчас и какие риски. Мы отдаём потребность, а
сравнение со своим включённым оборудованием клиент делает сам (решение 2026-10-19).

Тот же расчёт, что у проекта и интерфейса (calc_core.compute_with), только на одну
точку: текущий день и текущая погода вместо цикла и расчётных температур. Отличия
от проекта — во входных данных:
  • birds — ТЕКУЩЕЕ поголовье (его вводят руками), падёж к нему не применяется:
    иначе он был бы учтён дважды;
  • ограждения не обязательны: без них нет теплового баланса, конденсата и
    загрузки горелок, но Qmin/Qmax и риски по влаге и туннелю — есть;
  • горелки считаются включёнными, только если снаружи холоднее уставки.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .bird_heat import animal_heat_per_bird, house_heat_per_bird
from .building_thermal import HeaterConfig, air_temperature_rise_c
from .calc_core import CalcInput, CalcParams, CalcResult, HouseThermal, compute_with, tunnel_speed_limit_ms
from .construction import HouseGeometry, Surface
from .growth_profiles import load_profile
from .psychro import pressure_at_altitude_pa, site_pressure
from .tunnel_speed_calc import EFFECTIVE_TEMP_MAX_C, _effective_temperature
from .ventilation_design import (
    CAGE_BIRD_SPEED_SHARE, Airtightness, CageRow, Note, TunnelRules, _mean_height_m, tunnel_rule_params, _profile_citation, airtightness_q4,
    build_envelope, cage_notes, check_species, coldest_surface, condensation, setpoint_notes,
    species_notes, tunnel_target, turkey_density_note,
)

# Прежний предел возраста бройлера в сценарии «сейчас» (API до индейки: 0–70 сут)
REQUIREMENT_BROILER_MAX_DAY = 70


# Источники (`source_id`) с пересказом и ограничениями — в core/sources.py:
# там же, где их читает справочник API /sources


@dataclass(frozen=True)
class RequirementInput:
    geometry: HouseGeometry
    birds: int
    growth_profile_id: str
    age_days: int
    outdoor_t_c: float
    outdoor_rh_pct: float
    housing: str = "floor_litter"
    altitude_m: float = 0.0
    cage_rows: tuple[CageRow, ...] = ()
    airtightness: Optional[Airtightness] = None
    target_rh_pct: Optional[float] = None
    # Ограждения не обязательны: измеренный UA ИЛИ конструкции
    ua_w_per_k: Optional[float] = None
    walls: Optional[Surface] = None
    roof: Optional[Surface] = None
    end_walls: Optional[Surface] = None
    heater: Optional[HeaterConfig] = None
    tunnel_rules: Optional[TunnelRules] = None
    # Индейка: тип корпуса (turkey_norms.BROODER | GROW_OUT) — для предела плотности
    stage: Optional[str] = None

    @property
    def has_envelope(self) -> bool:
        return self.ua_w_per_k is not None or self.walls is not None or self.roof is not None


@dataclass
class RequirementResult:
    qmin_m3h: float
    qmin_basis: str
    qmax_m3h: float
    target_temp_c: float
    weight_g: float
    tunnel: dict
    findings: list[Note] = field(default_factory=list)
    assumptions: list[Note] = field(default_factory=list)
    source_ids: list[str] = field(default_factory=list)
    heating_need_kw: Optional[float] = None
    heater_duty_pct: Optional[float] = None
    air_exchange_m3h: Optional[float] = None
    profile_source: Optional[str] = None
    # Как у DesignDay: RH, с которой считали, и плотность (только пол)
    target_rh_pct: Optional[float] = None
    stocking_density_kg_m2: Optional[float] = None
    stocking_density_head_m2: Optional[float] = None


def requirement(inp: RequirementInput) -> RequirementResult:
    with site_pressure(pressure_at_altitude_pa(inp.altitude_m)):
        return _requirement(inp)


def _requirement(inp: RequirementInput) -> RequirementResult:
    g = inp.geometry
    findings: list[Note] = []
    assumptions: list[Note] = []
    # Источник уставки температуры добавит setpoint_notes — он свой у каждого кросса
    source_ids = {"cigr_1984", "cigr_2002", "cobb_2021_9_7_age"}
    cages = inp.housing == "cages"
    age = max(1, inp.age_days)

    # Профиль — первым: от вида птицы зависят цель туннеля, нормы и проверки входа.
    # Предел возраста бройлера здесь прежний (70 сут), а не проектные 63
    profile = load_profile(inp.growth_profile_id)
    check_species(profile, inp.housing, inp.stage, inp.age_days, broiler_max_day=REQUIREMENT_BROILER_MAX_DAY)
    turkey = profile.species == "turkey"
    species_notes(profile, assumptions, source_ids)

    target = tunnel_target(g, inp.housing, inp.cage_rows, profile.species)
    source_ids.add(target.source_id)
    if cages:
        cage_notes(assumptions, source_ids)

    ua: Optional[float] = None
    env = None
    q4_m3h = 0.0
    if inp.has_envelope:
        ua, env = build_envelope(g, inp.ua_w_per_k, inp.walls, inp.roof, inp.end_walls,
                                 assumptions, source_ids)
        q4_m3h = airtightness_q4(g.length_m * g.width_m, inp.airtightness, assumptions)
        source_ids.add("uga_leakage")

    # Падёж 0: birds — уже текущее поголовье
    share = CAGE_BIRD_SPEED_SHARE if cages else 1.0
    rules = tunnel_rule_params(inp.tunnel_rules, assumptions, source_ids)
    params = CalcParams(total_mortality_pct=0.0, v_tunnel_ms=target.speed_ms[1],
                        bird_speed_share=share, **rules)
    common = dict(birds=inp.birds, age_days=age, outside_t=inp.outdoor_t_c,
                  outside_rh=inp.outdoor_rh_pct, growth_profile_id=inp.growth_profile_id,
                  target_rh=inp.target_rh_pct, tunnel_section_m2=target.section_m2,
                  house_width_m=g.width_m, house_height_m=_mean_height_m(g),
                  air_exchange_floor_m3h=q4_m3h,
                  # Пол под птицей — для уставки Cobb по плотности; в клетках её нет
                  stocking_floor_m2=None if cages else g.length_m * g.width_m)

    # Горелки «включены», только если снаружи холоднее уставки: иначе открытое
    # пламя добавило бы к Qmin воздух на разбавление CO₂ в жару. Уставку узнаём
    # тем же расчётом без горелок
    base = compute_with(CalcInput(**common), params, HouseThermal(ua_w_per_k=ua))
    heater_on = inp.heater is not None and inp.outdoor_t_c < base.min_temp_c
    now: CalcResult = compute_with(CalcInput(heater_on=heater_on, **common), params,
                                   HouseThermal(ua_w_per_k=ua, heater=inp.heater))

    # Клетки: Qmax — по явному теплу уровня птицы (верхний край вилки), Qmin и
    # тепло — уровня корпуса (как подстилка), см. README «Клетки»
    qmax = now.q_max_m3h
    if cages:
        hot = compute_with(CalcInput(**common),
                           CalcParams(total_mortality_pct=0.0, v_tunnel_ms=target.speed_ms[1],
                                      bird_speed_share=share, bird_heat_model=animal_heat_per_bird, **rules),
                           HouseThermal(ua_w_per_k=ua))
        qmax = max(hot.q_max_m3h, now.q_min_m3h)

    tunnel = _tunnel_now(inp, age, target, now, qmax, findings, assumptions, source_ids, cages, params,
                         profile.species)

    # ── Находки ──
    setpoint_notes([now], findings, assumptions, source_ids)
    if now.humidity_uncontrollable:
        findings.append(Note("humidity_uncontrollable", {"day": age}, "critical"))
    if now.heater_insufficient:
        findings.append(Note("heater_insufficient", {
            "need_kw": round((now.heat_need_w or 0.0) / 1000.0, 1),
            "power_kw": inp.heater.total_power_kw}, "critical"))
    if now.heater_note == "heater_full_duty_estimate":
        findings.append(Note("heater_load_unknown", {}, "info"))
    if inp.has_envelope:
        if q4_m3h > now.q_min_m3h and inp.outdoor_t_c < now.min_temp_c:
            findings.append(Note("leakage_exceeds_min_vent", {
                "days": [age], "leak_4pa_m3h": round(q4_m3h)}, "info"))
        if now.rv_percent is not None:
            surface = coldest_surface(env, ua, g)
            cond = condensation(surface, now.min_temp_c, now.rv_percent, inp.outdoor_t_c)
            if cond is not None:
                findings.append(Note("condensation_risk", {
                    "surface": surface[0], "surface_c": round(cond[0], 1),
                    "dew_point_c": round(cond[1], 1)}, "warning"))

    floor_m2 = g.length_m * g.width_m
    if turkey:
        turkey_density_note(profile, inp.stage, [(age, now.birds_alive / floor_m2)], findings, source_ids)
    last_day = max(profile.daily()) if profile.points else 0
    if inp.age_days > last_day:
        findings.append(Note("cycle_beyond_profile", {"last_day": last_day}, "info"))
    if inp.altitude_m > 0:
        assumptions.append(Note("site_pressure_from_altitude", {"altitude_m": inp.altitude_m}))
        source_ids.add("ashrae_2017_ch1")

    result = RequirementResult(
        qmin_m3h=round(now.q_min_m3h), qmin_basis=now.qmin_basis, qmax_m3h=round(qmax),
        target_temp_c=round(now.min_temp_c, 2), weight_g=now.weight_used_g, tunnel=tunnel,
        findings=findings, assumptions=assumptions, source_ids=sorted(source_ids),
        profile_source=_profile_citation(profile),
        target_rh_pct=now.rv_percent,
        stocking_density_kg_m2=(round(now.stocking_density_kg_m2, 1)
                                if now.stocking_density_kg_m2 is not None else None),
        stocking_density_head_m2=round(now.birds_alive / floor_m2, 2) if turkey else None,
    )
    if inp.has_envelope:
        result.heating_need_kw = round((now.heat_need_w or 0.0) / 1000.0, 1)
        result.air_exchange_m3h = round(max(now.q_min_m3h, q4_m3h))
        if inp.heater is not None:
            result.heater_duty_pct = round(100.0 * (now.heater_duty_cycle or 0.0), 1)
    return result


def _tunnel_now(inp: RequirementInput, age: int, target, now: CalcResult, qmax: float,
                findings: list, assumptions: list, source_ids: set, cages: bool, params: CalcParams,
                species: str) -> dict:
    """
    Цель туннеля на сегодня и ощущаемая температура у вентиляторов.

    Цель — та же, что у проекта (target), но не выше предела Cobb §9.7 по возрасту
    для СКОРОСТИ У ПТИЦЫ: у пола это скорость в сечении, у клеток — половина
    скорости в проходах, поэтому предел для прохода вдвое выше.
    """
    share = CAGE_BIRD_SPEED_SHARE if cages else 1.0
    bird_cap = tunnel_speed_limit_ms(age, target.speed_ms[1] * share)
    aisle_cap = bird_cap / share
    speed = (min(target.speed_ms[0], aisle_cap), min(target.speed_ms[1], aisle_cap))
    out: dict = {
        # Те же пороги, что решают tunnel_active в ядре, — не свои числа рядом
        "allowed": age >= params.tunnel_min_day and inp.outdoor_t_c >= params.tunnel_min_temp_c,
        "active": now.tunnel_active,
        "target_speed_ms": {"min": round(speed[0], 2), "max": round(speed[1], 2),
                            "source_id": target.source_id},
        "free_section_m2": round(target.section_m2, 2),
    }
    # Таблица ощущаемой температуры и предел 32 °C — бройлерные (Cobb §9.7): для
    # индейки их нет, и ощущаемую температуру мы не выдаём, а не выдумываем
    if species != "turkey":
        out["effective_temp_limit_c"] = EFFECTIVE_TEMP_MAX_C
    if cages:
        out["bird_speed_ms"] = {"min": round(speed[0] * share, 2), "max": round(speed[1] * share, 2),
                                "source_id": "practice_cage_tunnel_2026"}

    # Жарко, а туннель по возрасту нельзя — внешней системе стоит знать почему
    if age < params.tunnel_min_day and inp.outdoor_t_c >= now.min_temp_c:
        findings.append(Note("tunnel_not_allowed_age", {"min_day": params.tunnel_min_day}, "info"))

    if now.tunnel_active and species == "turkey":
        assumptions.append(Note("effective_temp_not_for_turkey"))
    elif now.tunnel_active:
        # Птица у вентиляторов дышит воздухом, нагретым по длине корпуса
        rise = air_temperature_rise_c(inp.birds, now.weight_used_g / 1000.0, inp.outdoor_t_c, qmax / 3600.0)
        v_bird = qmax / 3600.0 / target.section_m2 * share
        t_eff = _effective_temperature(inp.outdoor_t_c + rise, inp.outdoor_rh_pct, v_bird)
        out["effective_temp_c"] = round(t_eff, 1)
        source_ids.add("effective_temp_table")
        if t_eff >= EFFECTIVE_TEMP_MAX_C:
            findings.append(Note("effective_temp_above_limit", {"effective_c": round(t_eff, 1)},
                                 "warning", "cobb_2021_9_7_age"))
        elif t_eff > now.min_temp_c:
            findings.append(Note("effective_temp_above_profile", {
                "effective_c": round(t_eff, 1), "target_c": round(now.min_temp_c, 1)}, "info"))
    return out
