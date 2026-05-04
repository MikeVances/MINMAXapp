from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal, Optional

from .profile_loader import VentProfile, Mode, ProfilePoint
from .day_master import load_day_master
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
    mode: Mode
    display_unit: DisplayUnit
    outside_t: float    # °C
    heater_on: bool = False
    outside_rh: float = 60.0  # % относительная влажность снаружи


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


def compute(profile: VentProfile, ci: CalcInput) -> CalcResult:
    """
    Compute min/max ventilation using day_master norms.

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

    # --- Load Day Master data ---
    dm = load_day_master()
    day_info = dm.get(age) if dm else None

    # Get weight and setpoints
    if day_info and day_info.body_weight_g is not None:
        body_weight_g = day_info.body_weight_g
    else:
        # Fallback to profile
        p = profile.get_point(ci.mode, age, strategy="floor")
        body_weight_g = p.body_weight_g

    weight_kg = max(body_weight_g / 1000.0, 0.0001)

    # Get target temperature (for coefficient calculation)
    if day_info and day_info.min_temp_c is not None:
        t_target_inside = day_info.min_temp_c
    else:
        p = profile.get_point(ci.mode, age, strategy="floor")
        t_target_inside = p.min_temp_c or 25.0

    # Get RH setpoint
    if day_info and day_info.rv_percent is not None:
        rv_percent = day_info.rv_percent
    else:
        p = profile.get_point(ci.mode, age, strategy="floor")
        rv_percent = p.rv_percent

    # --- Effective birds with mortality ---
    total_m = max(getattr(cfg, "total_mortality_pct", 0.0), 0.0) / 100.0
    daily_m = 1.0 - (1.0 - total_m) ** (1.0 / max(41, 1))
    survival = (1.0 - daily_m) ** max(age - 1, 0)
    birds_eff = ci.birds * survival

    # --- Get base ventilation norms ---
    if day_info and day_info.q_min_per_bird is not None and day_info.q_max_per_bird is not None:
        per_bird_min_base = float(day_info.q_min_per_bird)
        per_bird_max_base = float(day_info.q_max_per_bird)

        # Tunnel mode restrictions (Aviagen 2019 / industry standard)
        tunnel_min_day  = int(getattr(cfg, "tunnel_min_day", 14))
        tunnel_min_temp = float(getattr(cfg, "tunnel_min_temp_c", 18.0))
        tunnel_active   = (age >= tunnel_min_day) and (ci.outside_t >= tunnel_min_temp)

        # Qmin — биологический минимум по CO₂ (CIGR), не зависит от T наружного воздуха.
        per_bird_min = per_bird_min_base

        if tunnel_active:
            # Туннель ON: физическая мощность установки (поголовная)
            per_bird_max = per_bird_max_base
        else:
            # Туннель OFF: тепловой баланс всего птичника.
            #
            # Тепло, которое должна унести вентиляция:
            #   Q_vent = H_birds - Q_walls
            #   H_birds = 10.62 × W^0.75 × N  [Вт]  (CIGR, весь метаболизм)
            #   Q_walls = UA × (T_in - T_out)  [Вт]  (> 0 = тепло уходит через стены)
            #
            # В мороз Q_walls > 0: стены помогают охлаждению, нагрузка на вентиляцию ниже.
            # В жару T_out > T_in: Q_walls < 0, стены добавляют тепло → Qmax растёт.
            # Без данных калибровки UA = 0 (консервативно: не занижаем Qmax).
            h_birds_total_w = 10.62 * (weight_kg ** 0.75) * birds_eff
            q_wall_loss_w   = (_ua_coeff * (t_target_inside - ci.outside_t)
                               if _ua_coeff is not None else 0.0)
            q_vent_needed_w = max(0.0, h_birds_total_w - q_wall_loss_w)

            rho_air = 353.05 / (ci.outside_t + 273.15)
            delta_t = t_target_inside - ci.outside_t

            if delta_t > 0.5:
                # Q_total [м³/ч] = Q_vent_needed [Вт] × 3600 / (ρ × Cp × ΔT)
                q_max_cooling_total = (q_vent_needed_w * 3600.0) / (rho_air * 1006.0 * delta_t)
            else:
                # ΔT ≈ 0: стены не отводят тепло — полная мощность установки
                q_max_cooling_total = per_bird_max_base * birds_eff

            per_bird_max = max(
                per_bird_min,
                min(q_max_cooling_total / max(birds_eff, 1), per_bird_max_base),
            )

        # Calculate per-kg equivalents for display
        per_kg_min = per_bird_min / weight_kg if weight_kg > 0 else 0.0
        per_kg_max = per_bird_max / weight_kg if weight_kg > 0 else 0.0

        basis = "per_bird"  # We used per-bird norms from day_master

    else:
        tunnel_active = False
        # FALLBACK: Old profile-based logic
        p = profile.get_point(ci.mode, age, strategy="floor")
        per_bird_min = float(p.min_per_bird or 0)
        per_bird_max = float(p.max_per_bird or 0)
        per_kg_min = float(p.min_per_kg or 0)
        per_kg_max = float(p.max_per_kg or 0)

        # Apply metabolic correction for min
        if per_kg_min > 0:
            per_bird_from_kg = per_kg_min * (weight_kg ** 0.75)
            per_bird_min = max(per_bird_min, per_bird_from_kg)

        # Apply floor thresholds
        if age <= 7:
            per_bird_min = max(per_bird_min, getattr(cfg, "min_floor_0_7", 0.0))
        elif age <= 14:
            per_bird_min = max(per_bird_min, getattr(cfg, "min_floor_7_14", 0.0))

        basis = ci.display_unit

    # --- Calculate total flows ---
    q_min = birds_eff * per_bird_min   # базовый Qmin по CO₂ (CIGR)
    q_max = birds_eff * per_bird_max

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
    )
