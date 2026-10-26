"""
Уставка температуры в корпусе по методике производителя кросса.

Почему методика своя у каждого кросса, а не одна таблица Ross для всех: производители
задают уставку РАЗНЫМИ способами, и разница — не в сотых долях (сверка 2026-10-20):

  Aviagen (Ross 308/708, Arbor Acres) — по МАССЕ и RH, Ross Broiler Handbook 2025
      табл. 2.5 (Mitchell). Значения лежат в профиле, сдвиг по RH — apparent_temp.
  Cobb 500 — Cobb Broiler Management Guide 2021 §5.2 (с. 40): до 14-го дня по
      ВОЗРАСТУ и RH, дальше — по ПЛОТНОСТИ ПОСАДКИ кг/м² (28 кг/м² → 22 °C …
      42+ → 14 °C): под плотной птицей тепло накапливается быстрее.
  Hubbard Efficiency Plus — Broiler Guide V-2026-09, прил. 1 (с. 10): только по
      ВОЗРАСТУ («whole house heating»), без поправок на RH и плотность.

  Индейка (2026-10-26) — Aviagen Turkeys CL23 табл. 5 и Hybrid CMG с. 56: только по
      ВОЗРАСТУ, нижней границей диапазона (решение владельца), без поправки на RH —
      ни один из двух производителей её не даёт.

Возрастные таблицы Cobb (до 14-го дня) и Hubbard записаны в самих профилях
(data/growth_profiles/builtin) — здесь только то, что от возраста не выводится:
плотность Cobb и сдвиг по RH. Методику объявляет поле source.climate.method
встроенного профиля; у пользовательского профиля температура его собственная,
методику производителя к ней не применяем.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .apparent_temp import rh_temperature_shift
from .growth_profiles import GrowthPoint, GrowthProfile


# ─── Коды методик ────────────────────────────────────────────────────────────

ROSS = "mitchell_by_weight"
COBB = "cobb_rh_density"
HUBBARD = "hubbard_by_age"
TURKEY_AVIAGEN = "aviagen_turkey_by_age"
TURKEY_HYBRID = "hybrid_turkey_by_age"

# Код методики конкретного дня (уходит в ответ расчёта и в выбор источника)
DAY_ROSS = "mitchell_by_weight"
DAY_PROFILE = "custom_profile"
DAY_HUBBARD = "hubbard_by_age"
TURKEY_AVIAGEN = "aviagen_turkey_by_age"
TURKEY_HYBRID = "hybrid_turkey_by_age"
DAY_COBB_AGE = "cobb_by_age_rh"
DAY_COBB_DENSITY = "cobb_by_density"
DAY_COBB_FALLBACK = "cobb_fallback_ross"
DAY_TURKEY_AVIAGEN = TURKEY_AVIAGEN
DAY_TURKEY_HYBRID = TURKEY_HYBRID
# Свой профиль индейки: температура пользователя без поправки по RH — поправка
# Ross табл. 2.5 построена по массе бройлера (до ~3 кг), у индюка в 20 кг её нет
DAY_TURKEY_PROFILE = "custom_turkey_profile"

# Метка справочника /sources для каждой методики дня
SOURCE_BY_DAY_METHOD = {
    DAY_ROSS: "ross_2025_t2_5",
    # Свой профиль: температура пользователя, но сдвиг по RH — Ross табл. 2.5
    DAY_PROFILE: "ross_2025_t2_5",
    DAY_HUBBARD: "hubbard_2026_app1",
    DAY_COBB_AGE: "cobb_2021_5_2",
    DAY_COBB_DENSITY: "cobb_2021_5_2",
    # Плотность не известна — после 14-го дня значения профиля, это Ross
    DAY_COBB_FALLBACK: "ross_2025_t2_5",
    DAY_TURKEY_AVIAGEN: "aviagen_turkey_cl23_t5",
    DAY_TURKEY_HYBRID: "hybrid_turkey_cmg_p56",
}


# ─── Cobb 2021 §5.2 ──────────────────────────────────────────────────────────

# Возрастная часть таблицы Cobb кончается на 14-м дне, дальше строка «28 кг/м²»
COBB_AGE_TABLE_LAST_DAY = 14

# «Temperature Guidelines Based on Stocking Density»: плотность кг/м² → НИЖНЯЯ
# граница диапазона Cobb. Почему нижняя: строка 28 кг/м² есть и в таблице по RH,
# и там 22 °C стоит в колонке 60 % — ровно нижняя граница «22 to 24». Диапазон
# шириной 2 °C, таким образом, — это RH 60…40 %; профиль задан при 60 %, а другая
# RH сдвигает уставку той же поправкой, что и в возрастной части (см. ниже)
COBB_DENSITY_TABLE = [
    (28.0, 22.0), (30.0, 21.0), (32.0, 20.0), (34.0, 19.0),
    (36.0, 18.0), (38.0, 17.0), (40.0, 16.0), (42.0, 15.0),
]
# «42+» — 14 °C. Плотнее 42 кг/м² Cobb держать не советует; значение берём как есть
COBB_ABOVE_TABLE_C = 14.0
COBB_DENSITY_START = COBB_DENSITY_TABLE[0][0]

# Таблица по RH: 30…70 %, на каждые 10 % RH — 1 °C (на всех строках одинаково)
COBB_RH_RANGE = (30.0, 70.0)
COBB_REFERENCE_RH = 60.0


def cobb_rh_shift(rh: Optional[float]) -> float:
    """
    Сдвиг уставки Cobb относительно колонки 60 %: суше — теплее на 1 °C за 10 % RH.
    RH вне таблицы (30–70 %) — без сдвига, как и у Ross: экстраполировать не берёмся.
    """
    if rh is None or not (COBB_RH_RANGE[0] <= rh <= COBB_RH_RANGE[1]):
        return 0.0
    return (COBB_REFERENCE_RH - rh) / 10.0


def cobb_temp_by_density(density_kg_m2: float) -> float:
    """Уставка Cobb при 60 % RH по плотности не ниже 28 кг/м² (линейно между строками)."""
    table = COBB_DENSITY_TABLE
    if density_kg_m2 > table[-1][0]:
        return COBB_ABOVE_TABLE_C
    for (d0, t0), (d1, t1) in zip(table, table[1:]):
        if density_kg_m2 <= d1:
            return t0 + (t1 - t0) * (max(density_kg_m2, d0) - d0) / (d1 - d0)
    return table[-1][1]


def cobb_temp_after_age_table(t_day14_c: float, density_day14: float, density_now: float) -> float:
    """
    Уставка Cobb при 60 % RH после 14-го дня.

    В таблице по RH за строкой «14 дней» идёт строка «28 кг/м²» — следующая точка
    задана плотностью, а не днём. Между ними Cobb ничего не даёт; переход ведём
    линейно ПО ПЛОТНОСТИ от плотности 14-го дня к 28 кг/м² (наше допущение
    cobb_density_transition). По плотности, а не по дню — потому что её рост и
    задаёт смысл таблицы: при редкой посадке уставка снижается позже.
    """
    if density_now >= COBB_DENSITY_START or density_day14 >= COBB_DENSITY_START:
        return cobb_temp_by_density(density_now)
    share = (density_now - density_day14) / (COBB_DENSITY_START - density_day14)
    share = min(max(share, 0.0), 1.0)
    t28 = COBB_DENSITY_TABLE[0][1]
    return t_day14_c + (t28 - t_day14_c) * share


# ─── Уставка дня ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Setpoint:
    temp_c: float
    # Код методики этого дня (DAY_*), по нему выбирается источник
    method: str
    # Плотность посадки на этот день, кг/м² пола — только когда по ней считали
    density_kg_m2: Optional[float] = None


def profile_method(profile: GrowthProfile) -> Optional[str]:
    """Методика температуры встроенного профиля; у пользовательского — None."""
    if not profile.builtin:
        return None
    climate = (profile.source or {}).get("climate")
    return climate.get("method") if isinstance(climate, dict) else None


def setpoint_for_day(
    profile: GrowthProfile,
    age: int,
    point: GrowthPoint,
    rh: Optional[float],
    floor_m2: Optional[float],
    birds_now: float,
    birds_day14: float,
    mixed: bool = False,
) -> Setpoint:
    """
    Уставка температуры на день по методике кросса.

    floor_m2 — площадь пола ПОД ПТИЦЕЙ для плотности Cobb; None — плотность не
    определена (клетки: таблица Cobb — про подстилку, где тепло копится под птицей;
    или интерфейс без длины корпуса). Тогда после 14-го дня у Cobb берутся
    значения профиля (Ross) — DAY_COBB_FALLBACK, и ответ это называет.
    """
    method = profile_method(profile)
    base = point.min_temp_c

    if method == HUBBARD:
        # Hubbard поправки на RH не даёт: уставка — только по возрасту
        return Setpoint(base, DAY_HUBBARD)

    # Индейка: таблицы производителей — только по возрасту (уже в профиле). Смешанное
    # стадо до выборки самок — своя таблица, если она у производителя есть (Hybrid)
    if mixed and profile.mixed_temps:
        base = profile.mixed_temp_for_day(age)
    if method in (TURKEY_AVIAGEN, TURKEY_HYBRID):
        return Setpoint(base, method)
    if profile.species == "turkey":
        return Setpoint(base, DAY_TURKEY_PROFILE)

    if method == COBB:
        if age <= COBB_AGE_TABLE_LAST_DAY:
            return Setpoint(base + cobb_rh_shift(rh), DAY_COBB_AGE)
        if floor_m2:
            weight_kg = point.body_weight_g / 1000.0
            density = birds_now * weight_kg / floor_m2
            day14 = profile.point_for_day(COBB_AGE_TABLE_LAST_DAY)
            density_14 = birds_day14 * day14.body_weight_g / 1000.0 / floor_m2
            t60 = cobb_temp_after_age_table(day14.min_temp_c, density_14, density)
            return Setpoint(t60 + cobb_rh_shift(rh), DAY_COBB_DENSITY, density)
        method_day = DAY_COBB_FALLBACK
    else:
        method_day = DAY_ROSS if method == ROSS else DAY_PROFILE

    # Ross табл. 2.5: температура профиля — опорная при RH 60 %. При другой целевой
    # RH птица ощущает ту же сухую температуру иначе: суше — уставку выше, влажнее —
    # ниже. RH профиля вне таблицы (свой профиль с 80 %) — поправку не применяем
    t = base
    if rh is not None and 40.0 <= rh <= 70.0:
        t += rh_temperature_shift(point.body_weight_g, rh)
    return Setpoint(t, method_day)
