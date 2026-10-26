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
from .breed_climate import DAY_COBB_DENSITY, DAY_COBB_FALLBACK, SOURCE_BY_DAY_METHOD
from .building_thermal import HeaterConfig
from .calc_core import CalcInput, CalcParams, CalcResult, HouseThermal, compute_with
from .construction import (
    EnvelopeUA, HouseGeometry, Surface, envelope_areas, envelope_ua,
    surface_resistance_si,
)
from .errors import CalcError
from .growth_profiles import load_profile
from .leakage_calc import INLET_SPECIFIC_M3H_M2, RHO_AIR_KG_M3, _TIGHTNESS_THRESHOLDS
from .tunnel_design import HIGH_TUNNEL_PRESSURE_PA, Pads, Resistance, pad_area_m2, select_fans
from . import turkey_norms
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

# Скорость у птицы в клетках ≈ половина скорости в проходах (та же практика)
CAGE_BIRD_SPEED_SHARE = 0.5

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

# Последний день бройлерного цикла, который калькулятор считает: профили Ross/Cobb/
# Hubbard кончаются на 56–63 днях. У индейки цикл до 22 недель (154 дня)
BROILER_LAST_DAY = 63

# Источники (`source_id`) с пересказом и ограничениями — в core/sources.py:
# там же, где их читает справочник API /sources


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
class TunnelRules:
    min_day: int
    min_outdoor_c: float


def tunnel_rule_params(rules: Optional[TunnelRules], assumptions: list, source_ids: set) -> dict:
    """
    Пороги туннеля для CalcParams. Не заданы в запросе — практика по умолчанию,
    и ответ говорит об этом допущением со ссылкой на источник.
    """
    if rules is not None:
        return dict(tunnel_min_day=rules.min_day, tunnel_min_temp_c=rules.min_outdoor_c)
    defaults = CalcParams()
    assumptions.append(Note("tunnel_rules_default", {
        "min_day": defaults.tunnel_min_day, "min_temp_c": defaults.tunnel_min_temp_c},
        source_id="practice_tunnel_rules_2026"))
    source_ids.add("practice_tunnel_rules_2026")
    return {}


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
    # Правила туннеля (возраст, наружная T): None — практика по умолчанию (CalcParams)
    tunnel_rules: Optional["TunnelRules"] = None
    # Туннель (этап 3b): панели на впуске, каталог вентилятора (давление Па, расход
    # м³/ч) и замеренное давление на похожем корпусе
    pads: Optional[Pads] = None
    fan_curve: tuple[tuple[float, float], ...] = ()
    tunnel_static_pressure_pa: Optional[float] = None
    # Индейка (2026-10-26): брудер и доращивание — разные корпуса. first_day — день
    # посадки в этот корпус (на доращивание — день пересадки), cycle_days — последний
    # день в нём; stage — тип корпуса (turkey_norms.BROODER | GROW_OUT), у индейки
    # обязателен, у бройлера запрещён
    first_day: int = 1
    stage: Optional[str] = None


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
    # С чем считали уставку и влагу: RH из запроса или из профиля; None — ни там, ни там
    target_rh_pct: Optional[float] = None
    # Только пол: у клеток плотность на м² пола смысла не имеет
    stocking_density_kg_m2: Optional[float] = None
    # Индейка: живое поголовье на м² пола — в этих единицах руководства дают предел
    stocking_density_head_m2: Optional[float] = None


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


def coldest_surface(env: Optional[EnvelopeUA], ua_w_per_k: float,
                    g: HouseGeometry) -> tuple[str, float, float]:
    """
    (элемент, U, R_si) с самой холодной внутренней поверхностью: наибольшее U·R_si.
    Измеренный UA по элементам не делится — берём средний U оболочки и R_si стены;
    UA теста включает и щели, так что U завышен — риск виден раньше (безопасно).
    """
    if env is None:
        mean_u = ua_w_per_k / envelope_areas(g).total_m2
        return ("envelope_mean", mean_u, surface_resistance_si("wall"))
    parts = [
        ("side_walls", env.side_walls_u, surface_resistance_si("wall")),
        ("end_walls", env.end_walls_u, surface_resistance_si("wall")),
        ("roof", env.roof_u, surface_resistance_si("roof", env.areas.roof_pitch_deg)),
    ]
    return max(parts, key=lambda p: p[1] * p[2])


def condensation(surface: tuple[str, float, float], t_in: float, rh_in: float,
                 t_out: float) -> Optional[tuple[float, float]]:
    """(T поверхности, T росы), если поверхность холоднее точки росы; иначе None."""
    if t_in <= t_out:
        return None
    _, u, r_si = surface
    t_si = t_in - u * r_si * (t_in - t_out)
    t_dew = dew_point_c(t_in, rh_in)
    return (t_si, t_dew) if t_si < t_dew else None


@dataclass(frozen=True)
class TunnelTarget:
    section_m2: float                    # у клеток — свободное сечение
    speed_ms: tuple[float, float]        # у клеток — в проходах
    flow_m3h: tuple[float, float]
    source_id: str
    # Какой критерий дал верхнюю (расчётную) границу расхода: floor_capacity —
    # м³/ч на м² пола, air_exchange — смена объёма за 40 с, aisle_speed — скорость
    # в проходах клеток. Вентиляторы подбираются по верхней границе
    basis: str = "floor_capacity"


def tunnel_target(g: HouseGeometry, housing: str, cage_rows: tuple[CageRow, ...],
                  species: str = "broiler") -> TunnelTarget:
    """
    Цель туннеля корпуса: пол — Cobb §9.7 (больший из двух критериев), клетки — практика,
    индейка — скорость 2 м/с в сечении (Hybrid CMG с. 51, решение владельца).
    """
    if species == "turkey":
        section = g.width_m * _mean_height_m(g)
        v = turkey_norms.TUNNEL_SPEED_MS
        flow = v * section * 3600.0
        return TunnelTarget(section, (v, v), (flow, flow), turkey_norms.TUNNEL_SOURCE, "air_speed")
    if housing == "cages":
        section = cage_free_section_m2(g, cage_rows)
        speed = CAGE_AISLE_SPEED_MS
        return TunnelTarget(section, speed, tuple(v * section * 3600.0 for v in speed),
                            "practice_cage_tunnel_2026", "aisle_speed")
    section = g.width_m * _mean_height_m(g)
    volume_m3 = section * g.length_m
    floor_m2 = g.length_m * g.width_m
    flow = tuple(max(n * floor_m2, volume_m3 * 3600.0 / t)
                 for n, t in zip(TUNNEL_CAPACITY_M3H_M2, TUNNEL_AIR_EXCHANGE_S))
    # Высокий корпус (средняя высота больше ~2.2 м) упирается в смену объёма, а не в
    # ёмкость на м² пола — агенту стоит знать, какое правило Cobb сработало
    by_exchange = volume_m3 * 3600.0 / TUNNEL_AIR_EXCHANGE_S[1] > TUNNEL_CAPACITY_M3H_M2[1] * floor_m2
    return TunnelTarget(section, tuple(q / 3600.0 / section for q in flow), flow, "cobb_2021_9_7",
                        "air_exchange" if by_exchange else "floor_capacity")


def check_species(profile, housing: str, stage: Optional[str], last_day: int,
                  broiler_max_day: int = BROILER_LAST_DAY) -> None:
    """
    Вход, который у этого вида птицы не имеет смысла, — ошибка, а не тихое игнорирование:
    клеток у индейки нет, тип корпуса у бройлера не определён, а без типа у индейки
    не выбрать ни норму вентиляторов, ни предел плотности.
    """
    if profile.species == "turkey":
        if housing == "cages":
            raise CalcError("housing_not_for_species", species="turkey", housing=housing)
        if stage is None:
            raise CalcError("turkey_stage_required")
    else:
        if stage is not None:
            raise CalcError("stage_turkey_only", stage=stage)
        if last_day > broiler_max_day:
            raise CalcError("broiler_day_out_of_range", day=last_day, max_day=broiler_max_day)


def species_notes(profile, assumptions: list, source_ids: set) -> None:
    """Допущения и источники, которые вносит вид птицы (у бройлера — ничего нового)."""
    if profile.species != "turkey":
        return
    source_ids.add("cigr_2002_turkey")
    assumptions.append(Note("turkey_sensible_from_broiler", source_id="cigr_2002_turkey"))
    day0 = (profile.source or {}).get("weight_day0")
    if isinstance(day0, dict) and profile.builtin:
        source_ids.add("xin_1998_turkey")
        assumptions.append(Note("turkey_day0_weight", {"weight_g": day0.get("value_g")},
                                source_id="xin_1998_turkey"))
    if profile.min_vent_norm:
        sid = turkey_norms.GUIDE_NORM_SOURCE[profile.min_vent_norm]
        source_ids.add(sid)
        assumptions.append(Note("qmin_includes_guide_norm", {"norm": profile.min_vent_norm}, source_id=sid))
    # Пределы скорости по возрасту в ядре — Cobb (цыплята): у индейки своих нет
    source_ids.add("cobb_2021_9_7_age")
    assumptions.append(Note("turkey_tunnel_age_limits_from_broiler", source_id="cobb_2021_9_7_age"))


def turkey_density_note(profile, stage: str, days: list[tuple[int, float]], findings: list,
                        source_ids: set) -> None:
    """
    Плотность индейки в головах на м² против предела Aviagen. days — (день, гол/м²).
    Предела нет (смешанное стадо на доращивании) — так и говорим, а не молчим.
    """
    limit = turkey_norms.density_limit(stage, profile.sex)
    if limit is None:
        return
    source_ids.add(limit.source_id)
    over = [(d, h) for d, h in days if h > limit.head_per_m2]
    if over:
        findings.append(Note("turkey_density_high", {
            "days": [d for d, _ in over], "head_per_m2": round(max(h for _, h in over), 2),
            "limit_head_per_m2": limit.head_per_m2}, "warning", source_id=limit.source_id))


def build_envelope(g: HouseGeometry, ua_w_per_k: Optional[float], walls: Optional[Surface],
                   roof: Optional[Surface], end_walls: Optional[Surface],
                   assumptions: list, source_ids: set) -> tuple[float, Optional[EnvelopeUA]]:
    """UA корпуса: измеренный как есть или по конструкции (с допущениями и источниками)."""
    if ua_w_per_k is not None:
        return ua_w_per_k, None
    if walls is None or roof is None:
        raise CalcError("validation_failed", field="envelope")
    env = envelope_ua(g, walls, roof, end_walls)
    source_ids |= {"br443_2019_s3", "br443_2019_s4_3"}
    assumptions += [Note("materials_iso_10456"), Note("floor_not_included")]
    return env.ua_w_per_k, env


def cage_notes(assumptions: list, source_ids: set) -> None:
    source_ids |= {"aarnink_2018", "practice_cage_tunnel_2026"}
    assumptions += [Note("cages_heat_split_bounded"), Note("cages_bird_speed_from_aisle"),
                    Note("cage_through_flow_not_included")]


def airtightness_q4(floor_m2: float, airtight: Optional[Airtightness], assumptions: list) -> float:
    q4, assumed_class = leak_at_4pa_m3h(floor_m2, airtight)
    if assumed_class:
        assumptions.append(Note("airtightness_class_assumed", {
            "class": assumed_class, "relative_leakage": AIRTIGHTNESS_CLASS_RELATIVE[assumed_class]}))
    return q4


# ─── Расчёт ───────────────────────────────────────────────────────────────────

def design(inp: DesignInput) -> DesignResult:
    with site_pressure(pressure_at_altitude_pa(inp.altitude_m)):
        return _design(inp)


# Плотнее 42 кг/м² Cobb 2021 §5.2 держать не советует: тепло из-под птицы
# вентиляцией уже не снять
STOCKING_DENSITY_LIMIT_KG_M2 = 42.0


def setpoint_notes(results: list[CalcResult], findings: list, assumptions: list,
                   source_ids: set) -> None:
    """
    Источник уставки температуры и допущения её методики (breed_climate).

    Методика своя у каждого кросса и даже у дня (Cobb: возраст, затем плотность),
    поэтому источник берётся из того, как реально посчитан каждый день, а не
    подписывается одним «Ross» на все кроссы.
    """
    methods = {r.setpoint_method for r in results}
    source_ids |= {SOURCE_BY_DAY_METHOD[m] for m in methods if m in SOURCE_BY_DAY_METHOD}

    # Плотность теперь есть у любого кросса с полом — допущения и предел Cobb
    # относятся только к дням, где уставку по ней действительно считали
    dense = [r for r in results if r.setpoint_method == DAY_COBB_DENSITY]
    if dense:
        assumptions.append(Note("cobb_density_transition", {
            "density_from_kg_m2": round(dense[0].stocking_density_kg_m2, 1),
            "density_to_kg_m2": round(dense[-1].stocking_density_kg_m2, 1)}, source_id="cobb_2021_5_2"))
        over = [r for r in dense if r.stocking_density_kg_m2 > STOCKING_DENSITY_LIMIT_KG_M2]
        if over:
            findings.append(Note("stocking_density_high", {
                "days": [r.profile_day_resolved for r in over],
                "density_kg_m2": round(max(r.stocking_density_kg_m2 for r in over), 1),
                "limit_kg_m2": STOCKING_DENSITY_LIMIT_KG_M2}, "warning", source_id="cobb_2021_5_2"))
    if DAY_COBB_FALLBACK in methods:
        assumptions.append(Note("cobb_density_unavailable", source_id="ross_2025_t2_5"))


def _design(inp: DesignInput) -> DesignResult:
    g = inp.geometry
    warnings: list[Note] = []
    assumptions: list[Note] = []
    # Источник уставки температуры добавит setpoint_notes — он свой у каждого кросса
    source_ids = {"cigr_1984", "cigr_2002", "uga_leakage"}
    cages = inp.housing == "cages"

    # Профиль — первым: от вида птицы зависят цель туннеля, нормы и проверки входа
    profile = load_profile(inp.growth_profile_id)
    check_species(profile, inp.housing, inp.stage, inp.cycle_days)
    if inp.first_day >= inp.cycle_days:
        raise CalcError("first_day_after_last", first_day=inp.first_day, last_day=inp.cycle_days)
    turkey = profile.species == "turkey"
    species_notes(profile, assumptions, source_ids)

    # ── Ограждения и утечки ──
    ua, env = build_envelope(g, inp.ua_w_per_k, inp.walls, inp.roof, inp.end_walls,
                             assumptions, source_ids)
    floor_m2 = g.length_m * g.width_m
    q4_m3h = airtightness_q4(floor_m2, inp.airtightness, assumptions)

    # ── Туннель: сечение и цель скорости ──
    target = tunnel_target(g, inp.housing, inp.cage_rows, profile.species)
    section, speed_range, tunnel_range = target.section_m2, target.speed_ms, target.flow_m3h
    tunnel_source = target.source_id
    if cages:
        cage_notes(assumptions, source_ids)
    source_ids.add(tunnel_source)

    # Параметры модели: падёж и цикл — из запроса; туннель в днях — на верхней
    # границе цели (проектная мощность), остальное — значения интерфейса по умолчанию
    share = CAGE_BIRD_SPEED_SHARE if cages else 1.0
    rules = tunnel_rule_params(inp.tunnel_rules, assumptions, source_ids)
    winter_params = CalcParams(total_mortality_pct=inp.mortality_pct, cycle_days=inp.cycle_days,
                               v_tunnel_ms=speed_range[1], bird_speed_share=share,
                               placement_day=inp.first_day, **rules)
    # Клетки летом — явное тепло на уровне птицы (верхний край вилки): больше воздуха
    summer_params = CalcParams(total_mortality_pct=inp.mortality_pct, cycle_days=inp.cycle_days,
                               v_tunnel_ms=speed_range[1], bird_speed_share=share,
                               placement_day=inp.first_day, **rules,
                               bird_heat_model=animal_heat_per_bird if cages else house_heat_per_bird)
    winter_thermal = HouseThermal(ua_w_per_k=ua, heater=inp.heater)
    summer_thermal = HouseThermal(ua_w_per_k=ua)

    # Зимой наружный воздух — насыщенный: при −10 °C это 1.6 г/кг против 1.3 при
    # 80 %, а большее влагосодержание даёт больший влажностный Qmin
    winter_rh = 100.0
    assumptions.append(Note("winter_rh_saturated"))

    # Пол под птицей — для уставки Cobb по плотности посадки; в клетках её нет
    common = dict(birds=inp.birds, growth_profile_id=inp.growth_profile_id,
                  target_rh=inp.target_rh_pct, tunnel_section_m2=section,
                  house_width_m=g.width_m, house_height_m=_mean_height_m(g),
                  stocking_floor_m2=None if cages else floor_m2)

    last_profile_day = max(profile.daily()) if profile.points else 0
    if inp.cycle_days > last_profile_day:
        warnings.append(Note("cycle_beyond_profile", {"last_day": last_profile_day}, "info"))

    days: list[DesignDay] = []
    humid_days, short_days, leak_days, condensation_days = [], [], [], []
    coldest = coldest_surface(env, ua, g)
    worst_condensation: Optional[tuple[float, float]] = None
    winter_days: list[CalcResult] = []

    head_density: list[tuple[int, float]] = []

    for d in range(inp.first_day, inp.cycle_days + 1):
        w = compute_with(CalcInput(age_days=d, outside_t=inp.winter_design_c, outside_rh=winter_rh,
                                   heater_on=inp.heater is not None,
                                   air_exchange_floor_m3h=q4_m3h, **common),
                         winter_params, winter_thermal)
        s = compute_with(CalcInput(age_days=d, outside_t=inp.summer_design_db_c,
                                   outside_rh=inp.summer_design_rh_pct, **common),
                         summer_params, summer_thermal)

        winter_days.append(w)
        exchange = max(w.q_min_m3h, q4_m3h)
        days.append(DesignDay(
            day=d, weight_g=w.weight_used_g, target_temp_c=round(w.min_temp_c, 2),
            qmin_m3h=round(w.q_min_m3h), qmin_basis=w.qmin_basis,
            qmax_m3h=round(max(s.q_max_m3h, w.q_min_m3h)),
            heating_need_kw=round((w.heat_need_w or 0.0) / 1000.0, 1),
            air_exchange_m3h=round(exchange),
            air_exchange_basis="leakage" if q4_m3h > w.q_min_m3h else "qmin",
            target_rh_pct=w.rv_percent,
            stocking_density_kg_m2=(round(w.stocking_density_kg_m2, 1)
                                    if w.stocking_density_kg_m2 is not None else None),
            stocking_density_head_m2=(round(w.birds_alive / floor_m2, 2) if turkey else None),
        ))
        if turkey:
            head_density.append((d, w.birds_alive / floor_m2))
        if w.humidity_uncontrollable:
            humid_days.append(d)
        if w.heater_insufficient:
            short_days.append(d)
        if q4_m3h > w.q_min_m3h:
            leak_days.append(d)

        # Конденсат — на самой холодной поверхности: T_si = T_in − U·R_si·ΔT
        cond = (condensation(coldest, w.min_temp_c, w.rv_percent, inp.winter_design_c)
                if w.rv_percent is not None else None)
        if cond is not None:
            condensation_days.append(d)
            if worst_condensation is None or cond[1] - cond[0] > worst_condensation[1] - worst_condensation[0]:
                worst_condensation = cond

    # ── Находки ──
    setpoint_notes(winter_days, warnings, assumptions, source_ids)
    if turkey:
        turkey_density_note(profile, inp.stage, head_density, warnings, source_ids)
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
    if turkey:
        # Индейка: норма Hybrid по типу корпуса, а не класс климата Cobb
        per_m2 = turkey_norms.MIN_VENT_INSTALLED_M3H_M2[inp.stage]
        norm = (per_m2, per_m2)
        min_vent_source = turkey_norms.MIN_VENT_INSTALLED_SOURCE
        assumptions.append(Note("min_vent_turkey_stage", {"stage": inp.stage, "m3h_per_m2": per_m2},
                                source_id=min_vent_source))
    else:
        cold = inp.winter_design_c < COLD_CLIMATE_WINTER_C
        norm = MIN_VENT_INSTALLED_COLD_M3H_M2 if cold else MIN_VENT_INSTALLED_HOT_M3H_M2
        min_vent_source = "cobb_2021_9_1"
        assumptions.append(Note("min_vent_climate_class", {
            "class": "cold" if cold else "hot", "winter_design_c": inp.winter_design_c}))
    source_ids.add(min_vent_source)
    margin = inp.heating_margin_pct
    assumptions.append(Note("heating_safety_margin", {"pct": margin}))
    if inp.heater is None:
        assumptions.append(Note("heating_without_combustion_products"))
    if inp.altitude_m > 0:
        assumptions.append(Note("site_pressure_from_altitude", {"altitude_m": inp.altitude_m}))
        source_ids.add("ashrae_2017_ch1")

    min_vent_max = max(p_qmin.qmin_m3h, norm[1] * floor_m2)
    equipment = dict(
        min_vent_fans_m3h=dict(min=round(max(p_qmin.qmin_m3h, norm[0] * floor_m2)),
                               max=round(min_vent_max), source_id=min_vent_source),
        # Боковые клапаны минвентиляции под верх мощности её вентиляторов (UGA)
        inlet_area_m2=round(min_vent_max / INLET_SPECIFIC_M3H_M2, 2),
        tunnel_fans_m3h=dict(min=round(tunnel_range[0]), max=round(tunnel_range[1]), source_id=tunnel_source),
        tunnel_fans_basis=target.basis,
        tunnel_air_speed_ms=dict(min=round(speed_range[0], 2), max=round(speed_range[1], 2),
                                 source_id=tunnel_source),
        tunnel_free_section_m2=round(section, 2),
        heating_kw=round(p_heat.heating_need_kw * (1.0 + margin / 100.0), 1),
    )
    source_ids |= {"uga_inlet_750cfm", "amca_210"}
    equipment.update(_tunnel_equipment(inp, section, tunnel_range[1], warnings, assumptions, source_ids))

    return DesignResult(
        envelope_ua_w_per_k=round(ua, 1),
        days=days, peak=peak, equipment=equipment,
        warnings=warnings, assumptions=assumptions, source_ids=sorted(source_ids),
        heaters_sufficient=(not short_days) if inp.heater is not None else None,
        profile_source=_profile_citation(profile),
    )


def _tunnel_equipment(inp: DesignInput, section: float, q_design: float, warnings: list[Note],
                      assumptions: list[Note], source_ids: set) -> dict:
    """
    Давление туннеля при проектном расходе (верх цели) и, если дан каталог, число
    вентиляторов в рабочей точке. Панели — площадь по проектной скорости UGA.
    """
    out: dict = {}
    pad_area = None
    if inp.pads is not None:
        pad_area = pad_area_m2(q_design, inp.pads)
        out["pad_area_m2"] = round(pad_area, 1)
        source_ids |= {"uga_pad_velocity", "sanhe_pads"}
    measured = (q_design, inp.tunnel_static_pressure_pa) if inp.tunnel_static_pressure_pa else None
    resistance = Resistance(section, inp.pads, pad_area, measured)
    parts = resistance.parts(q_design)
    out["tunnel_static_pressure_pa"] = {k: (round(v, 1) if isinstance(v, float) else v)
                                        for k, v in vars(parts).items()}
    if parts.basis == "estimated":
        assumptions.append(Note("tunnel_length_loss_not_included"))
    if parts.total > HIGH_TUNNEL_PRESSURE_PA:
        warnings.append(Note("tunnel_pressure_high", {"pressure_pa": round(parts.total, 1)}, "warning"))

    if inp.fan_curve:
        sel = select_fans(inp.fan_curve, resistance, q_design)
        out["tunnel_fans"] = dict(count=sel.count, flow_per_fan_m3h=round(sel.flow_per_fan_m3h),
                                  operating_pressure_pa=round(sel.operating_pressure_pa, 1))
        if sel.extrapolated:
            warnings.append(Note("fan_curve_extrapolated", {
                "pressure_pa": round(sel.operating_pressure_pa, 1),
                "last_pa": inp.fan_curve[-1][0]}, "warning"))
    return out


def _profile_citation(profile) -> Optional[str]:
    """Ссылка на источник массы из встроенного профиля (для sources ответа)."""
    weight = profile.source.get("weight") if isinstance(profile.source, dict) else None
    if isinstance(weight, dict):
        return weight.get("ref")
    return weight if isinstance(weight, str) else None
