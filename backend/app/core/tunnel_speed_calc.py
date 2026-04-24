"""
Калькулятор скорости воздуха и ощущаемой температуры в туннельном птичнике.

Источник 1 (геометрия, давление):
  UGA Extension (Michael Czarick & Brian Fairchild):
  tunnel_air_speedstatic_pressure_estimating_spreadsheet_v1.5.xlsx

Источник 2 (ощущаемая температура):
  Таблица «Ощущаемая температура в зависимости от скорости движения воздуха»
  (российский нормативный источник, птицеводство)
  Учитывает КОМБИНИРОВАННЫЙ эффект: тепловой индекс при 0 м/с + конвективное
  и испарительное охлаждение дыхательных путей при движении воздуха.

  ВАЖНО: Это не стандартное ветровое охлаждение по UGA (≈-1°F/100FPM).
  При 35°C и 50% RH:
    V=0.5 м/с → -2.8°C,  V=1.0 → -8.4°C,  V=2.5 → -12.8°C
  Значительно больше UGA-формулы из-за учёта испарительного охлаждения слизистых.

Физика:
  V = Q / A_cross  (скорость воздуха в туннеле, м/с)
  P_dyn = 0.5 × ρ × V²  (динамическое давление, Па)

THI (Temperature Humidity Index, Buffington 1981):
  THI = 0.8 × T_db + (RH/100) × (T_db − 14.4) + 46.4
  Пороги для бройлеров: <74 комфорт, 74–78 тревога, 79–83 опасность, >83 критично
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# ─────────────────────────────────────────────────
# Таблица ощущаемой температуры [°C]
# Структура: {(T_actual_c, rh_pct): {v_ms: T_effective_c}}
# Источник: российская нормативная таблица для птицеводства
# Температуры-ключи (реальные): 21.1, 23.9, 26.6, 29.4, 32.2, 35.0 °C
# Соответствие °F: 70, 75, 80, 85, 90, 95 — таблица изначально Fahrenheit, конвертирована
# ─────────────────────────────────────────────────
_EFF_TEMP_TABLE: dict[tuple[float, float], dict[float, float]] = {
    (35.0, 50): {0.0: 35.0, 0.5: 32.2, 1.0: 26.6, 1.5: 24.4, 2.0: 23.3, 2.5: 22.2},
    (35.0, 70): {0.0: 38.3, 0.5: 35.5, 1.0: 30.5, 1.5: 28.8, 2.0: 26.1, 2.5: 24.4},

    (32.2, 50): {0.0: 32.2, 0.5: 26.6, 1.0: 24.4, 1.5: 22.8, 2.0: 21.1, 2.5: 20.0},
    (32.2, 70): {0.0: 35.5, 0.5: 32.7, 1.0: 28.8, 1.5: 27.2, 2.0: 25.5, 2.5: 23.3},

    (29.4, 50): {0.0: 29.4, 0.5: 24.4, 1.0: 22.8, 1.5: 21.1, 2.0: 20.0, 2.5: 20.0},
    (29.4, 70): {0.0: 31.6, 0.5: 30.0, 1.0: 27.2, 1.5: 25.5, 2.0: 24.4, 2.5: 23.3},

    (26.6, 50): {0.0: 26.6, 0.5: 24.4, 1.0: 22.2, 1.5: 21.1, 2.0: 18.9, 2.5: 18.3},
    (26.6, 70): {0.0: 28.3, 0.5: 26.1, 1.0: 24.4, 1.5: 23.3, 2.0: 20.5, 2.5: 19.4},

    (23.9, 50): {0.0: 23.9, 0.5: 22.8, 1.0: 21.1, 1.5: 20.0, 2.0: 17.7, 2.5: 16.6},
    (23.9, 70): {0.0: 25.5, 0.5: 24.4, 1.0: 23.3, 1.5: 22.2, 2.0: 20.0, 2.5: 18.8},

    (21.1, 50): {0.0: 21.1, 0.5: 18.9, 1.0: 18.3, 1.5: 17.7, 2.0: 16.6, 2.5: 16.1},
    (21.1, 70): {0.0: 22.8, 0.5: 21.1, 1.0: 20.0, 1.5: 18.9, 2.0: 17.7, 2.5: 16.6},
}

# Отсортированные ключи для интерполяции
_T_KEYS  = sorted({t for t, _ in _EFF_TEMP_TABLE})     # [21.1, 23.9, 26.6, 29.4, 32.2, 35.0]
_RH_KEYS = sorted({r for _, r in _EFF_TEMP_TABLE})     # [50, 70]
_V_KEYS  = [0.0, 0.5, 1.0, 1.5, 2.0, 2.5]

# Плотность воздуха при +25°C, кг/м³
RHO_AIR_KG_M3 = 1.184

# THI-пороги для бройлеров
_THI_THRESHOLDS = [
    (74.0, "Комфорт ✅"),
    (78.0, "Тревога 🟡"),
    (83.0, "Опасность ⚠️"),
    (999,  "Критично 🔴"),
]

# Рекомендуемые скорости по возрасту (дней: v_min, v_max)
_SPEED_TARGETS = [
    (21,  1.5, 2.0),
    (35,  2.0, 2.5),
    (42,  2.5, 3.0),
    (999, 2.5, 3.5),
]


# ─────────────────────────────────────────────────
# Dataclasses
# ─────────────────────────────────────────────────

@dataclass
class TunnelSpeedInput:
    house_width_m:    float     # Ширина птичника, м
    tunnel_height_m:  float     # Высота свободного сечения туннеля (≈70–85% стены), м
    num_fans:         int       # Количество туннельных вентиляторов
    fan_capacity_m3h: float     # Производительность одного вентилятора при 0 Па, м³/ч
    t_outdoor_db_c:   float     # Температура сухого термометра, °C
    rh_outdoor_pct:   float     # Относительная влажность, %
    bird_age_days:    int       # Возраст птицы, дней
    inlet_pressure_pa: float = 10.0  # Статическое давление на входе (пэды/шторы), Па


@dataclass
class TunnelSpeedResult:
    cross_section_m2:       float
    total_airflow_m3h:      float
    air_velocity_ms:        float
    air_velocity_fpm:       float
    wind_chill_c:           float   # Разница: T_actual − T_effective
    effective_temp_c:       float   # Ощущаемая температура из таблицы
    thi_value:              float
    thi_status:             str
    dynamic_pressure_pa:    float
    total_pressure_pa:      float
    target_v_min_ms:        float
    target_v_max_ms:        float
    velocity_status:        str
    fans_needed_for_target: int
    status_label:           str


# ─────────────────────────────────────────────────
# Вспомогательные функции
# ─────────────────────────────────────────────────

def _lerp(a: float, b: float, t: float) -> float:
    """Линейная интерполяция: t=0 → a, t=1 → b."""
    return a + (b - a) * t


def _interp_v(speed_dict: dict[float, float], v: float) -> float:
    """Интерполяция по скорости внутри одного (T, RH)-сегмента."""
    v = max(0.0, min(v, _V_KEYS[-1]))      # зажать в диапазон таблицы
    keys = _V_KEYS

    for i in range(len(keys) - 1):
        v0, v1 = keys[i], keys[i + 1]
        if v <= v1:
            t = (v - v0) / (v1 - v0) if v1 > v0 else 0.0
            return _lerp(speed_dict[v0], speed_dict[v1], t)
    return speed_dict[keys[-1]]


def _effective_temperature(t_db: float, rh: float, v_ms: float) -> float:
    """
    Трилинейная интерполяция по таблице ощущаемой температуры.

    Порядок:
    1. Находим два соседних T-уровня и интерполируем по T
    2. Повторяем для двух соседних RH-уровней
    3. Интерполируем по RH между результатами шага 1 и 2
    """
    # Зажать T в диапазон таблицы
    t_c = max(_T_KEYS[0], min(t_db, _T_KEYS[-1]))
    rh_c = max(_RH_KEYS[0], min(rh, _RH_KEYS[-1]))

    # --- Шаг 1: интерполяция по T (при двух крайних RH) ---
    def interp_at_rh(rh_level: float) -> float:
        """Интерполяция по T для конкретного rh_level."""
        for i in range(len(_T_KEYS) - 1):
            t0, t1 = _T_KEYS[i], _T_KEYS[i + 1]
            if t_c <= t1:
                tt = (t_c - t0) / (t1 - t0)
                val0 = _interp_v(_EFF_TEMP_TABLE[(t0, rh_level)], v_ms)
                val1 = _interp_v(_EFF_TEMP_TABLE[(t1, rh_level)], v_ms)
                return _lerp(val0, val1, tt)
        return _interp_v(_EFF_TEMP_TABLE[(_T_KEYS[-1], rh_level)], v_ms)

    # --- Шаг 2: интерполяция по RH ---
    rh0, rh1 = _RH_KEYS[0], _RH_KEYS[-1]   # 50, 70
    val_rh0 = interp_at_rh(rh0)
    val_rh1 = interp_at_rh(rh1)
    rh_t = (rh_c - rh0) / (rh1 - rh0)
    return _lerp(val_rh0, val_rh1, rh_t)


def _calc_thi(t_db: float, rh: float) -> tuple[float, str]:
    """THI = 0.8 × T + (RH/100) × (T − 14.4) + 46.4  (Buffington, 1981)."""
    thi = 0.8 * t_db + (rh / 100.0) * (t_db - 14.4) + 46.4
    for threshold, label in _THI_THRESHOLDS:
        if thi < threshold:
            return round(thi, 1), label
    return round(thi, 1), "Критично 🔴"


def _target_speed(age_days: int) -> tuple[float, float]:
    for max_age, v_min, v_max in _SPEED_TARGETS:
        if age_days <= max_age:
            return v_min, v_max
    return 2.5, 3.5


# ─────────────────────────────────────────────────
# Основной расчёт
# ─────────────────────────────────────────────────

def calculate_tunnel_speed(inp: TunnelSpeedInput) -> TunnelSpeedResult:
    """Расчёт параметров туннельной вентиляции с таблицей ощущаемой температуры."""

    # Площадь сечения и скорость воздуха
    cross_section = inp.house_width_m * inp.tunnel_height_m
    total_m3h = inp.num_fans * inp.fan_capacity_m3h
    total_m3s = total_m3h / 3600.0
    v_ms = total_m3s / cross_section if cross_section > 0 else 0.0
    v_fpm = v_ms * 196.85

    # Ощущаемая температура из таблицы (трилинейная интерполяция)
    t_eff = _effective_temperature(inp.t_outdoor_db_c, inp.rh_outdoor_pct, v_ms)
    wind_chill = inp.t_outdoor_db_c - t_eff   # положительное = охлаждение

    # THI
    thi_val, thi_status = _calc_thi(inp.t_outdoor_db_c, inp.rh_outdoor_pct)

    # Давление
    p_dynamic = 0.5 * RHO_AIR_KG_M3 * v_ms ** 2
    p_total = p_dynamic + inp.inlet_pressure_pa

    # Рекомендации по скорости
    v_min_t, v_max_t = _target_speed(inp.bird_age_days)
    if v_ms < v_min_t * 0.8:
        velocity_status = f"Слишком низкая ({v_ms:.1f} м/с < {v_min_t:.1f} м/с) — мало охлаждения 🔴"
    elif v_ms < v_min_t:
        velocity_status = f"Ниже рекомендованной ({v_ms:.1f} м/с, цель ≥{v_min_t:.1f} м/с) 🟡"
    elif v_ms <= v_max_t:
        velocity_status = f"В норме ({v_ms:.1f} м/с, рек. {v_min_t:.1f}–{v_max_t:.1f} м/с) ✅"
    elif v_ms <= 4.0:
        velocity_status = f"Выше нормы ({v_ms:.1f} м/с > {v_max_t:.1f} м/с) — возможен дискомфорт 🟡"
    else:
        velocity_status = f"Слишком высокая ({v_ms:.1f} м/с) — птица не может стоять нормально ⚠️"

    # Вентиляторов для нижней границы целевой скорости
    q_need_m3s = v_min_t * cross_section
    q_per_fan = inp.fan_capacity_m3h / 3600.0 if inp.fan_capacity_m3h > 0 else 1
    fans_needed = math.ceil(q_need_m3s / q_per_fan)

    # Общая оценка
    in_range = v_min_t <= v_ms <= v_max_t
    if in_range:
        if thi_val < 74:
            status_label = "Система в норме, тепловой стресс минимален ✅"
        elif thi_val < 78:
            status_label = "Скорость хорошая, но THI повышен — следите за птицей 🟡"
        else:
            status_label = "Скорость ОК, но высокий THI — рассмотрите испарительное охлаждение ⚠️"
    elif v_ms < v_min_t:
        status_label = "Скорость воздуха недостаточна — добавьте вентиляторы 🔴"
    elif v_ms > 4.0:
        status_label = "Скорость слишком высока — риск стресса от движения воздуха ⚠️"
    else:
        status_label = "Скорость выше нормы для данного возраста — возможен стресс 🟡"

    return TunnelSpeedResult(
        cross_section_m2       = round(cross_section, 2),
        total_airflow_m3h      = round(total_m3h, 0),
        air_velocity_ms        = round(v_ms, 2),
        air_velocity_fpm       = round(v_fpm, 0),
        wind_chill_c           = round(wind_chill, 1),
        effective_temp_c       = round(t_eff, 1),
        thi_value              = thi_val,
        thi_status             = thi_status,
        dynamic_pressure_pa    = round(p_dynamic, 1),
        total_pressure_pa      = round(p_total, 1),
        target_v_min_ms        = v_min_t,
        target_v_max_ms        = v_max_t,
        velocity_status        = velocity_status,
        fans_needed_for_target = fans_needed,
        status_label           = status_label,
    )
