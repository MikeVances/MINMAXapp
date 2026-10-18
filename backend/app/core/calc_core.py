from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from .errors import CalcError
from .growth_profiles import load_profile
from .apparent_temp import rh_temperature_shift
from .survival import survival_fraction
from .bird_heat import house_heat_per_bird, house_sensible_fraction
from .ventilation_calc import calc_q_min_per_bird
from .app_config import load_app_config
from .building_thermal import (
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

def sat_pressure_pa(T_c: float) -> float:
    """Давление насыщенного пара при T_c (°C). Формула Магнуса, ±0.1% в -40..+60°C."""
    return 611.2 * math.exp(17.67 * T_c / (T_c + 243.5))


def humidity_ratio_g_per_kg(T_c: float, rh_pct: float) -> float:
    """Влагосодержание воздуха, г/кг с.в. при (T°C, RH%)."""
    P_s = sat_pressure_pa(T_c)
    P_v = P_s * max(rh_pct, 0.0) / 100.0
    P_atm = 101_325.0
    # Клапейрон–Клаузиус: W = 0.622 × Pv / (Patm − Pv)
    return 0.622 * P_v / max(P_atm - P_v, 1.0) * 1000.0  # г/кг


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
    qmin_basis: str = "co2"  # "co2" | "moisture" — какое ограничение определило Qmin
    # Требуемый туннельный расход корпуса v × S × 3600, м³/ч (None — нет размеров)
    tunnel_requirement_m3h: Optional[float] = None
    # Qmax не посчитан: нужен туннельный расход, а размеров корпуса нет (Qmax = Qmin)
    house_geometry_missing: bool = False
    # Наружный воздух не суше целевого внутреннего (ΔW ≤ 0.1 г/кг): вентиляцией RH
    # не удержать при любом расходе, Qmin показан по CO₂
    humidity_uncontrollable: bool = False
    # Горелок не хватает даже на 100 % (с учётом подогрева их же воздуха разбавления)
    heater_insufficient: bool = False
    # Почему калибровка UA не применена: {code, params} или None
    calibration_ignored: Optional[dict] = None
    # Профиль роста, по которому шёл расчёт (видно, какие данные кросса использованы)
    growth_profile_id: Optional[str] = None


def compute(ci: CalcInput) -> CalcResult:
    """
    Compute min/max ventilation from the growth profile (weight, temperature, RH) and house data.

    Qmin = max(Qmin_CO₂, Qmin_moisture)  — CIGR + психрометрический баланс.
    Qmax = (H_birds − UA×ΔT) × 3600 / (ρ × Cp × ΔT)  — тепловой баланс с поправкой стен.
           Ограничен физической мощностью установки. В туннельном режиме: полная мощность.
    """

    cfg = load_app_config()
    age = max(1, int(ci.age_days))

    # Загружаем thermal_cfg один раз — используется в Qmax (UA), duty_cycle и влагобалансе
    _thermal_cfg = None
    # UA — только проверенной калибровки СВОЕГО корпуса (usable_ua): калибровка
    # чужого корпуса, тест короче 10 мин или неправдоподобный U оболочки в расчёт
    # не идут, а причина уходит в ответ, чтобы UI предупредил
    _ua_coeff: Optional[float] = None
    calibration_ignored: Optional[dict] = None
    try:
        _thermal_cfg = load_thermal_config()
        _ua_coeff, calibration_ignored = usable_ua(_thermal_cfg, ci.house_id)
    except Exception:
        _thermal_cfg = None

    # --- Профиль роста: масса, целевые температура и RH на этот день ---
    # Профиля нет → ProfileNotFound наружу: расчёт по «чьим-то» данным
    # хуже, чем явная ошибка (раньше здесь был тихий fallback на демо-профиль)
    profile_id = ci.growth_profile_id or getattr(cfg, "default_growth_profile", "ross308")
    point = load_profile(profile_id).point_for_day(age)

    if point.body_weight_g is None or point.min_temp_c is None:
        raise CalcError("profile_day_missing", id=profile_id, day=age)

    body_weight_g   = point.body_weight_g
    weight_kg       = max(body_weight_g / 1000.0, 0.0001)
    rv_percent      = ci.target_rh if ci.target_rh is not None else point.rv_percent

    # Температура профиля — опорная при RH 60 %. При другой целевой RH птица
    # ощущает ту же сухую температуру иначе: суше — уставку выше, влажнее — ниже
    # (Ross Handbook 2025, табл. 2.5). Та же RH ниже — потолок влагобаланса,
    # поэтому уставка и влажностный Qmin меняются согласованно.
    # RH профиля вне таблицы (свой профиль с 80 %) — поправку не применяем.
    t_target_inside = point.min_temp_c
    if rv_percent is not None and 40.0 <= rv_percent <= 70.0:
        t_target_inside += rh_temperature_shift(body_weight_g, rv_percent)

    # --- Effective birds with mortality ---
    birds_eff = ci.birds * survival_fraction(age, cfg.total_mortality_pct, cfg.cycle_days)

    # Тепло одной птицы на уровне корпуса при уставке — одна модель для Qmax, горелок и влаги
    bird_heat = house_heat_per_bird(weight_kg, t_target_inside)

    # --- Qmin: биологический минимум по CO₂ (CIGR 1984) из живой массы ---
    # Норма считается из веса профиля роста, а не хранится в нём: профиль — это
    # данные кросса (вес, температура, RH), а вентиляция — следствие физики.
    safety = float(getattr(cfg, "safety_factor_qmin", 1.5))
    per_bird_min = calc_q_min_per_bird(weight_kg, safety)
    q_min = birds_eff * per_bird_min
    q_min_co2 = q_min

    # --- Туннель: требуемый расход — свойство КОРПУСА, а не поголовья ---
    # Q_tunnel = v × S_сечения × 3600. Раньше мощность туннеля хранилась на голову
    # (поделённая на n_birds_initial) и умножалась на введённое поголовье:
    # вдвое меньше птицы → вдвое меньше «вентиляторов».
    tunnel_min_day  = int(getattr(cfg, "tunnel_min_day", 14))
    tunnel_min_temp = float(getattr(cfg, "tunnel_min_temp_c", 18.0))
    v_tunnel        = float(getattr(cfg, "v_tunnel_ms", 2.5))

    # Проектный туннельный расход корпуса (полная скорость) — для мощности и UI
    tunnel_requirement: Optional[float] = None
    # Туннельный расход с учётом возраста: молодой птице полную скорость не дают
    tunnel_flow_for_age: Optional[float] = None
    if ci.house_width_m and ci.house_height_m:
        section_m2 = ci.house_width_m * ci.house_height_m
        tunnel_requirement  = v_tunnel * section_m2 * 3600.0
        tunnel_flow_for_age = min(v_tunnel, tunnel_speed_limit_ms(age, v_tunnel)) * section_m2 * 3600.0

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
    qmin_basis = "co2"
    humidity_uncontrollable = False
    _delta_w: Optional[float] = None   # сохраняем для шага 2 (с паром горелок)
    _G_birds_gph: float = 0.0

    # Потолок режима для влажностного Qmin — тот же, что ограничивает Qmax
    moisture_ceiling, ceiling_needs_geometry = regime_ceiling_m3h(
        age, tunnel_min_day, q_min_co2, tunnel_flow_for_age)
    _rho_in = 353.05 / (t_target_inside + 273.15)

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

    if _thermal_cfg is not None and _thermal_cfg.heater and _ua_coeff is not None:
        heater_kw   = _thermal_cfg.heater.total_power_kw
        heater_type = _thermal_cfg.heater.heater_type
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
        )
        duty_cycle          = sol.duty_cycle
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
                qmin_basis = "moisture" if q_moist > q_min_co2 + heater_air else "co2"
            elif heater_air > 0:
                qmin_basis = "co2"

    # Fallback: нет calibration данных → эмпирическая поправка на поголовье
    if ci.heater_on and duty_cycle is None:
        delta_per_bird = 0.10 if age <= 14 else (0.05 if age <= 28 else 0.025)
        heater_air     = birds_eff * delta_per_bird
        q_min         += heater_air
        per_bird_min  += delta_per_bird

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
        heater_insufficient=heater_insufficient,
        calibration_ignored=calibration_ignored,
    )
