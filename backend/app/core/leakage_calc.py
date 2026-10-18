"""
Калькулятор герметичности (воздухопроницаемости) птичника.

Основан на методике UGA (University of Georgia, Michael Czarick):
  https://www.poultryventilation.com/resources/poultry-house-leakage-area-calculator-2018/

Физика:
  ELA (Equivalent Leakage Area) рассчитывается из уравнения Бернулли:
    Q = ELA * sqrt(2 * ΔP / ρ)
  Откуда:
    ELA = Q_m3s * sqrt(ρ / (2 * ΔP_Pa))

  Коэффициент расхода Cd здесь сознательно = 1, и ρ = 1.184 — константа: ровно так
  считает калькулятор UGA (poultry_house_air_leakage_calculator_2018.xlsx, ячейка
  L2: =I2*(J2/(2*K2))^0.5, J2 = 1.184), и его пороги классов привязаны к этой
  величине. С Cd = 0.61 (ELA по ASHRAE/LBL) площадь вышла бы в 1/0.61 раза больше
  и классы UGA к ней уже не применимы. Это условная площадь, а не площадь щелей.

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


@dataclass
class LeakageResult:
    fan_corrected_m3h: float       # Скорректированный расход вентилятора при тестовом давлении, м³/ч
    ela_m2: float                  # Суммарная площадь щелей/утечек (ELA), м²
    house_area_m2: float           # Площадь пола птичника, м²
    relative_leakage: float        # Относительная утечка, м² на 1000 м² пола (безразмерна)
    tightness_class: TightnessClass  # Класс герметичности — текст подставляет клиент (tightness_<class>)
    static_pressure_pa: float      # Введённое давление (для справки)


# Классификация по относительной утечке (м²/1000 м² = ft²/1000 ft² — безразмерна).
#
# Пороги UGA (Czarick, Fairchild), сверено с первоисточниками 2026-10-19:
#   0.48 и 0.65 — «Poultry House Leakage Estimating Spreadsheet 2014»: классы
#     < 0.48 / 0.48–0.65 / 0.65–1.2 / > 1.2, и у каждого физический смысл — доля
#     воздуха минвентиляции, входящая через клапаны, а не щели: > 70 % / 50–70 % /
#     12–50 % / меньше. Цель UGA — не меньше 50 %, то есть граница 0.65.
#   1.0 — «Poultry411 App — Poultry House Tightness Calculator» (2018, новее):
#     «above 1 is viewed as very poor»; там же 0.45 названо excellent, 0.78 — marginal,
#     что ложится в эти классы.
# Прежние 0.25 / 0.50 / 1.00 источника не имели: дом с 0.35 («excellent» у UGA)
# получал «умеренно».
_TIGHTNESS_THRESHOLDS: list[tuple[float, TightnessClass]] = [
    (0.48, "tight"),
    (0.65, "moderate"),
    (1.00, "leaky"),
]


def _classify(relative_leakage: float) -> TightnessClass:
    for threshold, cls in _TIGHTNESS_THRESHOLDS:
        if relative_leakage < threshold:
            return cls
    return "very_leaky"


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
    t_class = _classify(relative_leakage)

    return LeakageResult(
        fan_corrected_m3h  = round(q_corrected_m3h, 0),
        ela_m2             = round(ela_m2, 4),
        house_area_m2      = round(house_area_m2, 1),
        relative_leakage   = round(relative_leakage, 4),
        tightness_class    = t_class,
        static_pressure_pa = inp.measured_pressure_pa,
    )
