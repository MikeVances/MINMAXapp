from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Callable, Optional

from .errors import CalcError
from .growth_profiles import load_profile
from .breed_climate import setpoint_for_day
from .survival import survival_fraction
from .psychro import humidity_ratio
from .bird_heat import HouseHeat, house_heat_per_bird, house_sensible_fraction
from .ventilation_calc import calc_q_min_per_bird
from .turkey_norms import guide_min_vent_m3h
from .app_config import load_app_config
from .building_thermal import (
    BuildingDimensions,
    HeaterConfig,
    surface_condensation,
    AIR_CP_J_PER_KG_K,
    air_density_kg_m3,
    ventilation_heat_w,
    load_thermal_config,
    heater_air_demand,
    heater_co2_dilution_m3h,
    solve_heater_duty,
    usable_ua,
)


# ─── Психрометрические вспомогательные функции ───────────────────────────────

def humidity_ratio_g_per_kg(T_c: float, rh_pct: float) -> float:
    """Влагосодержание воздуха, г/кг с.в. при (T°C, RH%) — psychro.humidity_ratio в г/кг."""
    return humidity_ratio(T_c, rh_pct) * 1000.0


def house_sensible_fraction_cigr2002(t_inside_c: float) -> float:
    """Совместимость: доля явного тепла корпуса — см. bird_heat.house_sensible_fraction."""
    return house_sensible_fraction(t_inside_c)


# Переходная вентиляция (боковые клапаны) — 40–50 % мощности туннеля (Ross 2025, с. 79):
# пока тепловой баланс требует меньше половины туннельного расхода, туннель не нужен
TRANSITIONAL_SHARE_OF_TUNNEL = 0.5

# Предельная скорость воздуха у птицы по возрасту, м/с (Cobb Broiler Guide 2021, §9.7:
# 0–5 сут — до 0.3; 5–14 — 0.3–0.5; 14–21 — 0.5–1.8; старше — без ограничения)
_TUNNEL_SPEED_BY_AGE = [(5, 0.3), (14, 0.5), (21, 1.8)]


def tunnel_speed_limit_ms(age_days: int, v_design_ms: float) -> float:
    """Наибольшая допустимая скорость в туннеле для возраста; старше 21 дня — проектная."""
    for max_age, v in _TUNNEL_SPEED_BY_AGE:
        if age_days < max_age:
            return v
    return v_design_ms


def regime_ceiling_m3h(age: int, tunnel_min_day: int, q_min_co2: float,
                       tunnel_requirement: Optional[float]) -> tuple[float, bool]:
    """
    Наибольший расход, который корпус разумно даст в этом возрасте, м³/ч.

      моложе tunnel_min_day — 4 × Qmin по CO₂ (Aviagen: переходная вентиляция
                              3–5× минимума; больше — сквозняк по молодой птице);
      старше                — туннельный расход корпуса v × S × 3600.

    Второе значение — True, если туннельный расход нужен, но размеров корпуса нет
    и потолок оценён как 4 × Qmin: тогда UI просит ввести размеры.
    """
    if age < tunnel_min_day:
        return 4.0 * q_min_co2, False
    if tunnel_requirement:
        return tunnel_requirement, False
    return 4.0 * q_min_co2, True


def qmin_basis_of(co2_m3h: float, moisture_m3h: Optional[float], guide_m3h: Optional[float]) -> str:
    """
    Что определило Qmin: наибольшая из ветвей. При равенстве — CO₂, затем норма:
    влагу называем причиной, только когда она действительно требует больше.
    """
    best, basis = co2_m3h, "co2"
    if guide_m3h is not None and guide_m3h > best:
        best, basis = guide_m3h, "guide"
    if moisture_m3h is not None and moisture_m3h > best:
        basis = "moisture"
    return basis


def moisture_qmin_m3h(vapour_g_per_h: float, rho_in: float, delta_w_g_per_kg: float,
                      ceiling_m3h: float) -> tuple[float, bool]:
    """
    Расход, выносящий пар: Q = G / (ρ · ΔW), ограниченный потолком режима.

    Почему потолок, а не «вернуться на CO₂»: влагосодержание в корпусе
    W_вн = W_нар + G / (ρ · Q) убывает с ростом Q при ЛЮБОМ ΔW. Когда наружный
    воздух почти так же влажен, как целевой (ΔW → 0), нужный расход уходит в
    бесконечность, но лучшее достижимое — максимум режима, а не минимум по CO₂.
    Раньше здесь был разрыв: 223 тыс. м³/ч у суточных цыплят при 30 °C / 60 %
    и 4 тыс. при 62 % (аудит 2026-10-18).

    Второе значение — True, если цель по влажности вентиляцией не достигается
    (упёрлись в потолок): нужен подогрев приточного воздуха или осушение.
    """
    if delta_w_g_per_kg <= 0.0:
        return ceiling_m3h, True
    q = vapour_g_per_h / (rho_in * delta_w_g_per_kg)
    if q > ceiling_m3h:
        return ceiling_m3h, True
    return q, False


# ─── Модели данных ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class FlockGroup:
    """
    Вторая группа птицы в том же корпусе — самки индейки в смешанном стаде.
    last_day — последний день группы в корпусе (выборка); после него её нет.
    Падёж — тот же процент, что у основной группы.
    """
    growth_profile_id: str
    birds: int
    last_day: Optional[int] = None


def mix_heat(groups: list[tuple[float, HouseHeat]]) -> HouseHeat:
    """
    Тепло «средней птицы» корпуса из групп (живое поголовье, тепло одной птицы):
    дальше расчёт умножает его на всё поголовье — и получает сумму по группам.
    """
    n = sum(count for count, _ in groups) or 1.0
    return HouseHeat(total_w=sum(c * h.total_w for c, h in groups) / n,
                     sensible_w=sum(c * h.sensible_w for c, h in groups) / n,
                     latent_w=sum(c * h.latent_w for c, h in groups) / n)


@dataclass
class CalcInput:
    birds: int
    age_days: int
    outside_t: float    # °C
    heater_on: bool = False
    outside_rh: float = 60.0  # % относительная влажность снаружи
    # Сечение корпуса для туннельного расхода: ширина и СРЕДНЯЯ высота (стена+конёк)/2.
    # Не заданы → туннельный Qmax не считается (house_geometry_missing)
    house_width_m: Optional[float] = None
    house_height_m: Optional[float] = None
    # Профиль роста из библиотеки (кросс); None → default_growth_profile из настроек
    growth_profile_id: Optional[str] = None
    # Целевая RH в корпусе, % (40–70). None → RH из профиля роста.
    # Сдвигает уставку температуры (ощущаемая температура) и служит потолком влагобаланса
    target_rh: Optional[float] = None
    # Корпус расчёта: калибровка UA применяется только к тому корпусу, где измерена
    house_id: Optional[str] = None
    # Сечение туннеля, м², если оно не ширина × высота: клеточный зал — свободное
    # сечение между батареями (API v1). None → house_width_m × house_height_m
    tunnel_section_m2: Optional[float] = None
    # Утечка при ~4 Па, м³/ч: обогрев греет не меньше этого воздуха (API v1)
    air_exchange_floor_m3h: float = 0.0
    # Площадь пола под птицей, м² — для уставки Cobb по плотности посадки (API v1,
    # подстилка). None → плотность не определена, у Cobb после 14-го дня — профиль
    stocking_floor_m2: Optional[float] = None
    # Смешанное стадо: вторая группа (самки индейки) до дня выборки
    companion: Optional[FlockGroup] = None


@dataclass
class CalcResult:
    q_min_m3h: float
    q_max_m3h: float
    weight_used_g: float
    profile_day_resolved: int
    rates_per_bird_min: float
    rates_per_bird_max: float
    rates_per_kg_min: float
    rates_per_kg_max: float
    min_temp_c: Optional[float] = None
    rv_percent: Optional[float] = None
    heater_air_m3h: Optional[float] = None
    heater_duty_cycle: Optional[float] = None
    tunnel_active: bool = False
    # "co2" | "moisture" | "guide" — какое ограничение определило Qmin
    # (guide — норма минвентиляции производителя кросса, у индейки)
    qmin_basis: str = "co2"
    # Требуемый туннельный расход корпуса v × S × 3600, м³/ч (None — нет размеров)
    tunnel_requirement_m3h: Optional[float] = None
    # Qmax не посчитан: нужен туннельный расход, а размеров корпуса нет (Qmax = Qmin)
    house_geometry_missing: bool = False
    # Наружный воздух не суше целевого внутреннего (ΔW ≤ 0.1 г/кг): вентиляцией RH
    # не удержать при любом расходе, Qmin показан по CO₂
    humidity_uncontrollable: bool = False
    # Горелок не хватает даже на 100 % (с учётом подогрева их же воздуха разбавления)
    heater_insufficient: bool = False
    # Как учтены горелки без найденной загрузки: heater_data_missing | heater_full_duty_estimate
    heater_note: Optional[str] = None
    # Конденсат на ограждениях (нужны UA своего корпуса и размеры): T поверхности, T росы
    surface_temp_c: Optional[float] = None
    dew_point_inside_c: Optional[float] = None
    condensation_risk: bool = False
    # Почему калибровка UA не применена: {code, params} или None
    calibration_ignored: Optional[dict] = None
    # Профиль роста, по которому шёл расчёт (видно, какие данные кросса использованы)
    growth_profile_id: Optional[str] = None
    # Потребность в тепле, Вт (нужен UA): стены + обмен воздуха − явное тепло птицы
    heat_need_w: Optional[float] = None
    # Живая птица на этот день с учётом падежа
    birds_alive: Optional[float] = None
    # Методика уставки этого дня (breed_climate.DAY_*)
    setpoint_method: Optional[str] = None
    # Плотность посадки, кг живой массы на м² пола — у любого кросса, если площадь
    # пола известна (у клеток — None). Уставку по ней считает только Cobb
    stocking_density_kg_m2: Optional[float] = None
    # Вид птицы профиля (bird_heat.BROILER | TURKEY) — от него закон тепла
    species: str = "broiler"
    # Норма минвентиляции производителя на этот день, м³/ч (None — у кросса её нет)
    qmin_guide_m3h: Optional[float] = None
    # Смешанное стадо: живые птицы и масса второй группы в этот день (None — её нет:
    # стадо однополое или самок уже выбрали). weight_used_g — средняя по корпусу
    companion_alive: Optional[float] = None
    companion_weight_g: Optional[float] = None


@dataclass(frozen=True)
class CalcParams:
    """
    Параметры расчёта, которые интерфейс берёт из настроек хозяйства (app_config),
    а API v1 — из запроса. Разделены, чтобы оба пути шли через ОДНУ модель
    (compute_with), а не через две копии расчёта.
    """
    total_mortality_pct: float = 4.0
    cycle_days: int = 42
    default_growth_profile: str = "ross308"
    v_tunnel_ms: float = 2.5
    safety_factor_qmin: float = 1.5
    # Практика птицеводов (владелец, 2026-10-19): туннель с 21-го дня, снаружи ≥ 24 °C
    tunnel_min_day: int = 21
    tunnel_min_temp_c: float = 24.0
    # Тепло птицы: house_heat_per_bird (подстилка, CIGR 2002) или
    # animal_heat_per_bird (клетки, летний край вилки — bird_heat)
    bird_heat_model: Callable[[float, float], HouseHeat] = house_heat_per_bird
    # Скорость у птицы / скорость в сечении туннеля. Пол — 1; клетки — ~0.5 (в
    # проходах 4–5 м/с, у птицы 2–2.5, практика владельца). Предел Cobb по возрасту
    # — для скорости У ПТИЦЫ, поэтому в проходе клеточного зала он вдвое выше
    bird_speed_share: float = 1.0
    # День посадки в ЭТОТ корпус: на доращивании индейки птица приходит из брудера,
    # и падёж корпуса распределяется от дня посадки до cycle_days, а не от дня 1
    placement_day: int = 1

    @classmethod
    def from_app_config(cls, cfg) -> "CalcParams":
        return cls(
            total_mortality_pct=cfg.total_mortality_pct,
            cycle_days=cfg.cycle_days,
            default_growth_profile=getattr(cfg, "default_growth_profile", "ross308"),
            v_tunnel_ms=float(getattr(cfg, "v_tunnel_ms", 2.5)),
            safety_factor_qmin=float(getattr(cfg, "safety_factor_qmin", 1.5)),
            tunnel_min_day=int(getattr(cfg, "tunnel_min_day", cls.tunnel_min_day)),
            tunnel_min_temp_c=float(getattr(cfg, "tunnel_min_temp_c", cls.tunnel_min_temp_c)),
        )


@dataclass(frozen=True)
class HouseThermal:
    """Теплотехника корпуса: UA, горелки, размеры для проверки конденсата."""
    ua_w_per_k: Optional[float] = None
    heater: Optional[HeaterConfig] = None
    building: Optional[BuildingDimensions] = None
    # Почему сохранённая калибровка не применена (только путь интерфейса)
    calibration_ignored: Optional[dict] = None


def _stored_thermal(house_id: Optional[str]) -> HouseThermal:
    """Теплотехника корпуса из сохранённых настроек — путь интерфейса."""
    try:
        # Теплотехника СВОЕГО корпуса: калибровка и горелки хранятся по корпусам.
        # UA — только проверенной калибровки СВОЕГО корпуса (usable_ua): калибровка
        # чужого корпуса, тест короче 10 мин или неправдоподобный U оболочки в расчёт
        # не идут, а причина уходит в ответ, чтобы UI предупредил
        cfg = load_thermal_config(house_id=house_id)
        ua, ignored = usable_ua(cfg, house_id)
    except Exception:
        return HouseThermal()
    return HouseThermal(ua_w_per_k=ua, heater=cfg.heater, building=cfg.building,
                        calibration_ignored=ignored)


def compute(ci: CalcInput, **overrides) -> CalcResult:
    """
    Расчёт для интерфейса: параметры и теплотехника — из сохранённых настроек.
    overrides — поля CalcParams поверх настроек хозяйства: этап индейки задаёт свой
    цикл, день посадки и скорость тоннеля, которых в настройках бройлерной фермы нет.
    """
    thermal = _stored_thermal(ci.house_id)
    # Пол для плотности посадки Cobb — из сохранённых размеров корпуса: клеток в
    # интерфейсе нет, а без площади у Cobb после 14-го дня остались бы значения Ross
    if ci.stocking_floor_m2 is None and thermal.building is not None:
        ci = replace(ci, stocking_floor_m2=thermal.building.floor_area_m2)
    return compute_with(ci, replace(CalcParams.from_app_config(load_app_config()), **overrides), thermal)


def compute_with(ci: CalcInput, params: CalcParams, thermal: HouseThermal) -> CalcResult:
    """
    Compute min/max ventilation from the growth profile (weight, temperature, RH) and house data.
    Всё, кроме профиля роста, приходит аргументами — сохранённое состояние не читается.

    Qmin = max(Qmin_CO₂, Qmin_moisture)  — CIGR + психрометрический баланс.
    Qmax = (H_birds − UA×ΔT) × 3600 / (ρ × Cp × ΔT)  — тепловой баланс с поправкой стен.
           Ограничен физической мощностью установки. В туннельном режиме: полная мощность.
    """

    age = max(1, int(ci.age_days))
    _ua_coeff = thermal.ua_w_per_k
    calibration_ignored = thermal.calibration_ignored

    # --- Профиль роста: масса, целевые температура и RH на этот день ---
    # Профиля нет → ProfileNotFound наружу: расчёт по «чьим-то» данным
    # хуже, чем явная ошибка (раньше здесь был тихий fallback на демо-профиль)
    profile_id = ci.growth_profile_id or params.default_growth_profile
    profile = load_profile(profile_id)
    point = profile.point_for_day(age)

    if point.body_weight_g is None or point.min_temp_c is None:
        raise CalcError("profile_day_missing", id=profile_id, day=age)

    body_weight_g   = point.body_weight_g
    weight_kg       = max(body_weight_g / 1000.0, 0.0001)
    rv_percent      = ci.target_rh if ci.target_rh is not None else point.rv_percent

    # --- Effective birds with mortality ---
    # Отсчёт падежа — от дня посадки в корпус: survival(день посадки) = 1
    shift = params.placement_day - 1
    birds_eff = ci.birds * survival_fraction(age - shift, params.total_mortality_pct,
                                             params.cycle_days - shift)

    # Уставка — по методике производителя кросса (breed_climate): Ross — по массе
    # и RH, Cobb — по возрасту, затем по плотности посадки, Hubbard — по возрасту.
    # Та же RH — потолок влагобаланса, поэтому уставка и влажностный Qmin
    # меняются согласованно. Живая птица 14-го дня — для плотности Cobb
    birds_day14 = ci.birds * survival_fraction(14, params.total_mortality_pct, params.cycle_days)

    # Вторая группа (самки смешанного стада) — до дня выборки включительно
    companion = None
    group = ci.companion
    if group is not None and (group.last_day is None or age <= group.last_day):
        c_profile = load_profile(group.growth_profile_id)
        c_point = c_profile.point_for_day(age)
        if c_point.body_weight_g is None:
            raise CalcError("profile_day_missing", id=group.growth_profile_id, day=age)
        c_birds = group.birds * survival_fraction(age - shift, params.total_mortality_pct,
                                                  params.cycle_days - shift)
        companion = (c_profile, c_point, c_birds)

    # Пока в корпусе обе группы — уставка смешанного стада (своя таблица у Hybrid)
    setpoint = setpoint_for_day(profile, age, point, rv_percent, ci.stocking_floor_m2,
                                birds_eff, birds_day14, mixed=companion is not None)
    t_target_inside = setpoint.temp_c

    # Тепло одной птицы на уровне корпуса при уставке — одна модель для Qmax, горелок и
    # влаги. Закон полного тепла — по виду птицы профиля (бройлер, индейка)
    species = profile.species
    bird_heat = params.bird_heat_model(weight_kg, t_target_inside, species)

    # --- Qmin: биологический минимум по CO₂ (CIGR 1984) из живой массы ---
    # Норма считается из веса профиля роста, а не хранится в нём: профиль — это
    # данные кросса (вес, температура, RH), а вентиляция — следствие физики.
    safety = params.safety_factor_qmin
    per_bird_min = calc_q_min_per_bird(weight_kg, safety, species)

    # --- Смешанное стадо: дальше корпус видит «среднюю птицу» ---
    # Тепло, пар, CO₂ и масса — средние по живому поголовью обеих групп; всё ниже
    # умножает их на суммарное поголовье и получает сумму по группам. Нормы
    # производителей линейны по головам и массе (Aviagen — Σ n·w, Hybrid — Σ n),
    # поэтому норма «средней птицы» на всё поголовье тоже равна сумме — без потерь
    companion_alive = companion_weight_g = None
    if companion is not None:
        c_profile, c_point, c_birds = companion
        c_kg = max(c_point.body_weight_g / 1000.0, 0.0001)
        groups = [(birds_eff, bird_heat),
                  (c_birds, params.bird_heat_model(c_kg, t_target_inside, c_profile.species))]
        bird_heat = mix_heat(groups)
        n_total = birds_eff + c_birds
        per_bird_min = (birds_eff * per_bird_min
                        + c_birds * calc_q_min_per_bird(c_kg, safety, c_profile.species)) / n_total
        weight_kg = (birds_eff * weight_kg + c_birds * c_kg) / n_total
        body_weight_g = weight_kg * 1000.0
        companion_alive, companion_weight_g = c_birds, c_point.body_weight_g
        birds_eff = n_total
    q_min_co2 = birds_eff * per_bird_min

    # Норма производителя кросса (индейка: Aviagen — на кг, Hybrid — на голову по
    # неделям) — ещё одна нижняя граница рядом с CO₂, а не замена ему: норма не знает
    # ни горелок, ни влажности снаружи. Qmin = max(CO₂, норма, влага)
    q_min_guide: Optional[float] = None
    if profile.min_vent_norm:
        q_min_guide = guide_min_vent_m3h(profile.min_vent_norm, birds_eff, weight_kg, age,
                                         ci.stocking_floor_m2)
    q_min = max(q_min_co2, q_min_guide or 0.0)
    # Нижний предел без влаги: от него — потолок переходного режима (4 × минимум)
    q_min_floor = q_min

    # --- Туннель: требуемый расход — свойство КОРПУСА, а не поголовья ---
    # Q_tunnel = v × S_сечения × 3600. Раньше мощность туннеля хранилась на голову
    # (поделённая на n_birds_initial) и умножалась на введённое поголовье:
    # вдвое меньше птицы → вдвое меньше «вентиляторов».
    tunnel_min_day  = params.tunnel_min_day
    tunnel_min_temp = params.tunnel_min_temp_c
    v_tunnel        = params.v_tunnel_ms

    # Проектный туннельный расход корпуса (полная скорость) — для мощности и UI
    tunnel_requirement: Optional[float] = None
    # Туннельный расход с учётом возраста: молодой птице полную скорость не дают
    tunnel_flow_for_age: Optional[float] = None
    section_m2: Optional[float] = ci.tunnel_section_m2
    if section_m2 is None and ci.house_width_m and ci.house_height_m:
        section_m2 = ci.house_width_m * ci.house_height_m
    if section_m2:
        tunnel_requirement  = v_tunnel * section_m2 * 3600.0
        share = params.bird_speed_share
        v_for_age = min(v_tunnel, tunnel_speed_limit_ms(age, v_tunnel * share) / share)
        tunnel_flow_for_age = v_for_age * section_m2 * 3600.0

    # --- Тепловой баланс всего птичника ---
    # Тепло, которое должна унести вентиляция:
    #   Q_vent = H_birds - Q_walls
    #   H_birds = явное тепло КОРПУСА × N  [Вт]  (CIGR 2002, bird_heat)
    #   Q_walls = UA × (T_in - T_out)  [Вт]  (> 0 = тепло уходит через стены)
    #
    # В мороз Q_walls > 0: стены помогают охлаждению, нагрузка на вентиляцию ниже.
    # Без данных калибровки UA = 0 (консервативно: не занижаем Qmax).
    #
    # Баланс — по нагреву воздуха (ρ·Cp·ΔT), поэтому только явное тепло, и на
    # уровне КОРПУСА: часть тепла птицы уходит на испарение влаги из подстилки
    # и воздух не греет. Раньше бралось 6.90·W^0.75 (уровень птицы, 65 % полного),
    # а влагобаланс — долю корпуса: в сумме выходило больше 100 % (аудит 2026-10-18)
    h_birds_sensible_w = bird_heat.sensible_w * birds_eff
    q_wall_loss_w      = (_ua_coeff * (t_target_inside - ci.outside_t)
                          if _ua_coeff is not None else 0.0)
    q_vent_needed_w    = max(0.0, h_birds_sensible_w - q_wall_loss_w)

    # Объём через вытяжку — внутренний воздух, ρ при T_in (см. ventilation_heat_w)
    rho_air = air_density_kg_m3(t_target_inside)
    delta_t = t_target_inside - ci.outside_t

    # ΔT ≈ 0: воздух почти не охлаждает, баланс вырождается (деление на ~0)
    q_heat_balance = ((q_vent_needed_w * 3600.0) / (rho_air * AIR_CP_J_PER_KG_K * delta_t)
                      if delta_t > 0.5 else None)

    # --- Туннель: возраст и наружная T разрешают, а тепло корпуса — требует ---
    # Раньше хватало «≥ 14 дней и ≥ 18 °C»: в 14 дней при 18 °C снаружи (уставка 25 °C)
    # Qmax = полный туннель 2.5 м/с на птицу 0.5 кг (аудит 2026-10-18). Переходная
    # вентиляция через боковые клапаны рассчитана на 40–50 % мощности туннеля
    # (Ross Broiler Handbook 2025, с. 79) — туннель нужен, когда баланс требует больше.
    tunnel_allowed = (age >= tunnel_min_day) and (ci.outside_t >= tunnel_min_temp)
    if tunnel_allowed and tunnel_flow_for_age is not None:
        tunnel_active = (q_heat_balance is None
                         or q_heat_balance > TRANSITIONAL_SHARE_OF_TUNNEL * tunnel_flow_for_age)
    else:
        # Без размеров корпуса сравнить не с чем — прежнее правило, UI попросит размеры
        tunnel_active = tunnel_allowed

    # --- Qmax ---
    house_geometry_missing = False
    if tunnel_active:
        q_max_need = tunnel_flow_for_age
    else:
        # Потолок переходного режима:
        #   моложе tunnel_min_day — 4 × Qmin (Aviagen: переходная вентиляция 3–5× минимума);
        #   старше — туннельный расход корпуса для этого возраста
        ceiling = 4.0 * q_min if age < tunnel_min_day else tunnel_flow_for_age

        candidates = [q for q in (q_heat_balance, ceiling) if q is not None]
        # (влажностный Qmin ниже берёт тот же потолок через regime_ceiling_m3h)
        q_max_need = min(candidates) if candidates else None

    if q_max_need is None:
        # Не из чего считать: нужен туннельный расход, а размеров корпуса нет.
        # Честно сообщаем, а не подставляем «норму на голову» от чужого поголовья.
        house_geometry_missing = True
        q_max_need = q_min

    # Максимум не ниже минимума: в мороз тепловой баланс даёт крошечный Qmax
    q_max = max(q_min, q_max_need)

    per_bird_max = q_max / max(birds_eff, 1.0)
    per_kg_min = per_bird_min / weight_kg if weight_kg > 0 else 0.0
    per_kg_max = per_bird_max / weight_kg if weight_kg > 0 else 0.0

    # --- Влагобаланс (ШАГ 1): птицы, без пара горелок ---
    # Вычисляем до секции горелок, чтобы duty_cycle учитывал полный Qmin.
    # Пар горелок добавляется ниже как уточнение.
    qmin_basis = qmin_basis_of(q_min_co2, None, q_min_guide)
    humidity_uncontrollable = False
    _delta_w: Optional[float] = None   # сохраняем для шага 2 (с паром горелок)
    _G_birds_gph: float = 0.0

    # Потолок режима для влажностного Qmin — тот же, что ограничивает Qmax
    moisture_ceiling, ceiling_needs_geometry = regime_ceiling_m3h(
        age, tunnel_min_day, q_min_floor, tunnel_flow_for_age)
    _rho_in = air_density_kg_m3(t_target_inside)   # с поправкой на высоту фермы

    if rv_percent is not None:
        W_inside_max = humidity_ratio_g_per_kg(t_target_inside, rv_percent)
        W_outside    = humidity_ratio_g_per_kg(ci.outside_t, ci.outside_rh)
        _delta_w     = W_inside_max - W_outside

        # Пар корпуса = скрытое тепло на уровне корпуса (CIGR 2002, bird_heat): дыхание
        # птицы + испарение с подстилки, полное тепло — С температурной поправкой
        # (без неё скрытое при 32 °C было завышено в 1.45 раза)
        _G_birds_gph = bird_heat.vapour_g_per_h * birds_eff

        q_min_moisture_birds, humidity_uncontrollable = moisture_qmin_m3h(
            _G_birds_gph, _rho_in, _delta_w, moisture_ceiling)

        if q_min_moisture_birds > q_min:
            q_min      = q_min_moisture_birds
            qmin_basis = "moisture"

    # --- Горелки: загрузка, согласованная с их собственным воздухом ---
    # Открытое пламя добавляет к Qmin две вещи: воздух на разбавление CO₂ (ветка CO₂)
    # и пар (ветка влаги). Qmin = max(CO₂ птицы + CO₂ горелок, влага птицы + пар горелок).
    # Загрузка d зависит от Qmin (его воздух надо греть), Qmin — от d, поэтому решаем
    # совместно (solve_heater_duty). Раньше d считался по Qmin без воздуха горелок,
    # воздух добавлялся после, и загрузка занижалась в 2–2.5 раза (аудит 2026-10-18).
    heater_air = 0.0
    duty_cycle = None
    heater_insufficient = False

    heat_need_w: Optional[float] = None
    if thermal.heater and _ua_coeff is not None:
        heater_kw   = thermal.heater.total_power_kw
        heater_type = thermal.heater.heater_type
        q_min_birds = q_min                     # без горелок: max(CO₂, влага) птицы
        open_flame  = ci.heater_on and heater_type == "gas_open"

        def qmin_for_duty(d: float) -> float:
            if not ci.heater_on:
                return q_min_birds
            q_co2_branch = q_min_co2 + heater_co2_dilution_m3h(heater_kw, d, heater_type)
            q_moist_branch = 0.0
            if open_flame and _delta_w is not None:
                gas_m3h = heater_kw / 10.0 * d                 # LHV ≈ 10 кВт·ч/м³
                q_moist_branch, _ = moisture_qmin_m3h(
                    _G_birds_gph + gas_m3h * 1607.0, _rho_in, _delta_w, moisture_ceiling)
            return max(q_co2_branch, q_moist_branch, q_min_birds)

        sol = solve_heater_duty(
            qmin_for_duty,
            ua_w_per_k       = _ua_coeff,
            t_inside_c       = t_target_inside,
            t_outside_c      = ci.outside_t,
            birds_sensible_w = bird_heat.sensible_w * birds_eff,
            heater_power_w   = heater_kw * 1000.0,
            exchange_floor_m3h = ci.air_exchange_floor_m3h,
        )
        duty_cycle          = sol.duty_cycle
        heat_need_w         = sol.heat_need_w
        heater_insufficient = sol.insufficient

        if ci.heater_on:
            heater_air = heater_co2_dilution_m3h(heater_kw, duty_cycle, heater_type)
            q_min = sol.qmin_m3h
            # Какая ветка правит при найденной загрузке: CO₂ (птица + горелки) или влага
            if open_flame and _delta_w is not None:
                gas_m3h = heater_kw / 10.0 * duty_cycle
                q_moist, capped = moisture_qmin_m3h(
                    _G_birds_gph + gas_m3h * 1607.0, _rho_in, _delta_w, moisture_ceiling)
                humidity_uncontrollable = humidity_uncontrollable or capped
                qmin_basis = qmin_basis_of(q_min_co2 + heater_air, q_moist, q_min_guide)
            elif heater_air > 0:
                # Сюда попадает только открытое пламя без целевой RH: влага не считалась
                qmin_basis = qmin_basis_of(q_min_co2 + heater_air, None, q_min_guide)

    # Горелки включены, но загрузку не найти — нет калибровки UA или данных о горелке.
    # Раньше здесь добавлялось 0.10 / 0.05 / 0.025 м³/ч на голову по возрасту: числа
    # без источника, и добавлялись они даже электрическим обогревателям, у которых
    # CO₂ нет вовсе (аудит 2026-10-18). Теперь — только то, что следует из данных:
    heater_note: Optional[str] = None
    if ci.heater_on and duty_cycle is None:
        heater = thermal.heater
        if heater is None:
            # Ни мощности, ни типа: добавить нечего — так и говорим, а не угадываем
            heater_note = "heater_data_missing"
        elif heater.heater_type == "gas_open":
            # Мощность известна, загрузки нет (UA не откалиброван): разбавление CO₂ при
            # 100 % — оценка СВЕРХУ, в безопасную для птицы сторону
            heater_air = heater_co2_dilution_m3h(heater.total_power_kw, 1.0, heater.heater_type)
            if q_min_co2 + heater_air > q_min:
                q_min, qmin_basis = q_min_co2 + heater_air, "co2"
            heater_note = "heater_full_duty_estimate"
        # Электрические и непрямого нагрева воздух птичника не загрязняют — поправки нет

    # Конденсат на ограждениях при целевой RH внутри (ASHRAE, теплопередача через стенку)
    surface_temp = dew_in = None
    condensation = False
    if _ua_coeff is not None and thermal.building \
            and rv_percent is not None and t_target_inside > ci.outside_t:
        surface_temp, dew_in, condensation = surface_condensation(
            _ua_coeff, thermal.building, t_target_inside, rv_percent, ci.outside_t)

    # Потребность в тепле без горелок (известен только UA): мощность 0 → solve
    # отдаёт потребность при d = 0, то есть без воздуха на разбавление продуктов
    # сгорания — тип горелок неизвестен
    if heat_need_w is None and _ua_coeff is not None:
        heat_need_w = solve_heater_duty(
            lambda d: q_min, ua_w_per_k=_ua_coeff, t_inside_c=t_target_inside,
            t_outside_c=ci.outside_t, birds_sensible_w=bird_heat.sensible_w * birds_eff,
            heater_power_w=0.0, exchange_floor_m3h=ci.air_exchange_floor_m3h,
        ).heat_need_w

    # Влажность упёрлась в потолок, а потолок без размеров корпуса только оценён
    if humidity_uncontrollable and ceiling_needs_geometry:
        house_geometry_missing = True

    # Влагобаланс и воздух горелок могли поднять Qmin уже ПОСЛЕ расчёта Qmax:
    # максимум по определению не ниже минимума
    if q_max < q_min:
        q_max = q_min
        per_bird_max = q_max / max(birds_eff, 1.0)
        per_kg_max = per_bird_max / weight_kg if weight_kg > 0 else 0.0

    return CalcResult(
        q_min_m3h=float(q_min),
        q_max_m3h=float(q_max),
        weight_used_g=body_weight_g,
        profile_day_resolved=age,
        rates_per_bird_min=per_bird_min,
        rates_per_bird_max=per_bird_max,
        rates_per_kg_min=per_kg_min,
        rates_per_kg_max=per_kg_max,
        min_temp_c=t_target_inside,
        rv_percent=rv_percent,
        heater_air_m3h=heater_air if heater_air > 0 else None,
        heater_duty_cycle=duty_cycle,
        tunnel_active=tunnel_active,
        qmin_basis=qmin_basis,
        tunnel_requirement_m3h=tunnel_requirement,
        house_geometry_missing=house_geometry_missing,
        growth_profile_id=profile_id,
        humidity_uncontrollable=humidity_uncontrollable,
        heater_note=heater_note,
        surface_temp_c=surface_temp,
        dew_point_inside_c=dew_in,
        condensation_risk=condensation,
        heater_insufficient=heater_insufficient,
        calibration_ignored=calibration_ignored,
        heat_need_w=heat_need_w,
        birds_alive=birds_eff,
        setpoint_method=setpoint.method,
        # Та же формула, что у плотности Cobb в breed_climate: живая птица × масса
        # профиля / пол. Отдаётся для всех кроссов — агенту не пересчитывать самому
        stocking_density_kg_m2=(birds_eff * weight_kg / ci.stocking_floor_m2
                                if ci.stocking_floor_m2 else None),
        species=species,
        qmin_guide_m3h=q_min_guide,
        companion_alive=companion_alive,
        companion_weight_g=companion_weight_g,
    )
