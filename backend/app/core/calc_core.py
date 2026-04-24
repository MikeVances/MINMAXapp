from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

from .profile_loader import VentProfile, Mode, ProfilePoint
from .day_master import load_day_master
from .app_config import load_app_config
from .building_thermal import (
    load_thermal_config,
    calculate_heater_duty_cycle,
    heater_air_demand,
)


DisplayUnit = Literal["per_bird", "per_kg"]


@dataclass
class CalcInput:
    birds: int
    age_days: int
    mode: Mode
    display_unit: DisplayUnit
    outside_t: float  # °C
    heater_on: bool = False


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
    heater_air_m3h: Optional[float] = None  # Дополнительный воздух для газовых обогревателей
    heater_duty_cycle: Optional[float] = None  # Коэффициент загрузки обогревателей (0..1)


def temp_coefficient(t_outdoor: float, t_inside: float) -> float:
    """
    Рассчитывает коэффициент вентиляции на основе разницы температур.

    Физика:
    - При большой разнице (холод) воздух плотнее (больше O2 в м³) + большие теплопотери
      → нужно меньше воздухообмена → коэффициент < 1.0
    - При малой разнице (жара) плохое охлаждение + низкая плотность воздуха
      → нужно больше воздухообмена → коэффициент > 1.0

    Args:
        t_outdoor: Температура наружного воздуха, °C
        t_inside: Целевая температура внутри птичника, °C

    Returns:
        Коэффициент (0.5 .. 1.5+), который умножается на базовые нормы Qmin/Qmax
    """
    delta_t = t_inside - t_outdoor

    if delta_t > 20:  # Зима: -10°C снаружи, +30°C внутри
        # Минимальная вентиляция (плотный воздух + теплопотери)
        return 0.5
    elif delta_t < 5:  # Жара: +30°C снаружи, +25°C внутри
        # Максимальная вентиляция (плохой отвод тепла)
        return 1.5
    else:
        # Линейная интерполяция между 0.5 и 1.5
        # delta_t = 20 → k = 0.5
        # delta_t = 5  → k = 1.5
        return 0.5 + (20 - delta_t) / 15 * 1.0


def compute(profile: VentProfile, ci: CalcInput) -> CalcResult:
    """
    Compute min/max ventilation using day_master norms with temperature coefficient.

    New behaviour (refactored):
    - Uses q_min_per_bird and q_max_per_bird from day_master as base norms
    - Applies temperature coefficient based on outdoor vs target indoor temperature
    - Falls back to old profile-based logic if day_master norms are missing
    - Respects heater correction and mortality for effective bird count
    """

    cfg = load_app_config()
    age = max(1, int(ci.age_days))

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

    # --- Calculate temperature coefficient ---
    k_temp = temp_coefficient(ci.outside_t, t_target_inside)

    # --- Get base ventilation norms ---
    if day_info and day_info.q_min_per_bird is not None and day_info.q_max_per_bird is not None:
        # NEW: Use norms from day_master
        per_bird_min_base = float(day_info.q_min_per_bird)
        per_bird_max_base = float(day_info.q_max_per_bird)

        # Apply temperature coefficient
        per_bird_min = per_bird_min_base * k_temp
        per_bird_max = per_bird_max_base * k_temp

        # Calculate per-kg equivalents for display
        per_kg_min = per_bird_min / weight_kg if weight_kg > 0 else 0.0
        per_kg_max = per_bird_max / weight_kg if weight_kg > 0 else 0.0

        basis = "per_bird"  # We used per-bird norms from day_master

    else:
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

    # --- Heater correction (always applied) ---
    if ci.heater_on:
        if age <= 14:
            per_bird_min += 0.10
        elif age <= 28:
            per_bird_min += 0.05
        else:
            per_bird_min += 0.025

    # --- Calculate total flows ---
    q_min = birds_eff * per_bird_min
    q_max = birds_eff * per_bird_max

    # --- Calculate additional air for gas heaters (if configured) ---
    heater_air = 0.0
    duty_cycle = None

    try:
        thermal_cfg = load_thermal_config()
        if thermal_cfg.heater and thermal_cfg.calibration:
            # Calculate heater duty cycle
            duty_cycle = calculate_heater_duty_cycle(
                ua_coefficient=thermal_cfg.calibration.ua_coefficient,
                t_inside_target=t_target_inside,
                t_outside=ci.outside_t,
                heater_power_kw=thermal_cfg.heater.total_power_kw,
            )

            # Calculate additional air for gas combustion
            heater_air = heater_air_demand(
                heater_power_kw=thermal_cfg.heater.total_power_kw,
                duty_cycle=duty_cycle,
                heater_type=thermal_cfg.heater.heater_type,
            )

            # Add heater air to minimum ventilation
            q_min += heater_air

    except Exception:
        # If thermal config is not available or invalid, continue without heater adjustment
        pass

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
    )
