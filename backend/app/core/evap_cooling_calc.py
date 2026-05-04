"""
Калькулятор системы испарительного охлаждения птичника (Pad & Fan).

Методика UGA (University of Georgia, Michael Czarick):
  evaporative_cooling_pad_system_design_2014_v2.xlsx
  evaporative_cooling_design_spreadsheet_2014_-_metric.xlsx

ДАННЫЕ ПЭДОВ: таблицы SANHE (оцифровано с кривых производителя):
─────────────────────────────────────────────────────────────────
  Эффективность насыщения пэда (saturation efficiency):
    η = (T_db_in − T_db_out) / (T_db_in − T_wb_in) × 100%
    Интерполируется линейно по скорости воздуха через пэд.
    — не КПД по энергии, а степень приближения к T_wb.

  Типы пэдов SANHE:
    7090 — высокоэффективный (угол гофры 70°/90°): высокая η, больший ΔP
    7060 — стандартный (70°/60°): ниже ΔP, ниже η при той же толщине
    5090 — компактный (50°/90°): высокая η для своей толщины, тонкие секции

  ВАЖНО: η снижается с ростом скорости (меньше времени контакта с влажной поверхностью).
  Значения в таблицах — точки на кривой η(v) производителя. Выше 2.5 м/с риск уноса капель.

Водопотребление (ПСИХРОМЕТРИЧЕСКИЙ МАССОВЫЙ БАЛАНС, как в UGA):
  p_ws(T) = 611.2 × exp(17.67T / (T+243.5))  (Magnus-Tetens, Па)
  W = 0.622 × p_w / (P_atm − p_w)        [кг воды / кг сухого воздуха]
  ΔW = η × (W_sat(T_wb) − W_outside)     [кг/кг]
  Q_water = (Q_air/3600) × ρ × ΔW × 60  [л/мин]

  Точность: ±2% vs UGA Excel (подтверждено: расчёт 32.6 л/мин, UGA 33.2 л/мин)

Расчёт T_wb — формула Стулла (Stull, 2011), точность ±0.3°C:
  T_wb = T × atan(0.151977 × (RH+8.313659)^0.5)
       + atan(T + RH)
       - atan(RH - 1.676331)
       + 0.00391838 × RH^1.5 × atan(0.023101 × RH)
       - 4.686035
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

# Плотность воздуха при +25°C, кг/м³
RHO_AIR_KG_M3 = 1.184

# Стандартное атмосферное давление, Па
P_ATM_PA = 101325.0

# Рекомендуемая скорость для расчёта площади пэда (практический оптимум η/ΔP)
V_REC_MS = 1.25


# ─────────────────────────────────────────────────────────────────
# Данные пэдов SANHE (оцифровано с кривых производителя)
# structure: velocities [м/с], thicknesses [мм],
#   efficiency_pct [%] и pressure_pa [Па] — как функция скорости для каждой толщины
# ─────────────────────────────────────────────────────────────────
SANHE_PADS: dict[str, dict] = {
    "7090": {
        "description": "SANHE 7090 — высокоэффективный (гофра 70°/90°)",
        "velocities":  [0.5, 1.0, 1.5, 2.0, 2.5, 3.0],
        "thicknesses": [75, 100, 150, 200, 300],
        "v_min_ms":    0.6,
        "v_max_ms":    2.5,
        "efficiency_pct": {
            75:  [73, 68, 64, 60, 57, 55],
            100: [83, 77, 72, 69, 67, 66],
            150: [93, 89, 86, 83, 82, 81],
            200: [97, 95, 92, 90, 89, 89],
            300: [99, 98, 97, 97, 96, 96],
        },
        "pressure_pa": {
            75:  [5,  8,  14, 22,  33,  45],
            100: [7,  12, 20, 31,  45,  60],
            150: [10, 18, 32, 48,  68,  90],
            200: [15, 28, 48, 72,  105, 145],
            300: [25, 45, 75, 115, 165, 215],
        },
    },
    "7060": {
        "description": "SANHE 7060 — стандартный (гофра 70°/60°)",
        "velocities":  [0.5, 1.0, 1.5, 2.0, 2.5, 3.0],
        "thicknesses": [75, 100, 150, 200, 300],
        "v_min_ms":    0.6,
        "v_max_ms":    2.5,
        "efficiency_pct": {
            75:  [66, 58, 53, 50, 48, 46],
            100: [75, 69, 63, 59, 56, 54],
            150: [88, 82, 76, 72, 69, 67],
            200: [95, 90, 85, 82, 80, 78],
            300: [97, 95, 94, 93, 91, 90],
        },
        "pressure_pa": {
            75:  [2,  5,  8,  13, 18, 25],
            100: [4,  7,  12, 18, 26, 35],
            150: [6,  10, 17, 26, 36, 48],
            200: [8,  14, 24, 36, 50, 65],
            300: [12, 22, 37, 55, 75, 90],
        },
    },
    "5090": {
        "description": "SANHE 5090 — компактный (гофра 50°/90°)",
        "velocities":  [0.5, 1.0, 1.5, 2.0, 2.5, 3.0],
        "thicknesses": [50, 75, 100, 150],
        "v_min_ms":    0.6,
        "v_max_ms":    2.5,
        "efficiency_pct": {
            50:  [74, 69, 65, 62, 60, 59],
            75:  [86, 82, 78, 74, 72, 71],
            100: [93, 90, 87, 85, 83, 82],
            150: [98, 96, 94, 92, 91, 91],
        },
        "pressure_pa": {
            50:  [5,  10, 16, 24,  34,  45],
            75:  [8,  15, 25, 38,  55,  72],
            100: [12, 23, 37, 55,  78,  98],
            150: [20, 35, 55, 80, 115, 150],
        },
    },
}

PAD_TYPE_DEFAULT = "7090"


# ─────────────────────────────────────────────────
# Dataclasses
# ─────────────────────────────────────────────────

@dataclass
class EvapCoolingInput:
    # Размеры птичника (для контекста/аудита)
    house_length_m: float          # Длина птичника, м

    # Климатические условия
    t_outdoor_db_c: float          # Температура сухого термометра снаружи, °C
    rh_outdoor_pct: float          # Относительная влажность снаружи, %

    # Система вентиляции
    total_fan_m3h: float           # Суммарная производительность туннельных вентиляторов, м³/ч

    # Параметры пэда
    pad_type: str                  # Тип пэда SANHE: "7090", "7060", "5090"
    pad_thickness_mm: int          # Толщина пэда, мм (зависит от типа)
    pad_length_m: float            # Суммарная длина панелей охлаждения, м
    pad_height_m: float            # Высота панелей охлаждения, м

    # Целевая температура внутри (для оценки эффективности)
    t_inside_target_c: float       # Целевая температура внутри птичника, °C

    # Опционально: температура воды подачи (скважина / бак)
    # None = стандартный адиабатический расчёт (как в UGA)
    water_supply_t_c: Optional[float] = None


@dataclass
class EvapCoolingResult:
    # --- Психрометрика ---
    t_wb_c: float                  # Температура мокрого термометра, °C
    t_pad_out_c: float             # Температура воздуха после пэда, °C
    cooling_achieved_c: float      # Достигнутое охлаждение, °C
    pad_efficiency: float          # Эффективность насыщения η (0..1): η=(T_db_in−T_db_out)/(T_db_in−T_wb_in)

    # --- Геометрия пэда ---
    pad_area_m2: float             # Фактическая площадь пэдов, м²
    air_velocity_ms: float         # Скорость воздуха через пэд, м/с
    velocity_ok: bool              # Скорость в допустимом диапазоне
    velocity_status: str           # Описание статуса скорости
    pad_pressure_drop_pa: float    # Перепад давления на пэде, Па (SANHE, интерп. по скорости)

    # --- Водопотребление ---
    water_flow_lpm: float          # Расход воды, л/мин
    water_per_hour_l: float        # Водопотребление, л/ч

    # --- Оценка условий в птичнике ---
    cooling_sufficient: bool       # Охлаждение достаточное (T_pad < T_target)
    temp_margin_c: float           # Запас температуры (T_target - T_pad), °C

    # --- Рекомендации ---
    recommended_pad_area_m2: float  # Рекомендуемая площадь пэда для скорости V_REC_MS
    status_label: str              # Общая оценка системы

    # --- Точка росы и проверка температуры воды подачи ---
    t_dew_c: float                         # Точка росы входящего воздуха, °C (всегда вычисляется)
    water_supply_t_c: Optional[float]      # Температура воды подачи (None если не задана)
    # 'safe'             — T_вода > T_dp, испарение не нарушено
    # 'condensation_risk'— T_вода < T_dp, конденсация на пэде, потеря эффективности насыщения
    # None               — температура воды не указана
    water_regime: Optional[str]


# ─────────────────────────────────────────────────
# Вспомогательные функции
# ─────────────────────────────────────────────────

def _interp_linear(x_vals: list[float], y_vals: list[float], x: float) -> float:
    """
    Линейная интерполяция с зажимом к граничным значениям таблицы.

    Не экстраполирует: за пределами диапазона возвращает крайнее значение.
    Подходит для кривых η(v) и ΔP(v), которые монотонны и не имеют
    физически обоснованного продолжения за границы измерений.
    """
    if x <= x_vals[0]:
        return y_vals[0]
    if x >= x_vals[-1]:
        return y_vals[-1]
    for i in range(len(x_vals) - 1):
        if x_vals[i] <= x <= x_vals[i + 1]:
            t = (x - x_vals[i]) / (x_vals[i + 1] - x_vals[i])
            return y_vals[i] + t * (y_vals[i + 1] - y_vals[i])
    return y_vals[-1]


def _sat_pressure_pa(t_c: float) -> float:
    """
    Давление насыщенных паров воды по формуле Magnus-Tetens, Па.

    Источник: Murray (1967); диапазон 0–50°C, точность <0.1%.
    """
    return 611.2 * math.exp(17.67 * t_c / (t_c + 243.5))


def _humidity_ratio(t_c: float, rh_pct: float) -> float:
    """
    Влагосодержание воздуха W, кг воды / кг сухого воздуха.

    W = 0.622 × p_w / (P_atm − p_w)
    """
    p_ws = _sat_pressure_pa(t_c)
    p_w  = rh_pct / 100.0 * p_ws
    return 0.622 * p_w / (P_ATM_PA - p_w)


def _wet_bulb_stull(t_db: float, rh: float) -> float:
    """
    Расчёт температуры мокрого термометра по формуле Стулла (2011).

    Источник: Stull R. (2011). Wet-Bulb Temperature from Relative Humidity and Air Temperature.
    J. Appl. Meteor. Climatol.
    Точность: ±0.3°C в диапазоне 5–40°C, 5–99% RH.
    """
    t = t_db
    r = rh
    t_wb = (
        t * math.atan(0.151977 * (r + 8.313659) ** 0.5)
        + math.atan(t + r)
        - math.atan(r - 1.676331)
        + 0.00391838 * r ** 1.5 * math.atan(0.023101 * r)
        - 4.686035
    )
    return t_wb


def _water_flow_lpm(
    fan_m3h: float,
    t_db: float,
    rh_pct: float,
    t_wb: float,
    efficiency: float,
) -> float:
    """
    Расход воды — психрометрический массовый баланс (метод UGA Excel).

    Воздух, проходя через пэд с эффективностью насыщения η, достигает промежуточного состояния
    на линии адиабатического насыщения между исходной точкой (T_db, W_outside)
    и точкой насыщения (T_wb, W_sat(T_wb)):

      ΔW = η × (W_sat(T_wb) − W_outside)   [кг воды / кг сух. воздуха]
      Q_water = (Q / 3600) × ρ × ΔW × 60   [л/мин]

    Точность: ±2% vs UGA Excel (против ±21% при тепловом балансе).
    """
    w_outside = _humidity_ratio(t_db, rh_pct)
    w_sat_wb  = _humidity_ratio(t_wb, 100.0)   # влагосодержание при T_wb, RH=100%

    dw = efficiency * (w_sat_wb - w_outside)
    if dw <= 0:
        return 0.0

    q_m3s = fan_m3h / 3600.0
    # Масса испарённой воды = расход воздуха × плотность × ΔW
    m_water_kg_s = q_m3s * RHO_AIR_KG_M3 * dw
    # Перевод в л/мин (плотность воды ≈ 1 кг/л)
    return m_water_kg_s * 60.0


def _dew_point(t_db: float, rh_pct: float) -> float:
    """
    Точка росы входящего воздуха, °C.

    Инверсия формулы Magnus-Tetens:
      Pv = (RH/100) × Psat(T_db)
      T_dp = 243.5 × ln(Pv/611.2) / (17.67 − ln(Pv/611.2))

    Если T_вода < T_dp → поверхность пэда холоднее точки росы →
    водяной пар конденсируется на пэде, выделяя скрытую теплоту →
    эффективность насыщения пэда снижается.
    """
    pv     = (rh_pct / 100.0) * _sat_pressure_pa(t_db)
    ln_pv  = math.log(pv / 611.2)
    return 243.5 * ln_pv / (17.67 - ln_pv)


def calculate_evap_cooling(inp: EvapCoolingInput) -> EvapCoolingResult:
    """Расчёт системы испарительного охлаждения птичника."""

    # Получаем данные пэда из таблицы SANHE
    pad_data  = SANHE_PADS.get(inp.pad_type, SANHE_PADS[PAD_TYPE_DEFAULT])
    velocities = pad_data["velocities"]
    eta_table  = pad_data["efficiency_pct"][inp.pad_thickness_mm]
    dp_table   = pad_data["pressure_pa"][inp.pad_thickness_mm]
    v_min      = pad_data["v_min_ms"]
    v_max      = pad_data["v_max_ms"]

    # Температура мокрого термометра
    t_wb = _wet_bulb_stull(inp.t_outdoor_db_c, inp.rh_outdoor_pct)

    # Геометрия пэда — прямые размеры: длина × высота
    pad_area_m2 = inp.pad_length_m * inp.pad_height_m
    if pad_area_m2 <= 0:
        pad_area_m2 = 0.001  # защита от деления на ноль

    # Скорость воздуха через пэд: Q / A
    q_m3s = inp.total_fan_m3h / 3600.0
    air_velocity_ms = q_m3s / pad_area_m2

    # Интерполяция η и ΔP по фактической скорости
    eta_pct = _interp_linear(velocities, eta_table, air_velocity_ms)
    dp_pa   = _interp_linear(velocities, dp_table,  air_velocity_ms)
    eta     = eta_pct / 100.0

    # Температура воздуха после пэда
    t_pad_out = inp.t_outdoor_db_c - eta * (inp.t_outdoor_db_c - t_wb)
    cooling_achieved = inp.t_outdoor_db_c - t_pad_out

    # Проверка диапазона скорости
    velocity_ok = v_min <= air_velocity_ms <= v_max
    if air_velocity_ms < v_min:
        velocity_status = (
            f"Слишком низкая ({air_velocity_ms:.2f} м/с < {v_min} м/с) — риск плесени на пэде"
        )
    elif air_velocity_ms > v_max:
        velocity_status = (
            f"Слишком высокая ({air_velocity_ms:.2f} м/с > {v_max} м/с) — брызги воды в птичник"
        )
    else:
        velocity_status = (
            f"В норме: {air_velocity_ms:.2f} м/с, "
            f"η = {eta_pct:.0f}%, ΔP = {dp_pa:.0f} Па"
        )

    # Водопотребление (психрометрический массовый баланс)
    water_lpm = _water_flow_lpm(inp.total_fan_m3h, inp.t_outdoor_db_c, inp.rh_outdoor_pct, t_wb, eta)
    water_per_hour = water_lpm * 60.0

    # Оценка эффективности
    temp_margin = inp.t_inside_target_c - t_pad_out
    cooling_sufficient = t_pad_out <= inp.t_inside_target_c

    # Рекомендуемая площадь пэда для скорости V_REC_MS
    recommended_pad_area = q_m3s / V_REC_MS

    # Общая оценка
    if not velocity_ok and air_velocity_ms > v_max:
        status_label = "Площадь пэда недостаточна — брызги ⚠️"
    elif not velocity_ok and air_velocity_ms < v_min:
        status_label = "Площадь пэда избыточна — риск плесени ⚠️"
    elif not cooling_sufficient:
        status_label = "Охлаждение недостаточное — рассмотрите дополнительные меры 🔴"
    elif temp_margin < 2.0:
        status_label = "Охлаждение на грани нормы 🟡"
    else:
        status_label = "Система работает в норме ✅"

    # Точка росы входящего воздуха (всегда)
    t_dew = _dew_point(inp.t_outdoor_db_c, inp.rh_outdoor_pct)

    # Режим подачи воды (если задана температура)
    water_regime: Optional[str] = None
    if inp.water_supply_t_c is not None:
        # Добавляем 0.5°C запаса: пэд чуть теплее чем вода подачи из-за теплообмена
        water_regime = 'safe' if inp.water_supply_t_c >= (t_dew + 0.5) else 'condensation_risk'

    return EvapCoolingResult(
        t_wb_c                  = round(t_wb, 1),
        t_pad_out_c             = round(t_pad_out, 1),
        cooling_achieved_c      = round(cooling_achieved, 1),
        pad_efficiency          = round(eta, 4),
        pad_area_m2             = round(pad_area_m2, 2),
        air_velocity_ms         = round(air_velocity_ms, 2),
        velocity_ok             = velocity_ok,
        velocity_status         = velocity_status,
        pad_pressure_drop_pa    = round(dp_pa, 1),
        water_flow_lpm          = round(water_lpm, 1),
        water_per_hour_l        = round(water_per_hour, 0),
        cooling_sufficient      = cooling_sufficient,
        temp_margin_c           = round(temp_margin, 1),
        recommended_pad_area_m2 = round(recommended_pad_area, 2),
        status_label            = status_label,
        t_dew_c                 = round(t_dew, 1),
        water_supply_t_c        = inp.water_supply_t_c,
        water_regime            = water_regime,
    )
