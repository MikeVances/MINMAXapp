"""
Модуль для расчёта теплового баланса птичника и работы газовых обогревателей.

Тепловой баланс птичника (уравнение установившегося теплообмена):
═══════════════════════════════════════════════════════════════════════════

  Q_heater + Q_birds  =  Q_walls + Q_vent

  Q_heater — тепло от обогревателей [Вт]
  Q_birds  — метаболическое тепло птицы [Вт]   ← часто пренебрегают, а зря
  Q_walls  — теплопотери через ограждения = UA × (T_in − T_out)  [Вт]
  Q_vent   — теплопотери с вентиляционным воздухом               [Вт]
           = Q_min [м³/с] × ρ × cp × (T_in − T_out)

Метаболическое тепло птицы (CIGR Handbook Vol. II):
  q_total [Вт/гол] = 10.62 × W^0.75   (W — живая масса, кг)
  Разделение: ~65% чувствительное тепло (sensible), ~35% скрытое (latent)
  q_sensible [Вт/гол] = 6.90 × W^0.75

Порядок масштаба:
  30 000 бройлеров в 2 кг → 6.90 × 1.68 × 30 000 ≈ 348 кВт
  Это часто полностью покрывает теплопотери без обогревателей (с ≈3 нед.)

Калибровочный тест UA (метод охлаждения):
  Выполнять в ПУСТОМ птичнике: тепловая масса птиц и помёта полностью
  искажает UA, если проводить с заселённым стадом.
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, asdict, field
from typing import Optional


THERMAL_CONFIG_PATH = os.getenv("THERMAL_CONFIG_JSON", "data/thermal_config.json")


@dataclass
class BuildingDimensions:
    """Размеры помещения"""
    length_m: float  # длина, м
    width_m: float   # ширина, м
    height_m: float  # высота, м

    @property
    def volume_m3(self) -> float:
        """Объем помещения, м³"""
        return self.length_m * self.width_m * self.height_m

    @property
    def floor_area_m2(self) -> float:
        """Площадь пола, м²"""
        return self.length_m * self.width_m


@dataclass
class HeaterConfig:
    """Конфигурация обогревателей"""
    heater_type: str  # "gas_open" (газовые открытого горения) или "electric"
    total_power_kw: float  # общая тепловая мощность, кВт


@dataclass
class CalibrationTest:
    """Результаты теста охлаждения для калибровки"""
    t_initial_c: float      # начальная температура, °C
    t_final_c: float        # конечная температура через time_minutes, °C
    t_outside_c: float      # температура снаружи, °C
    time_minutes: float     # время теста, минуты
    ua_coefficient: float   # рассчитанный коэффициент теплопотерь, Вт/°C


@dataclass
class ThermalConfig:
    """Полная конфигурация теплотехнических параметров"""
    building: Optional[BuildingDimensions] = None
    heater: Optional[HeaterConfig] = None
    calibration: Optional[CalibrationTest] = None


def calculate_ua_coefficient(
    volume_m3: float,
    t_initial: float,
    t_final: float,
    t_outside: float,
    time_minutes: float
) -> float:
    """
    Рассчитывает коэффициент теплопотерь по методу охлаждения.

    Физика: Q_loss = UA × ΔT = C × dT/dt
    где UA - коэффициент теплопередачи помещения (Вт/°C)

    Args:
        volume_m3: Объем помещения, м³
        t_initial: Начальная температура внутри, °C
        t_final: Температура через time_minutes, °C
        t_outside: Температура снаружи, °C
        time_minutes: Время теста, минуты (обычно 5-10 мин)

    Returns:
        Коэффициент теплопотерь UA, Вт/°C
    """
    # Тепловая емкость воздуха в помещении
    air_density = 1.2  # кг/м³ при 20°C
    air_cp = 1005  # Дж/(кг·°C)
    thermal_capacity = volume_m3 * air_density * air_cp  # Дж/°C

    # Разница температур в начале и конце теста
    delta_t_initial = t_initial - t_outside
    delta_t_final = t_final - t_outside

    if delta_t_initial <= 0 or delta_t_final <= 0:
        raise ValueError("Начальная и конечная температуры должны быть выше наружной")

    # Средняя скорость охлаждения
    time_seconds = time_minutes * 60
    cooling_rate = (t_initial - t_final) / time_seconds  # °C/с

    # Средняя разница температур (логарифмическое среднее более точно, но для простоты берем арифметическое)
    delta_t_avg = (delta_t_initial + delta_t_final) / 2

    # Коэффициент теплопотерь (Вт/°C)
    # Q_loss = UA × ΔT, где Q_loss = C × dT/dt
    ua_coefficient = (thermal_capacity * cooling_rate) / delta_t_avg

    return abs(ua_coefficient)


def calculate_heater_duty_cycle(
    ua_coefficient: float,
    t_inside_target: float,
    t_outside: float,
    heater_power_kw: float
) -> float:
    """
    Рассчитывает коэффициент загрузки обогревателей (долю времени работы).

    Args:
        ua_coefficient: Коэффициент теплопотерь, Вт/°C
        t_inside_target: Целевая температура внутри, °C
        t_outside: Температура снаружи, °C
        heater_power_kw: Мощность обогревателей, кВт

    Returns:
        Коэффициент загрузки (0..1), где 1 = 100% времени работы
    """
    if t_inside_target <= t_outside:
        # Обогрев не нужен
        return 0.0

    # Теплопотери при целевой температуре
    heat_loss_w = ua_coefficient * (t_inside_target - t_outside)

    # Коэффициент загрузки
    heater_power_w = heater_power_kw * 1000

    if heater_power_w <= 0:
        return 0.0

    duty_cycle = heat_loss_w / heater_power_w

    # Ограничить 0..1
    return min(max(duty_cycle, 0.0), 1.0)


def heater_air_demand(heater_power_kw: float, duty_cycle: float, heater_type: str) -> float:
    """
    Рассчитывает дополнительный воздухообмен для газовых обогревателей.

    Стехиометрия сгорания природного газа (метан CH₄):
    CH₄ + 2O₂ → CO₂ + 2H₂O

    1 м³ газа + 9.5 м³ воздуха (для обеспечения 2 м³ O₂ при 21% в воздухе)

    Args:
        heater_power_kw: Тепловая мощность обогревателей, кВт
        duty_cycle: Коэффициент загрузки (0..1), доля времени работы
        heater_type: Тип обогревателей ("gas_open" или "electric")

    Returns:
        Дополнительный воздухообмен для горения, м³/ч
    """
    if heater_type != "gas_open":
        # Электрические обогреватели не требуют воздуха для горения
        return 0.0

    # Расход природного газа
    gas_per_100kw = 10.0  # м³/ч природного газа на 100 кВт тепловой мощности
    air_per_m3_gas = 9.5  # м³ воздуха на 1 м³ газа для полного сгорания

    # С учетом коэффициента загрузки
    gas_flow = (heater_power_kw / 100.0) * gas_per_100kw * duty_cycle  # м³/ч
    air_needed = gas_flow * air_per_m3_gas  # м³/ч

    return air_needed


# ─────────────────────────────────────────────────────────────────────────────
# Полный тепловой баланс птичника
# ─────────────────────────────────────────────────────────────────────────────

# Параметры воздуха (стандарт +15°C)
_RHO_CP = 1.2 * 1005 / 3600   # Вт·ч/(м³·°C) → Вт/(м³/ч·°C) = 0.335 Вт/(м³/ч·°C)


@dataclass
class HeatBalance:
    """Результат расчёта полного теплового баланса птичника."""
    # Потери тепла
    q_walls_kw:         float   # через ограждения: UA × ΔT
    q_ventilation_kw:   float   # с вентиляционным воздухом: Q_min × 0.335 × ΔT
    q_total_loss_kw:    float   # суммарные потери

    # Приходная часть (не от обогревателей)
    q_birds_kw:         float   # метаболическое чувствительное тепло птицы
    q_bird_per_bird_w:  float   # тепло одной птицы, Вт

    # Баланс
    q_heater_required_kw: float     # сколько нужно от обогревателей (≥ 0)
    heater_covers_need:   bool      # мощность обогревателей достаточна
    duty_cycle:           float     # коэффициент загрузки (0..1)
    duty_cycle_pct:       float     # %

    # Газовое сжигание (только для gas_open)
    combustion_air_m3h:   float     # воздух для горения, м³/ч

    # Диагностика
    bird_heat_fraction:   float     # доля потребности, покрытая птицей (может >1)
    status_label:         str       # текстовая оценка


def bird_sensible_heat_w(bird_weight_kg: float) -> float:
    """
    Чувствительное тепло одной птицы, Вт.

    Формула CIGR Handbook Vol. II (Livestock Housing):
      Q_total = 10.62 × W^0.75  [Вт/гол]
      Q_sensible ≈ 65% от Q_total при температурах 18–30°C

    Где W — живая масса, кг. Показатель 0.75 отражает закон площади поверхности тела.
    """
    if bird_weight_kg <= 0:
        return 0.0
    return 6.90 * (bird_weight_kg ** 0.75)


def calculate_heat_balance(
    ua_coefficient:   float,    # Коэффициент теплопотерь здания, Вт/°C
    q_min_m3h:        float,    # Минимальный воздухообмен, м³/ч
    t_inside_target:  float,    # Целевая температура внутри, °C
    t_outside:        float,    # Температура снаружи, °C
    num_birds:        int,      # Количество птицы, гол
    bird_weight_kg:   float,    # Средняя живая масса птицы, кг
    heater_power_kw:  float,    # Суммарная мощность обогревателей, кВт (0 = нет)
    heater_type:      str = "gas_open",  # "gas_open" или "electric"
) -> HeatBalance:
    """
    Полный тепловой баланс птичника с учётом метаболического тепла птицы.

    Уравнение баланса:
      Q_heater = Q_walls + Q_ventilation − Q_birds
                 (неотрицательно — обогреватели не охлаждают)
    """
    dt = max(t_inside_target - t_outside, 0.0)   # разница температур

    # Потери через ограждения (UA × ΔT)
    q_walls_w = ua_coefficient * dt
    q_walls_kw = q_walls_w / 1000.0

    # Потери с вентиляционным воздухом (Q_min × ρcp × ΔT)
    # _RHO_CP = 0.335 Вт/(м³/ч·°C)
    q_vent_w = q_min_m3h * _RHO_CP * dt
    q_vent_kw = q_vent_w / 1000.0

    q_total_loss_kw = q_walls_kw + q_vent_kw

    # Метаболическое тепло птицы
    q_per_bird_w = bird_sensible_heat_w(bird_weight_kg)
    q_birds_kw = (num_birds * q_per_bird_w) / 1000.0

    # Потребность в тепле от обогревателей
    q_need_kw = max(0.0, q_total_loss_kw - q_birds_kw)

    # Коэффициент покрытия птицей
    bird_fraction = q_birds_kw / q_total_loss_kw if q_total_loss_kw > 0 else 0.0

    # Duty cycle и воздух для горения
    if heater_power_kw > 0 and q_need_kw > 0:
        duty_cycle = min(q_need_kw / heater_power_kw, 1.0)
    else:
        duty_cycle = 0.0

    covers = (heater_power_kw >= q_need_kw) if q_need_kw > 0 else True
    combustion_air = heater_air_demand(heater_power_kw, duty_cycle, heater_type)

    # Текстовая оценка
    if dt <= 0:
        status = "Обогрев не требуется (снаружи теплее) ✅"
    elif q_need_kw == 0:
        status = f"Птица выделяет достаточно тепла — обогреватели не нужны ✅ (птицы: +{q_birds_kw:.0f} кВт)"
    elif not covers:
        deficit = q_need_kw - heater_power_kw
        status = f"Мощности недостаточно! Дефицит {deficit:.1f} кВт — добавьте обогреватели ⚠️"
    elif duty_cycle >= 0.9:
        status = f"Обогреватели работают на пределе ({duty_cycle*100:.0f}%) — рекомендуется резерв 🟡"
    elif duty_cycle >= 0.5:
        status = f"Умеренная загрузка ({duty_cycle*100:.0f}%) — система в норме ✅"
    else:
        status = f"Лёгкая загрузка ({duty_cycle*100:.0f}%) — мощность с запасом ✅"

    return HeatBalance(
        q_walls_kw            = round(q_walls_kw, 2),
        q_ventilation_kw      = round(q_vent_kw, 2),
        q_total_loss_kw       = round(q_total_loss_kw, 2),
        q_birds_kw            = round(q_birds_kw, 2),
        q_bird_per_bird_w     = round(q_per_bird_w, 2),
        q_heater_required_kw  = round(q_need_kw, 2),
        heater_covers_need    = covers,
        duty_cycle            = round(duty_cycle, 4),
        duty_cycle_pct        = round(duty_cycle * 100, 1),
        combustion_air_m3h    = round(combustion_air, 1),
        bird_heat_fraction    = round(bird_fraction, 4),
        status_label          = status,
    )


def load_thermal_config(path: str = THERMAL_CONFIG_PATH) -> ThermalConfig:
    """Загружает конфигурацию теплотехнических параметров из JSON"""
    if not os.path.exists(path):
        return ThermalConfig()

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        building = None
        if "building" in data and data["building"]:
            building = BuildingDimensions(**data["building"])

        heater = None
        if "heater" in data and data["heater"]:
            heater = HeaterConfig(**data["heater"])

        calibration = None
        if "calibration" in data and data["calibration"]:
            calibration = CalibrationTest(**data["calibration"])

        return ThermalConfig(building=building, heater=heater, calibration=calibration)

    except Exception:
        return ThermalConfig()


def save_thermal_config(config: ThermalConfig, path: str = THERMAL_CONFIG_PATH) -> None:
    """Сохраняет конфигурацию теплотехнических параметров в JSON"""
    os.makedirs(os.path.dirname(path), exist_ok=True)

    data = {}
    if config.building:
        data["building"] = asdict(config.building)
    if config.heater:
        data["heater"] = asdict(config.heater)
    if config.calibration:
        data["calibration"] = asdict(config.calibration)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
