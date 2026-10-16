from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal, Optional

from .growth_profiles import load_profile
from .apparent_temp import rh_temperature_shift
from .ventilation_calc import calc_q_min_per_bird
from .app_config import load_app_config
from .building_thermal import (
    load_thermal_config,
    heater_air_demand,
    heater_co2_dilution_m3h,
)


DisplayUnit = Literal["per_bird", "per_kg"]

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


# ─── Модели данных ────────────────────────────────────────────────────────────

@dataclass
class CalcInput:
    birds: int
    age_days: int
    display_unit: DisplayUnit
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


@dataclass
class CalcResult:
    q_min_m3h: float
    q_max_m3h: float
    basis_used: DisplayUnit
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
    _ua_coeff: Optional[float] = None
    try:
        _thermal_cfg = load_thermal_config()
        if _thermal_cfg.calibration:
            _ua_coeff = _thermal_cfg.calibration.ua_coefficient
    except Exception:
        _thermal_cfg = None

    # --- Профиль роста: масса, целевые температура и RH на этот день ---
    # Профиля нет → ProfileNotFound наружу: расчёт по «чьим-то» данным
    # хуже, чем явная ошибка (раньше здесь был тихий fallback на демо-профиль)
    profile_id = ci.growth_profile_id or getattr(cfg, "default_growth_profile", "ross308")
    point = load_profile(profile_id).point_for_day(age)

    if point.body_weight_g is None or point.min_temp_c is None:
        raise ValueError(f"В профиле '{profile_id}' нет массы или температуры на день {age}")

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
    total_m = max(getattr(cfg, "total_mortality_pct", 0.0), 0.0) / 100.0
    daily_m = 1.0 - (1.0 - total_m) ** (1.0 / max(41, 1))
    survival = (1.0 - daily_m) ** max(age - 1, 0)
    birds_eff = ci.birds * survival

    # --- Qmin: биологический минимум по CO₂ (CIGR 1984) из живой массы ---
    # Норма считается из веса профиля роста, а не хранится в нём: профиль — это
    # данные кросса (вес, температура, RH), а вентиляция — следствие физики.
    safety = float(getattr(cfg, "safety_factor_qmin", 1.5))
    per_bird_min = calc_q_min_per_bird(weight_kg, safety)
    q_min = birds_eff * per_bird_min

    # --- Туннель: требуемый расход — свойство КОРПУСА, а не поголовья ---
    # Q_tunnel = v × S_сечения × 3600. Раньше мощность туннеля хранилась на голову
    # (поделённая на n_birds_initial) и умножалась на введённое поголовье:
    # вдвое меньше птицы → вдвое меньше «вентиляторов».
    tunnel_min_day  = int(getattr(cfg, "tunnel_min_day", 14))
    tunnel_min_temp = float(getattr(cfg, "tunnel_min_temp_c", 18.0))
    tunnel_active   = (age >= tunnel_min_day) and (ci.outside_t >= tunnel_min_temp)

    tunnel_requirement: Optional[float] = None
    if ci.house_width_m and ci.house_height_m:
        v_tunnel = float(getattr(cfg, "v_tunnel_ms", 2.5))
        tunnel_requirement = v_tunnel * ci.house_width_m * ci.house_height_m * 3600.0

    # --- Qmax ---
    house_geometry_missing = False
    if tunnel_active:
        q_max_need = tunnel_requirement
    else:
        # Туннель OFF: тепловой баланс всего птичника.
        #
        # Тепло, которое должна унести вентиляция:
        #   Q_vent = H_birds - Q_walls
        #   H_birds = 6.90 × W^0.75 × N  [Вт]  (CIGR, только ЯВНОЕ тепло)
        #   Q_walls = UA × (T_in - T_out)  [Вт]  (> 0 = тепло уходит через стены)
        #
        # В мороз Q_walls > 0: стены помогают охлаждению, нагрузка на вентиляцию ниже.
        # Без данных калибровки UA = 0 (консервативно: не занижаем Qmax).
        #
        # Почему 6.90, а не полное тепло 10.62: баланс ниже — по нагреву воздуха
        # (ρ·Cp·ΔT). Скрытое тепло (3.72·W^0.75) уходит с паром дыхания и
        # температуру воздуха не поднимает; с ним Qmax завышался на 54 %.
        h_birds_sensible_w = 6.90 * (weight_kg ** 0.75) * birds_eff
        q_wall_loss_w      = (_ua_coeff * (t_target_inside - ci.outside_t)
                              if _ua_coeff is not None else 0.0)
        q_vent_needed_w    = max(0.0, h_birds_sensible_w - q_wall_loss_w)

        rho_air = 353.05 / (ci.outside_t + 273.15)
        delta_t = t_target_inside - ci.outside_t

        # ΔT ≈ 0: воздух почти не охлаждает, баланс вырождается (деление на ~0)
        q_heat_balance = ((q_vent_needed_w * 3600.0) / (rho_air * 1006.0 * delta_t)
                          if delta_t > 0.5 else None)

        # Потолок переходного режима:
        #   моложе tunnel_min_day — 4 × Qmin (Aviagen: переходная вентиляция 3–5× минимума);
        #   старше — туннельный расход корпуса (холоднее tunnel_min_temp туннель не включают,
        #   но больше него установка всё равно не даст)
        ceiling = 4.0 * q_min if age < tunnel_min_day else tunnel_requirement

        candidates = [q for q in (q_heat_balance, ceiling) if q is not None]
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
    basis = "per_bird"

    # --- Влагобаланс (ШАГ 1): птицы, без пара горелок ---
    # Вычисляем до секции горелок, чтобы duty_cycle учитывал полный Qmin.
    # Пар горелок добавляется ниже как уточнение.
    qmin_basis = "co2"
    _delta_w: Optional[float] = None   # сохраняем для шага 2 (с паром горелок)
    _G_birds_gph: float = 0.0

    if rv_percent is not None:
        W_inside_max = humidity_ratio_g_per_kg(t_target_inside, rv_percent)
        W_outside    = humidity_ratio_g_per_kg(ci.outside_t, ci.outside_rh)
        _delta_w     = W_inside_max - W_outside

        if _delta_w > 0.1:
            q_latent_w   = 3.72 * (weight_kg ** 0.75)
            _G_birds_gph = q_latent_w * 3600.0 / 2430.0 * birds_eff
            rho_in       = 353.05 / (t_target_inside + 273.15)
            q_min_moisture_birds = _G_birds_gph / (rho_in * _delta_w)

            if q_min_moisture_birds > q_min:
                q_min      = q_min_moisture_birds
                qmin_basis = "moisture"

    # --- Горелки: duty_cycle + CO₂ от открытого горения ---
    # duty_cycle учитывает ТРИ слагаемых теплового баланса:
    #   Q_need = UA×ΔT  +  Q_vent_heat  −  Q_птиц_чувств
    #   Q_vent_heat = Qmin [м³/ч] × ρ_вход × Cp × ΔT / 3600
    # Qmin здесь — текущее значение после влагобаланса птиц (без пара горелок).
    # Это главный член в холодную погоду (уносится с минимальным воздухом).
    heater_air = 0.0
    duty_cycle = None

    if _thermal_cfg is not None and _thermal_cfg.heater and _thermal_cfg.calibration:
        q_birds_sensible_w = 6.90 * (weight_kg ** 0.75) * birds_eff
        delta_t_h  = max(0.0, t_target_inside - ci.outside_t)

        # Нагрев входящего воздуха: холодный воздух Qmin м³/ч нужно догреть до T_in
        rho_inlet      = 353.05 / (ci.outside_t + 273.15)
        q_vent_heat_w  = (q_min / 3600.0) * rho_inlet * 1006.0 * delta_t_h

        heat_need_w = max(0.0,
            _thermal_cfg.calibration.ua_coefficient * delta_t_h
            + q_vent_heat_w
            - q_birds_sensible_w
        )
        heater_power_w = _thermal_cfg.heater.total_power_kw * 1000.0
        duty_cycle = min(heat_need_w / heater_power_w, 1.0) if heater_power_w > 0 else 0.0

        if ci.heater_on:
            heater_air = heater_co2_dilution_m3h(
                heater_power_kw=_thermal_cfg.heater.total_power_kw,
                duty_cycle=duty_cycle,
                heater_type=_thermal_cfg.heater.heater_type,
            )
            q_min += heater_air

    # Fallback: нет calibration данных → эмпирическая поправка на поголовье
    if ci.heater_on and duty_cycle is None:
        delta_per_bird = 0.10 if age <= 14 else (0.05 if age <= 28 else 0.025)
        heater_air     = birds_eff * delta_per_bird
        q_min         += heater_air
        per_bird_min  += delta_per_bird

    # --- Влагобаланс (ШАГ 2): добавляем пар газовых горелок ---
    # Горелки открытого горения выбрасывают H₂O в птичник (1 м³ газа → 1.607 кг H₂O).
    # Уточняем G_total и пересчитываем Qmin_moisture если duty_cycle известен.
    if (_delta_w is not None and _delta_w > 0.1
            and ci.heater_on and duty_cycle is not None
            and _thermal_cfg is not None and _thermal_cfg.heater
            and _thermal_cfg.heater.heater_type == "gas_open"):
        _gas         = (_thermal_cfg.heater.total_power_kw / 100.0) * 10.0 * duty_cycle
        G_heater_gph = _gas * 1607.0
        rho_in       = 353.05 / (t_target_inside + 273.15)
        q_min_moisture_total = (_G_birds_gph + G_heater_gph) / (rho_in * _delta_w)
        if q_min_moisture_total > q_min:
            q_min      = q_min_moisture_total
            qmin_basis = "moisture"

    # Влагобаланс и воздух горелок могли поднять Qmin уже ПОСЛЕ расчёта Qmax:
    # максимум по определению не ниже минимума
    if q_max < q_min:
        q_max = q_min
        per_bird_max = q_max / max(birds_eff, 1.0)
        per_kg_max = per_bird_max / weight_kg if weight_kg > 0 else 0.0

    return CalcResult(
        q_min_m3h=float(q_min),
        q_max_m3h=float(q_max),
        basis_used=basis,
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
    )
