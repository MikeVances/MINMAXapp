"""
Психрометрия влажного воздуха — одна на все модули.

Раньше в трёх копиях: calc_core и evap_cooling_calc считали влагосодержание
каждый сам, мокрый термометр шёл по формуле Стулла (2011), а плотность —
константой 1.184 кг/м³. Формула Стулла заявлялась с точностью ±0.3 °C, но в
сухую жару (40–45 °C, RH 20–30 %) — именно там, где считают панели, — ошибалась
на +0.7…+1.0 °C против ASHRAE (сверено с psychrolib 2.5, 2026-10-19); расход
воды через это завышался на десятки процентов при высокой RH. Константа 1.184
завышала массу сухого воздуха в кубометре на 3–6 % на выходе панели.

Уравнения — ASHRAE Handbook Fundamentals 2017, гл. 1 (номера в скобках).
Давление насыщения — формула Магнуса: против Hyland–Wexler (ASHRAE) расхождение
< 0.3 % в рабочем диапазоне, мокрый термометр от этого сдвигается < 0.05 °C.
Давление — 101 325 Па по умолчанию (высота над уровнем моря — отдельная задача,
параметр p_pa для неё уже есть).
"""
from __future__ import annotations

import math

P_ATM_PA = 101_325.0
# Отношение молярных масс воды и сухого воздуха (ASHRAE: 0.621945)
_EPS = 0.621945
# Газовая постоянная сухого воздуха, кДж/(кг·К) (ASHRAE: 0.287042)
_R_DA = 0.287042


def sat_pressure_pa(t_c: float) -> float:
    """Давление насыщенного пара над водой, Па (Магнус: 611.2·exp(17.67·t/(t+243.5)))."""
    return 611.2 * math.exp(17.67 * t_c / (t_c + 243.5))


def sat_pressure_ice_pa(t_c: float) -> float:
    """Давление насыщения надо льдом, Па (Магнус для льда, WMO: 22.46 / 272.62)."""
    return 611.2 * math.exp(22.46 * t_c / (t_c + 272.62))


def humidity_ratio(t_c: float, rh_pct: float, p_pa: float = P_ATM_PA) -> float:
    """
    Влагосодержание W, кг воды / кг сухого воздуха (20): W = 0.621945·pw/(p − pw).

    RH — относительно насыщения НАД ВОДОЙ и ниже нуля: так её дают метеостанции
    (WMO) и так её вводит пользователь. psychrolib ниже нуля берёт лёд — отсюда
    расхождение точки росы на морозе, это разница соглашений, а не ошибка.
    """
    p_w = max(rh_pct, 0.0) / 100.0 * sat_pressure_pa(t_c)
    return _EPS * p_w / max(p_pa - p_w, 1.0)


def _w_from_wet_bulb(t_c: float, t_wb: float, p_pa: float) -> float:
    """W по температурам сухого и мокрого термометров (33) — выше нуля, (35) — ниже.

    Ниже нуля термометр обледенел: насыщение у его поверхности — надо льдом."""
    if t_wb >= 0.0:
        ws = humidity_ratio(t_wb, 100.0, p_pa)
        return ((2501.0 - 2.326 * t_wb) * ws - 1.006 * (t_c - t_wb)) / (2501.0 + 1.86 * t_c - 4.186 * t_wb)
    p_wi = sat_pressure_ice_pa(t_wb)
    ws = _EPS * p_wi / (p_pa - p_wi)
    return ((2830.0 - 0.24 * t_wb) * ws - 1.006 * (t_c - t_wb)) / (2830.0 + 1.86 * t_c - 2.1 * t_wb)


def wet_bulb_c(t_c: float, rh_pct: float, p_pa: float = P_ATM_PA) -> float:
    """
    Температура мокрого термометра, °C — решение (33)/(35) относительно t_wb.

    W(t_wb) растёт монотонно, поэтому деление пополам между −60 °C и t_c сходится
    всегда; 60 шагов — точность лучше 1e-12 °C, дешевле любой подгонки.
    """
    w = humidity_ratio(t_c, rh_pct, p_pa)
    lo, hi = -60.0, t_c
    for _ in range(60):
        mid = (lo + hi) / 2.0
        if _w_from_wet_bulb(t_c, mid, p_pa) > w:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2.0


def dew_point_c(t_c: float, rh_pct: float) -> float:
    """Точка росы, °C — обращение формулы Магнуса."""
    g = math.log(max(rh_pct, 0.01) / 100.0 * sat_pressure_pa(t_c) / 611.2)
    return 243.5 * g / (17.67 - g)


def specific_volume_m3_per_kg_da(t_c: float, w: float, p_pa: float = P_ATM_PA) -> float:
    """Удельный объём влажного воздуха, м³ на кг СУХОГО воздуха (26)."""
    return _R_DA * (t_c + 273.15) * (1.0 + 1.607858 * w) / (p_pa / 1000.0)


def dry_air_kg_per_m3(t_c: float, w: float, p_pa: float = P_ATM_PA) -> float:
    """Масса сухого воздуха в кубометре влажного — для балансов «на кг сухого воздуха»."""
    return 1.0 / specific_volume_m3_per_kg_da(t_c, w, p_pa)


def moist_air_density(t_c: float, rh_pct: float, p_pa: float = P_ATM_PA) -> float:
    """Плотность влажного воздуха, кг/м³ (28): (1 + W) / v — для давлений и расходов."""
    w = humidity_ratio(t_c, rh_pct, p_pa)
    return (1.0 + w) / specific_volume_m3_per_kg_da(t_c, w, p_pa)
