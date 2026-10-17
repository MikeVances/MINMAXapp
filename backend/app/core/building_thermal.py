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
import logging
import math
import os
from dataclasses import dataclass, asdict, field
from typing import Optional

from .json_store import atomic_write_json
from .paths import data_path

logger = logging.getLogger(__name__)


THERMAL_CONFIG_PATH = str(data_path("THERMAL_CONFIG_JSON", "data/thermal_config.json"))


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
    house_id: Optional[str] = None           # ID корпуса из main-page tabs (e.g. "1", "A-2")
    building: Optional[BuildingDimensions] = None
    heater: Optional[HeaterConfig] = None
    calibration: Optional[CalibrationTest] = None


AIR_CP_J_PER_KG_K = 1006.0   # удельная теплоёмкость сухого воздуха


def air_density_kg_m3(t_c: float) -> float:
    """Плотность воздуха при 101.325 кПа: ρ = 353.05 / T[K]."""
    return 353.05 / (t_c + 273.15)


def calculate_ua_coefficient(
    volume_m3: float,
    t_initial: float,
    t_final: float,
    t_outside: float,
    time_minutes: float
) -> float:
    """
    УСЛОВНЫЙ коэффициент теплопотерь по тесту остывания пустого корпуса, Вт/°C.

    Остывание по Ньютону: C · dT/dt = −UA · (T − T_нар) → экспонента, откуда
        UA = C / t · ln(ΔT₀ / ΔT₁)
    (раньше бралась средняя арифметическая ΔT — систематическая ошибка тем больше,
    чем сильнее остыл корпус).

    Оговорка, из-за которой UA «условный»: C — теплоёмкость только ВОЗДУХА.
    В реальном корпусе тепло отдают и пол, и стены, и результат зависит от длины
    теста: в первые минуты воздух выдувается инфильтрацией (UA завышается в разы),
    в долгом тесте пол и стены подогревают воздух (UA занижается).
    Надёжнее калибровка по установившемуся режиму горелок.

    Raises:
        ValueError: температура не выше наружной или не снижалась за время теста
    """
    delta_t_initial = t_initial - t_outside
    delta_t_final = t_final - t_outside

    if delta_t_initial <= 0 or delta_t_final <= 0:
        raise ValueError("Начальная и конечная температуры должны быть выше наружной")
    if t_final >= t_initial:
        # Раньше здесь был abs(): рост температуры давал «нормальный» положительный UA
        raise ValueError("Температура за время теста не снизилась — тест остывания некорректен")
    if time_minutes <= 0:
        raise ValueError("Длительность теста должна быть больше нуля")

    # Теплоёмкость воздуха корпуса при средней температуре теста
    t_mean = (t_initial + t_final) / 2.0
    thermal_capacity = volume_m3 * air_density_kg_m3(t_mean) * AIR_CP_J_PER_KG_K   # Дж/°C

    return thermal_capacity / (time_minutes * 60.0) * math.log(delta_t_initial / delta_t_final)


def heater_air_demand(heater_power_kw: float, duty_cycle: float, heater_type: str) -> float:
    """
    Стехиометрический воздух на горение (для справки/отображения).

    CH₄ + 2O₂ → CO₂ + 2H₂O
    1 м³ газа требует 9.5 м³ воздуха (2 м³ O₂ при 21% объёмных).

    Для расчёта Qmin используй heater_co2_dilution_m3h() — CO₂ dilution является
    определяющим ограничением и превышает combustion air в ~40 раз.
    """
    if heater_type != "gas_open":
        return 0.0

    gas_flow = (heater_power_kw / 100.0) * 10.0 * duty_cycle  # м³/ч газа (LHV ≈ 10 кВт/м³)
    return gas_flow * 9.5


def heater_co2_dilution_m3h(
    heater_power_kw: float,
    duty_cycle: float,
    heater_type: str,
    safety_factor: float = 1.5,
) -> float:
    """
    Дополнительный Qmin для поддержания CO₂ < 3000 ppm при работе горелок открытого горения.

    При открытом горении продукты сгорания (CO₂, H₂O) выходят в воздух птичника:
      CH₄ + 2O₂ → CO₂ + 2H₂O
      1 м³ природного газа (LHV ≈ 10 кВт/м³) → 1000 л CO₂

    Разбавление: ΔQmin = V_CO₂ [л/ч] / ΔCO₂ [л/м³] × safety
    ΔCO₂ = 2600 ppm = 2.6 л/м³  (лимит 3000 − фон 400 ppm)

    Это определяющий вентиляционный constraint, в ~40 раз превышающий combustion air.
    """
    if heater_type != "gas_open":
        return 0.0

    gas_flow_m3h = (heater_power_kw / 100.0) * 10.0 * duty_cycle  # м³ газа/ч
    co2_lh = gas_flow_m3h * 1000.0                                  # л CO₂/ч

    return (co2_lh / 2.6) * safety_factor


# ─────────────────────────────────────────────────────────────────────────────
# Полный тепловой баланс птичника
# ─────────────────────────────────────────────────────────────────────────────

# Параметры воздуха (стандарт +15°C)
def ventilation_heat_w(q_m3h: float, t_inside_c: float, t_outside_c: float) -> float:
    """
    Тепло, уносимое вентиляцией при нагреве приточного воздуха до T_in, Вт.

    Расход q — объём ВНУТРЕННЕГО воздуха: вытяжные вентиляторы перекачивают воздух
    корпуса, их паспорт и уставки — в м³/ч при его температуре. Поэтому ρ берётся
    при T_in. Одна функция для Qmax, duty cycle горелок и анализа теплового баланса
    (раньше было три варианта: ρ при T_нар в двух местах и фиксированные 1.2·1005).
    """
    dt = t_inside_c - t_outside_c
    return q_m3h / 3600.0 * air_density_kg_m3(t_inside_c) * AIR_CP_J_PER_KG_K * dt




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

    # Потери с вентиляционным воздухом (Q_min × ρcp × ΔT), dt ≥ 0
    q_vent_w = ventilation_heat_w(q_min_m3h, t_inside_target, t_outside) if dt > 0 else 0.0
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

        return ThermalConfig(
            house_id=data.get("house_id"),
            building=building,
            heater=heater,
            calibration=calibration,
        )

    except Exception:
        # Калибровка UA потеряна — расчёт горелок пойдёт без неё, это должно быть видно в логе
        logger.exception("thermal_config не читается: %s — используются значения по умолчанию", path)
        return ThermalConfig()


def save_thermal_config(config: ThermalConfig, path: str = THERMAL_CONFIG_PATH) -> None:
    """Сохраняет конфигурацию теплотехнических параметров в JSON"""
    data = {}
    if config.house_id is not None:
        data["house_id"] = config.house_id
    if config.building:
        data["building"] = asdict(config.building)
    if config.heater:
        data["heater"] = asdict(config.heater)
    if config.calibration:
        data["calibration"] = asdict(config.calibration)

    atomic_write_json(path, data)
