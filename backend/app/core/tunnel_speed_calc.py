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

Индекс теплового стресса для БРОЙЛЕРОВ — THVI (Tao & Xin 2003,
Transactions of the ASAE 46(2):491–497, doi:10.13031/2013.12971):
  THVI = (0.85 × T_db + 0.15 × T_wb) × V^−0.058
  Получен на бройлерах Ross 2.8 кг при V = 0.2–1.2 м/с. Пороги (экспозиция 90 мин,
  по росту температуры тела): <35 норма, 35–38 тревога, 38–40 опасность, >40 критично.
  Раньше здесь стоял THI NRC 1971 (для КРС, ошибочно подписан Buffington 1981)
  с порогами для коров 74/79/84.

Рабочая точка вентиляторов:
  Паспорт «при 0 Па» завышает расход: в туннеле вентилятор работает против давления
  впуска и сечения. Если задана производительность при 25 Па, характеристика
  линеаризуется q = q₀ − s·P, сопротивление системы P = c·Q², и рабочая точка —
  их пересечение. Без второй точки скорость считается по паспорту 0 Па с пометкой.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .evap_cooling_calc import _wet_bulb_stull
from .building_thermal import air_temperature_rise_c

# ─────────────────────────────────────────────────
# Таблица ощущаемой температуры [°C]
# Структура: {(T_actual_c, rh_pct): {v_ms: T_effective_c}}
# Источник: документ «Ощущаемая температура в зависимости от скорости движения воздуха.doc»
# (лежит в корне проекта, вне git) — значения совпадают до десятых, но первоисточника
# в документе нет (аудит 2026-10-18). Как таблица применяется по T — см. _wind_cooling_c
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

# Пороги THVI (Tao & Xin 2003, экспозиция 90 мин), °C. < threshold → категория
# Коды, не текст: переводит клиент (i18n: thvi_<code>)
_THVI_THRESHOLDS = [
    (35.0, "normal"),
    (38.0, "alert"),
    (40.0, "danger"),
    (999,  "critical"),
]
# Диапазон скоростей, на котором получена формула THVI: за ним эффект скорости
# не экстраполируем (выше 1.2 м/с охлаждение берём как при 1.2 — в безопасную сторону)
_THVI_V_RANGE = (0.2, 1.2)

# Давление второй точки паспорта вентилятора, Па (0.1" вод. ст. ≈ 25 Па — типовая точка BESS)
FAN_RATING_POINT_PA = 25.0

# Рекомендуемые скорости по возрасту (дней: v_min, v_max)
_SPEED_TARGETS = [
    (21,  1.5, 2.0),
    (35,  2.0, 2.5),
    (42,  2.5, 3.0),
    (999, 2.5, 3.5),
]

# Верхний предел комфортной температуры для бройлеров по возрасту, °C
# Источник: Aviagen Broiler Management Guide 2019
_COMFORT_TARGETS = [
    (7,   32.0),
    (14,  29.0),
    (21,  27.0),
    (28,  26.0),
    (35,  25.0),
    (999, 24.0),
]

# Практический максимум T_outdoor для птицеводства в таблице — если лимит выше, считаем "без ограничений"
_T_LIMIT_CAP = 42.0


# ─────────────────────────────────────────────────
# Dataclasses
# ─────────────────────────────────────────────────

CD_INLET      = 0.62  # Коэффициент расхода для шторных/сетчатых клапанов
CD_INLET_OPEN = 0.90  # Открытый торец (лёгкое сжатие струи + сетка)

@dataclass
class TunnelSpeedInput:
    house_width_m:    float     # Ширина птичника, м
    tunnel_height_m:  float     # Высота свободного сечения туннеля (≈70–85% стены), м
    num_fans:         int       # Количество туннельных вентиляторов
    fan_capacity_m3h: float     # Производительность одного вентилятора при 0 Па, м³/ч
    t_outdoor_db_c:   float     # Температура сухого термометра, °C
    rh_outdoor_pct:   float     # Относительная влажность, %
    bird_age_days:    int       # Возраст птицы, дней
    # Геометрия впускной системы (заменяет inlet_pressure_pa)
    num_inlets:    int   = 1    # Количество приточных секций/проёмов, шт
    inlet_width_m:  float = 0.0 # Ширина одного проёма, м (0 = авто: ширина птичника)
    inlet_height_m: float = 0.0 # Высота одного проёма, м (0 = авто: высота туннеля)
    # Производительность одного вентилятора при 25 Па, м³/ч (0 = неизвестна)
    fan_capacity_25pa_m3h: float = 0.0
    # Поголовье и масса: для нагрева воздуха вдоль корпуса (0 = не учитывать)
    num_birds:      int   = 0
    bird_weight_kg: float = 0.0


# Допустимая разница температур между торцами корпуса в тоннельном режиме, °C
# (Cobb Broiler Guide 2021, с. 75: ≤ 2.8 °C в самый жаркий день при птице убойного возраста;
# то же значение — Aviagen «Основы вентиляции» 2019, с. 16)
MAX_END_TO_END_RISE_C = 2.8


@dataclass
class TunnelSpeedResult:
    cross_section_m2:       float
    total_airflow_m3h:      float
    air_velocity_ms:        float
    air_velocity_fpm:       float
    wind_chill_c:           float   # Разница: T_actual − T_effective
    effective_temp_c:       float   # Ощущаемая температура из таблицы
    thi_value:              float
    thi_status:             str     # normal | alert | danger | critical
    dynamic_pressure_pa:    float
    inlet_area_m2:          float   # Суммарная площадь впускных проёмов
    inlet_velocity_ms:      float   # Скорость воздуха через впуск
    inlet_sp_pa:            float   # Статическое давление на впуске (из геометрии)
    inlet_status:           str     # good | normal | high | critical
    total_pressure_pa:      float   # Суммарное давление = дин. + впуск
    target_v_min_ms:        float
    target_v_max_ms:        float
    velocity_status:        str     # too_low | below_target | ok | above_target | too_high
    fans_needed_for_target: int
    # Общая оценка: код для перевода на клиенте и уровень для цвета бейджа.
    # Статусы отдаются кодами, а не фразами: сервер не знает языка пользователя,
    # а клиент раньше угадывал цвет по эмодзи внутри строки.
    status_code:            str     # ok | needs_cooling | thvi_alert | thvi_high | too_slow | too_fast | above_range
    status_level:           str     # ok | warn | danger
    # Тепловой вердикт: туннель vs испарительное охлаждение
    bird_comfort_target_c:    float  # Целевая T комфорта по возрасту птицы
    tunnel_sufficient:        bool   # Туннель справляется при текущих условиях
    t_outdoor_tunnel_limit_c: float  # Макс. T_нар при которой туннель достаточен
    temp_margin_c:            float  # Запас: T_цель − T_ощущ (>0 = запас есть)
    # Откуда расход: "operating_point" (с учётом давления) или "rated_0pa" (паспорт, завышен)
    velocity_basis:           str = "rated_0pa"
    fan_operating_m3h:        float = 0.0   # расход одного вентилятора в рабочей точке
    # Нагрев воздуха вдоль корпуса (0 — поголовье не задано)
    air_temp_rise_c:          float = 0.0
    t_fan_end_c:              float = 0.0   # T воздуха у вентиляторов — по ней ощущаемая и THVI
    end_to_end_rise_excessive: bool = False # > 2.8 °C (Cobb): нужно больше воздуха


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


# Температурные опоры охлаждения ветром (аудит 2026-10-18). Таблица выше растила
# эффект с температурой (2.5 м/с: −5.0 °C при 21 °C, −12.8 °C при 35 °C) и линейно
# экстраполировала его выше 35 °C — «тоннель достаточен до 38.6 °C». Физически
# конвекция пропорциональна (T_поверхности − T_воздуха) и гаснет у температуры птицы.
#   29.4 °C (85 °F) — UGA (Czarick): 85 °F при 500 fpm ощущаются как 72 °F; на графике
#                     Czarick кривые 85, 90 и 95 °F дают ОДИНАКОВОЕ охлаждение
#                     (extension.umd.edu, «Tunnel ventilation management», слайд 16) →
#                     выше 85 °F эффект не растёт, держим значение таблицы при 29.4 °C;
#   35.0 °C (95 °F) — нижняя граница температуры поверхности бройлера;
#   37.8 °C (100 °F) — верхняя: «воздух в диапазоне 95–100 °F практически останавливает
#                     теплоотдачу» (Univ. of Kentucky, AFS гл. 9) → охлаждение ветром 0.
# Ограничение (честно): при 29.4 °C таблица даёт 8.3–9.4 °C охлаждения при 2.5 м/с,
# UGA — ≈ 7.2 °C, Ross 2025 — ≈ 5.6 °C. Источник таблицы не установлен; это
# оптимистичнее на 1–4 °C и требует таблицы с проверяемым источником.
_T_WIND_PLATEAU_C   = 29.4
_T_WIND_FADE_FROM_C = 35.0
_T_BIRD_SURFACE_C   = 37.8


def _table_value(t_c: float, rh_level: float, v_ms: float) -> float:
    """Значение таблицы при T внутри её диапазона (без экстраполяции)."""
    t_c = min(max(t_c, _T_KEYS[0]), _T_KEYS[-1])
    for i in range(len(_T_KEYS) - 1):
        t0, t1 = _T_KEYS[i], _T_KEYS[i + 1]
        if t_c <= t1:
            tt = (t_c - t0) / (t1 - t0)
            return _lerp(_interp_v(_EFF_TEMP_TABLE[(t0, rh_level)], v_ms),
                         _interp_v(_EFF_TEMP_TABLE[(t1, rh_level)], v_ms), tt)
    return _interp_v(_EFF_TEMP_TABLE[(_T_KEYS[-1], rh_level)], v_ms)


def _wind_cooling_c(t_db: float, rh_level: float, v_ms: float) -> float:
    """
    Охлаждение ветром, °C (≥ 0): насколько поток ниже ощущения в неподвижном воздухе.

    До 29.4 °C — по таблице; 29.4…35 °C — плато на значении 29.4 °C (UGA);
    35…37.8 °C — линейно до нуля (поверхность птицы); выше — 0. Ниже 21.1 °C —
    значение края таблицы: прежняя экстраполяция давала отрицательное
    «охлаждение», то есть ветер якобы грел птицу.
    """
    t_ref = min(max(t_db, _T_KEYS[0]), _T_WIND_PLATEAU_C)
    cooling = max(0.0, _table_value(t_ref, rh_level, 0.0) - _table_value(t_ref, rh_level, v_ms))
    if t_db <= _T_WIND_FADE_FROM_C:
        return cooling
    if t_db >= _T_BIRD_SURFACE_C:
        return 0.0
    return cooling * (_T_BIRD_SURFACE_C - t_db) / (_T_BIRD_SURFACE_C - _T_WIND_FADE_FROM_C)


def _effective_temperature(t_db: float, rh: float, v_ms: float) -> float:
    """
    Ощущаемая температура = T + поправка влажности (неподвижный воздух) − охлаждение ветром.

    Поправка влажности — строка v = 0 таблицы (при RH 70 % ощущается теплее
    термометра: 35 °C → 38.3 °C); вне диапазона T таблицы берём её значение на
    краю: в строке v = 0 ощущаемая T растёт с T с наклоном ≈ 1, то есть поправка
    почти постоянна. Охлаждение ветром — _wind_cooling_c. RH зажимается в [50, 70].
    """
    rh_c = max(_RH_KEYS[0], min(rh, _RH_KEYS[-1]))

    def at_rh(rh_level: float) -> float:
        t_tab = min(max(t_db, _T_KEYS[0]), _T_KEYS[-1])
        humidity_shift = _table_value(t_tab, rh_level, 0.0) - t_tab
        return t_db + humidity_shift - _wind_cooling_c(t_db, rh_level, v_ms)

    rh0, rh1 = _RH_KEYS[0], _RH_KEYS[-1]
    return _lerp(at_rh(rh0), at_rh(rh1), (rh_c - rh0) / (rh1 - rh0))


def _calc_thvi(t_db: float, rh: float, v_ms: float) -> tuple[float, str]:
    """THVI = (0.85·T_db + 0.15·T_wb) · V^−0.058 (Tao & Xin 2003), V в пределах исследования."""
    t_wb = _wet_bulb_stull(t_db, rh)
    v = min(max(v_ms, _THVI_V_RANGE[0]), _THVI_V_RANGE[1])
    thvi = (0.85 * t_db + 0.15 * t_wb) * v ** -0.058
    for threshold, label in _THVI_THRESHOLDS:
        if thvi < threshold:
            return round(thvi, 1), label
    return round(thvi, 1), "critical"


def _fan_operating_flow_m3s(
    q0_m3s: float, q25_m3s: float, num_fans: int, resistance_pa_per_m3s2: float
) -> float:
    """
    Расход ОДНОГО вентилятора в рабочей точке, м³/с.

    Характеристика вентилятора (линейно по двум точкам паспорта): q = q₀ − s·P,
      s = (q₀ − q₂₅) / 25 Па.
    Сопротивление системы: P = c · (N·q)².
    Подстановка: s·c·N²·q² + q − q₀ = 0 → q = (−1 + √(1 + 4·s·c·N²·q₀)) / (2·s·c·N²).
    """
    s = (q0_m3s - q25_m3s) / FAN_RATING_POINT_PA
    a = s * resistance_pa_per_m3s2 * num_fans ** 2
    if a <= 0:
        return q0_m3s
    return (-1.0 + math.sqrt(1.0 + 4.0 * a * q0_m3s)) / (2.0 * a)


def _target_speed(age_days: int) -> tuple[float, float]:
    for max_age, v_min, v_max in _SPEED_TARGETS:
        if age_days <= max_age:
            return v_min, v_max
    return 2.5, 3.5


def _bird_comfort_target(age_days: int) -> float:
    """Верхний предел комфортной температуры для бройлера данного возраста, °C."""
    for max_age, target in _COMFORT_TARGETS:
        if age_days <= max_age:
            return target
    return 24.0


def _find_tunnel_temp_limit(rh_pct: float, v_ms: float, t_target_c: float) -> float:
    """
    Максимальная наружная температура, при которой туннельная вентиляция
    обеспечивает ощущаемую температуру ≤ t_target_c.

    Сканирует T_outdoor от 15 до 45°C с шагом 0.5°C.
    effective_temp монотонно растёт с T_outdoor → находим точку пересечения
    через линейную интерполяцию между двумя соседними шагами.
    """
    T_STEP = 0.5
    t_prev = 15.0
    eff_prev = _effective_temperature(t_prev, rh_pct, v_ms)

    t = t_prev + T_STEP
    while t <= 45.0:
        eff = _effective_temperature(t, rh_pct, v_ms)
        if eff >= t_target_c:
            # Линейная интерполяция для точности ±0.1°C
            if eff > eff_prev:
                frac = (t_target_c - eff_prev) / (eff - eff_prev)
                return round(t_prev + frac * T_STEP, 1)
            return round(t_prev, 1)
        t_prev = t
        eff_prev = eff
        t = round(t + T_STEP, 1)

    return _T_LIMIT_CAP  # Лимит выше практического диапазона


# ─────────────────────────────────────────────────
# Основной расчёт
# ─────────────────────────────────────────────────

def calculate_tunnel_speed(inp: TunnelSpeedInput) -> TunnelSpeedResult:
    """Расчёт параметров туннельной вентиляции с таблицей ощущаемой температуры."""

    cross_section = inp.house_width_m * inp.tunnel_height_m

    # Геометрия впускных проёмов
    # 0 → авто: открытый торец = ширина птичника × высота сечения туннеля
    is_open_end  = (inp.inlet_width_m <= 0 and inp.inlet_height_m <= 0)
    eff_inlet_w  = inp.inlet_width_m  if inp.inlet_width_m  > 0 else inp.house_width_m
    eff_inlet_h  = inp.inlet_height_m if inp.inlet_height_m > 0 else inp.tunnel_height_m
    inlet_area   = inp.num_inlets * eff_inlet_w * eff_inlet_h
    if inlet_area <= 0:
        inlet_area = cross_section

    # Открытый торец: Cd≈0.90 (лёгкое сжатие + сетка)
    # Шторные/панельные клапаны: Cd=0.62
    cd = CD_INLET_OPEN if is_open_end else CD_INLET

    # Сопротивление системы P = c·Q² [Па при Q в м³/с]: динамическое давление в
    # сечении + потеря на впуске (модель UGA)
    resistance = RHO_AIR_KG_M3 / 2.0 * (
        (1.0 / cross_section ** 2 if cross_section > 0 else 0.0) + 1.0 / (inlet_area * cd) ** 2
    )

    # Расход вентиляторов: рабочая точка, если известна вторая точка паспорта
    q0_m3s = inp.fan_capacity_m3h / 3600.0
    q25_m3s = inp.fan_capacity_25pa_m3h / 3600.0
    if 0.0 < q25_m3s < q0_m3s:
        q_fan_m3s = _fan_operating_flow_m3s(q0_m3s, q25_m3s, inp.num_fans, resistance)
        velocity_basis = "operating_point"
    else:
        q_fan_m3s = q0_m3s
        velocity_basis = "rated_0pa"

    total_m3s = inp.num_fans * q_fan_m3s
    total_m3h = total_m3s * 3600.0
    v_ms = total_m3s / cross_section if cross_section > 0 else 0.0
    v_fpm = v_ms * 196.85

    # Худшее место корпуса — у вентиляторов: воздух нагрет теплом птицы по пути.
    # RH оставляем как на входе (нагретый воздух суше — оценка в безопасную сторону)
    air_rise = air_temperature_rise_c(inp.num_birds, inp.bird_weight_kg, inp.t_outdoor_db_c, total_m3s)
    t_fan_end = inp.t_outdoor_db_c + air_rise

    # Ощущаемая температура у вентиляторов (таблица, см. _effective_temperature)
    t_eff = _effective_temperature(t_fan_end, inp.rh_outdoor_pct, v_ms)
    wind_chill = t_fan_end - t_eff   # положительное = охлаждение

    # THVI по T и RH у вентиляторов: скорость входит в индекс сама
    thi_val, thi_status = _calc_thvi(t_fan_end, inp.rh_outdoor_pct, v_ms)

    # Динамическое давление в туннеле
    p_dynamic = 0.5 * RHO_AIR_KG_M3 * v_ms ** 2

    inlet_v    = total_m3s / inlet_area
    inlet_sp   = RHO_AIR_KG_M3 * (inlet_v / cd) ** 2 / 2

    # Пороги UGA: 400/600/800 FPM → 2.0/3.0/4.0 м/с
    if inlet_v < 2.0:
        inlet_status = "good"
    elif inlet_v < 3.0:
        inlet_status = "normal"
    elif inlet_v < 4.0:
        inlet_status = "high"
    else:
        inlet_status = "critical"

    p_total = p_dynamic + inlet_sp

    # Рекомендации по скорости
    v_min_t, v_max_t = _target_speed(inp.bird_age_days)
    if v_ms < v_min_t * 0.8:
        velocity_status = "too_low"
    elif v_ms < v_min_t:
        velocity_status = "below_target"
    elif v_ms <= v_max_t:
        velocity_status = "ok"
    elif v_ms <= 4.0:
        velocity_status = "above_target"
    else:
        velocity_status = "too_high"

    # Вентиляторов для нижней границы целевой скорости
    q_need_m3s = v_min_t * cross_section
    # В рабочей точке, если она известна (паспорт 0 Па занизил бы потребность)
    q_per_fan = q_fan_m3s if q_fan_m3s > 0 else 1
    fans_needed = math.ceil(q_need_m3s / q_per_fan)

    # Тепловой вердикт (нужен до формирования status_code)
    comfort_target = _bird_comfort_target(inp.bird_age_days)
    temp_margin    = comfort_target - t_eff
    # Туннель достаточен только если ОБА условия выполнены:
    # 1. Скорость воздуха >= минимальной проектной (обеспечивает ветровое охлаждение)
    # 2. Ощущаемая T <= целевой комфортной T для данного возраста
    tunnel_ok      = (v_ms >= v_min_t) and (t_eff <= comfort_target)
    # Предел — по наружной T: у вентиляторов воздух теплее на air_rise
    t_limit        = round(_find_tunnel_temp_limit(inp.rh_outdoor_pct, v_ms, comfort_target) - air_rise, 1)

    # Общая оценка — согласована с tunnel_ok, чтобы бейдж не противоречил карточке
    in_range = v_min_t <= v_ms <= v_max_t
    if in_range:
        if not tunnel_ok:
            # Скорость в норме, но ощущаемая T превышает целевую — нужно охлаждение
            status_code, status_level = "needs_cooling", "danger"
        elif thi_val < _THVI_THRESHOLDS[0][0]:
            status_code, status_level = "ok", "ok"
        elif thi_val < _THVI_THRESHOLDS[1][0]:
            status_code, status_level = "thvi_alert", "warn"
        else:
            status_code, status_level = "thvi_high", "danger"
    elif v_ms < v_min_t:
        status_code, status_level = "too_slow", "danger"
    elif v_ms > 4.0:
        status_code, status_level = "too_fast", "danger"
    else:
        status_code, status_level = "above_range", "warn"

    return TunnelSpeedResult(
        cross_section_m2          = round(cross_section, 2),
        total_airflow_m3h         = round(total_m3h, 0),
        air_velocity_ms           = round(v_ms, 2),
        air_velocity_fpm          = round(v_fpm, 0),
        wind_chill_c              = round(wind_chill, 1),
        effective_temp_c          = round(t_eff, 1),
        thi_value                 = thi_val,
        thi_status                = thi_status,
        dynamic_pressure_pa       = round(p_dynamic, 1),
        inlet_area_m2             = round(inlet_area, 2),
        inlet_velocity_ms         = round(inlet_v, 2),
        inlet_sp_pa               = round(inlet_sp, 1),
        inlet_status              = inlet_status,
        total_pressure_pa         = round(p_total, 1),
        target_v_min_ms           = v_min_t,
        target_v_max_ms           = v_max_t,
        velocity_status           = velocity_status,
        fans_needed_for_target    = fans_needed,
        status_code               = status_code,
        status_level              = status_level,
        bird_comfort_target_c     = comfort_target,
        tunnel_sufficient         = tunnel_ok,
        t_outdoor_tunnel_limit_c  = t_limit,
        temp_margin_c             = round(temp_margin, 1),
        velocity_basis            = velocity_basis,
        fan_operating_m3h         = round(q_fan_m3s * 3600.0, 0),
        air_temp_rise_c           = round(air_rise, 1),
        t_fan_end_c               = round(t_fan_end, 1),
        end_to_end_rise_excessive = air_rise > MAX_END_TO_END_RISE_C,
    )
