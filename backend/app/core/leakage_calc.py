"""
Калькулятор герметичности (воздухопроницаемости) птичника.

Основан на методике UGA (University of Georgia, Michael Czarick):
  https://www.poultryventilation.com/resources/poultry-house-leakage-area-calculator-2018/

Физика:
  ELA (Equivalent Leakage Area) рассчитывается из уравнения Бернулли:
    Q = ELA * sqrt(2 * ΔP / ρ)
  Откуда:
    ELA = Q_m3s * sqrt(ρ / (2 * ΔP_Pa))

  где Q_m3s — расход вентилятора при измеренном давлении (м³/с),
  ρ = 1.184 кг/м³ — плотность воздуха при +20°C,
  ΔP_Pa — измеренное статическое давление, Па.

Поправка производительности вентилятора на давление теста:
  Вентилятор, указанный при 0.10" (25 Па), при тестовом давлении P_in (в дюймах):
    Q_corrected = Q_rated * (-2.57 * P_in² - 0.97 * P_in + 1.124)
  Это эмпирический полином UGA, откалиброванный на типичных туннельных вентиляторах.
"""

from __future__ import annotations
import math
from dataclasses import dataclass
from typing import Literal

# Физические константы
RHO_AIR_KG_M3 = 1.184          # Плотность воздуха при +20°C, кг/м³
IN_H2O_TO_PA  = 249.089         # 1 дюйм водяного столба = 249.089 Па (точное значение SI)

# Правило UGA: 750 CFM на ft² открытой площади впуска → в метрике:
# 750 CFM/ft² = 750 * 1.699 м³ч / (0.0929 м²) = 13 717 м³ч/м²
INLET_SPECIFIC_M3H_M2 = 13_717.0


TightnessClass = Literal["tight", "moderate", "leaky", "very_leaky"]


@dataclass
class LeakageInput:
    # Размеры птичника
    house_length_m: float          # Длина, м
    house_width_m:  float          # Ширина, м

    # Параметры теста герметичности
    fan_capacity_m3h: float        # Производительность тестового вентилятора при 25 Па (≈0.10"), м³/ч
    measured_pressure_pa: float    # Статическое давление при тесте, Па (рекомендация: 25-65 Па)

    # Параметры минимальной вентиляции (для расчёта доли инфильтрации)
    min_vent_fan_m3h: float        # Производительность вентилятора минвентиляции, м³/ч
    num_inlets: int                # Количество боковых приточных клапанов
    inlet_height_cm: float         # Максимальная высота открытия клапана, см
    inlet_length_cm: float         # Длина клапана, см


@dataclass
class LeakageResult:
    # --- Результаты теста герметичности ---
    fan_corrected_m3h: float       # Скорректированный расход вентилятора при тестовом давлении, м³/ч
    ela_m2: float                  # Суммарная площадь щелей/утечек (ELA), м²
    house_area_m2: float           # Площадь пола птичника, м²
    relative_leakage: float        # Относительная утечка, м² на 1000 м² пола (безразмерна)
    tightness_class: TightnessClass  # Класс герметичности
    tightness_label_ru: str        # Метка на русском

    # --- Анализ впускной системы при минвентиляции ---
    inlet_area_m2: float           # Суммарная площадь боковых клапанов при макс. открытии, м²
    required_total_area_m2: float  # Требуемая суммарная площадь впуска при 25 Па (правило UGA), м²
    net_inlet_area_m2: float       # Чистая требуемая площадь впуска (за вычетом щелей), м²
    pct_air_via_inlets: float      # Доля воздуха через клапаны (0–1)
    required_opening_cm: float     # Требуемая высота открытия клапана, см
    static_pressure_pa: float      # Введённое давление (для справки)


# Классификация по относительной утечке (м²/1000 м² = ft²/1000 ft² — безразмерна)
_TIGHTNESS_THRESHOLDS: list[tuple[float, TightnessClass, str]] = [
    (0.25, "tight",      "Герметичный ✅"),
    (0.50, "moderate",   "Умеренный 🟡"),
    (1.00, "leaky",      "Негерметичный ⚠️"),
    (9999, "very_leaky", "Критически негерметичный 🔴"),
]


def _classify(relative_leakage: float) -> tuple[TightnessClass, str]:
    for threshold, cls, label in _TIGHTNESS_THRESHOLDS:
        if relative_leakage < threshold:
            return cls, label
    return "very_leaky", "Критически негерметичный 🔴"


def _fan_correction(q_rated_m3h: float, pressure_pa: float) -> float:
    """
    Поправка производительности вентилятора на фактическое давление.

    Вентиляторы калиброваны при 25 Па (≈ 0.10"). При более высоком давлении
    производительность падает нелинейно. Полином UGA (P_in в дюймах вод. ст.):
        multiplier = -2.57 * P_in² - 0.97 * P_in + 1.124
    """
    p_in = pressure_pa / IN_H2O_TO_PA          # Па → дюймы
    multiplier = -2.57 * p_in**2 - 0.97 * p_in + 1.124
    multiplier = max(0.0, multiplier)            # Не может быть отрицательным
    return q_rated_m3h * multiplier


def calculate_leakage(inp: LeakageInput) -> LeakageResult:
    """Расчёт герметичности птичника."""

    # Площадь пола
    house_area_m2 = inp.house_length_m * inp.house_width_m

    # Скорректированный расход вентилятора при давлении теста
    q_corrected_m3h = _fan_correction(inp.fan_capacity_m3h, inp.measured_pressure_pa)
    q_corrected_m3s = q_corrected_m3h / 3600.0

    # ELA: уравнение Бернулли обращённое
    # Q = ELA * sqrt(2*P/rho) → ELA = Q * sqrt(rho/(2*P))
    ela_m2 = q_corrected_m3s * math.sqrt(RHO_AIR_KG_M3 / (2.0 * inp.measured_pressure_pa))

    # Относительная утечка (безразмерная — одинакова в имперской и метрической системах)
    relative_leakage = ela_m2 / (house_area_m2 / 1000.0)

    # Класс герметичности
    t_class, t_label = _classify(relative_leakage)

    # --- Анализ впускной системы ---
    # Суммарная площадь клапанов при максимальном открытии
    inlet_h_m  = inp.inlet_height_cm / 100.0
    inlet_l_m  = inp.inlet_length_cm / 100.0
    inlet_area_m2 = inlet_h_m * inlet_l_m * inp.num_inlets

    # Требуемая площадь для обеспечения вентиляции при 25 Па (правило 750 CFM/ft²)
    required_total_area_m2 = inp.min_vent_fan_m3h / INLET_SPECIFIC_M3H_M2

    # Чистая площадь впуска (всё что не покрывается щелями нужно обеспечить клапанами)
    net_inlet_area_m2 = max(0.0, required_total_area_m2 - ela_m2)

    # Доля воздуха через клапаны
    if required_total_area_m2 > 0:
        pct_air_via_inlets = min(1.0, net_inlet_area_m2 / required_total_area_m2)
    else:
        pct_air_via_inlets = 0.0

    # Требуемая высота открытия каждого клапана
    if inp.num_inlets > 0 and inlet_l_m > 0:
        required_opening_m = net_inlet_area_m2 / (inp.num_inlets * inlet_l_m)
    else:
        required_opening_m = 0.0
    required_opening_cm = required_opening_m * 100.0

    return LeakageResult(
        fan_corrected_m3h       = round(q_corrected_m3h, 0),
        ela_m2                  = round(ela_m2, 4),
        house_area_m2           = round(house_area_m2, 1),
        relative_leakage        = round(relative_leakage, 4),
        tightness_class         = t_class,
        tightness_label_ru      = t_label,
        inlet_area_m2           = round(inlet_area_m2, 4),
        required_total_area_m2  = round(required_total_area_m2, 4),
        net_inlet_area_m2       = round(net_inlet_area_m2, 4),
        pct_air_via_inlets      = round(pct_air_via_inlets, 4),
        required_opening_cm     = round(required_opening_cm, 1),
        static_pressure_pa      = inp.measured_pressure_pa,
    )
