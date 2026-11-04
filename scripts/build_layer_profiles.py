#!/usr/bin/env python3
"""
Генератор встроенных профилей роста промышленных несушек и ремонтного молодняка
в клетках (species="layer"):
  - lohmann-lsl-classic.json   (Lohmann LSL-Classic — белая несушка, клетки, 0–72 нед.)
  - lohmann-brown-classic.json (Lohmann Brown-Classic — коричневая несушка, клетки, 0–72 нед.)
  - hyline-brown.json          (Hy-Line Brown — коричневая несушка, клетки, 0–72 нед.)
  - hyline-w36.json            (Hy-Line W-36 — белая несушка, клетки, 0–72 нед.)

Все таблицы оцифрованы напрямую из руководств производителей в refs/layers/:
  • Lohmann Tierzucht — Management Guide Cage Housing: Lohmann LSL-Classic (с. 10, 34–35, 38–39)
  • Lohmann Tierzucht — Management Guide Cage Housing: Lohmann Brown-Classic (с. 10, 34–35, 38–39)
  • Hy-Line Brown Commercial Layers — Performance Standards Guide, Conventional Systems, Dec 2025 (с. 4–6, 9)
  • Hy-Line W-36 Commercial Layers — Performance Standards Guide, Conventional Systems, Jan 2020 (с. 4–6, 9)
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "growth_profiles" / "builtin"


# ─── Lohmann LSL-Classic (Cage Management Guide, p. 10, 34–35, 38–39) ────────

# С. 34–35: средняя живая масса по неделям 1..72, г
LOHMANN_LSL_WEIGHT_G: dict[int, float] = {
    1: 75, 2: 125, 3: 187, 4: 257, 5: 338, 6: 432, 7: 530, 8: 627, 9: 722, 10: 814,
    11: 901, 12: 976, 13: 1041, 14: 1102, 15: 1159, 16: 1215, 17: 1268, 18: 1320,
    19: 1371, 20: 1422, 21: 1472, 22: 1520, 23: 1562, 24: 1598, 25: 1628, 26: 1648,
    27: 1665, 28: 1680, 29: 1690, 30: 1700, 31: 1707, 32: 1710, 33: 1713, 34: 1715,
    35: 1718, 36: 1720, 37: 1723, 38: 1725, 39: 1728, 40: 1730, 41: 1733, 42: 1735,
    43: 1738, 44: 1740, 45: 1743, 46: 1745, 47: 1747, 48: 1749, 49: 1751, 50: 1752,
    51: 1754, 52: 1755, 53: 1756, 54: 1758, 55: 1759, 56: 1760, 57: 1761, 58: 1763,
    59: 1764, 60: 1765, 61: 1766, 62: 1768, 63: 1769, 64: 1770, 65: 1771, 66: 1773,
    67: 1774, 68: 1775, 69: 1776, 70: 1778, 71: 1779, 72: 1780,
}

# Табл. 18 (с. 38–39): суточная яйцемасса Egg Mass g/H.D. in Week, недели 19..72
LOHMANN_LSL_EGG_MASS_G: dict[int, float] = {
    19: 3.9, 20: 16.5, 21: 26.0, 22: 36.0, 23: 43.0, 24: 47.6, 25: 50.9, 26: 53.0,
    27: 54.7, 28: 55.9, 29: 56.8, 30: 57.5, 31: 58.1, 32: 58.5, 33: 59.0, 34: 59.4,
    35: 59.7, 36: 59.9, 37: 60.0, 38: 60.1, 39: 60.2, 40: 60.3, 41: 60.4, 42: 60.4,
    43: 60.4, 44: 60.4, 45: 60.4, 46: 60.4, 47: 60.3, 48: 60.3, 49: 60.2, 50: 60.1,
    51: 60.1, 52: 60.0, 53: 59.9, 54: 59.8, 55: 59.7, 56: 59.6, 57: 59.4, 58: 59.3,
    59: 59.1, 60: 59.0, 61: 58.8, 62: 58.7, 63: 58.5, 64: 58.3, 65: 58.2, 66: 58.0,
    67: 57.7, 68: 57.5, 69: 57.3, 70: 57.0, 71: 56.8, 72: 56.4,
}


# ─── Lohmann Brown-Classic (Cage Management Guide, p. 10, 34–35, 38–39) ──────

LOHMANN_BROWN_WEIGHT_G: dict[int, float] = {
    1: 75, 2: 130, 3: 195, 4: 273, 5: 366, 6: 469, 7: 573, 8: 677, 9: 777, 10: 873,
    11: 963, 12: 1047, 13: 1128, 14: 1205, 15: 1279, 16: 1351, 17: 1421, 18: 1493,
    19: 1565, 20: 1635, 21: 1701, 22: 1760, 23: 1808, 24: 1846, 25: 1874, 26: 1893,
    27: 1906, 28: 1914, 29: 1918, 30: 1921, 31: 1924, 32: 1926, 33: 1929, 34: 1932,
    35: 1934, 36: 1936, 37: 1939, 38: 1941, 39: 1944, 40: 1946, 41: 1949, 42: 1952,
    43: 1954, 44: 1956, 45: 1959, 46: 1961, 47: 1964, 48: 1966, 49: 1969, 50: 1972,
    51: 1974, 52: 1976, 53: 1979, 54: 1981, 55: 1985, 56: 1986, 57: 1990, 58: 1992,
    59: 1994, 60: 1996, 61: 1999, 62: 2001, 63: 2004, 64: 2006, 65: 2009, 66: 2012,
    67: 2014, 68: 2016, 69: 2019, 70: 2021, 71: 2024, 72: 2026,
}

LOHMANN_BROWN_EGG_MASS_G: dict[int, float] = {
    19: 3.9, 20: 16.8, 21: 26.5, 22: 36.7, 23: 43.9, 24: 48.6, 25: 51.9, 26: 54.1,
    27: 55.7, 28: 56.9, 29: 57.8, 30: 58.5, 31: 59.2, 32: 59.6, 33: 60.1, 34: 60.4,
    35: 60.7, 36: 60.9, 37: 61.0, 38: 61.0, 39: 61.1, 40: 61.1, 41: 61.1, 42: 61.1,
    43: 61.1, 44: 61.0, 45: 61.0, 46: 60.9, 47: 60.8, 48: 60.7, 49: 60.6, 50: 60.5,
    51: 60.4, 52: 60.2, 53: 60.0, 54: 59.9, 55: 59.7, 56: 59.5, 57: 59.3, 58: 59.1,
    59: 58.9, 60: 58.7, 61: 58.5, 62: 58.3, 63: 58.1, 64: 57.9, 65: 57.7, 66: 57.5,
    67: 57.3, 68: 57.1, 69: 56.8, 70: 56.6, 71: 56.3, 72: 56.0,
}


def _lohmann_temp_c(day: int) -> float:
    """
    Lohmann Cage Management Guide, Table 1 (p. 10):
      Day 1–2: 35–36 °C (35.5)
      Day 3–4: 33–34 °C (33.5)
      Day 5–7: 31–32 °C (31.5)
      Week 2 (d 8–14): 28–29 °C (28.5)
      Week 3 (d 15–21): 26–27 °C (26.5)
      Week 4 (d 22–28): 22–24 °C (23.0)
      From Week 5 (d 29+): 18–20 °C (19.0)
    """
    if day <= 2:
        return 35.5
    if day <= 4:
        return 33.5
    if day <= 7:
        return 31.5
    if day <= 14:
        return 28.5
    if day <= 21:
        return 26.5
    if day <= 28:
        return 23.0
    return 19.0


def build_lohmann_profile(
    profile_id: str,
    name: str,
    breed: str,
    weights_by_week: dict[int, float],
    egg_mass_by_week: dict[int, float],
    weight_ref: str,
    egg_ref: str,
    climate_ref: str,
) -> dict:
    points: list[dict] = [
        {"day": 0, "body_weight_g": 38.0, "min_temp_c": 35.5, "rv_percent": 65.0, "egg_mass_g": 0.0},
        {"day": 2, "body_weight_g": None, "min_temp_c": 35.5, "rv_percent": 65.0},
        {"day": 4, "body_weight_g": None, "min_temp_c": 33.5, "rv_percent": 65.0},
    ]
    for week in range(1, 73):
        day = week * 7
        points.append({
            "day": day,
            "body_weight_g": float(weights_by_week[week]),
            "min_temp_c": _lohmann_temp_c(day),
            "rv_percent": 65.0,
            "egg_mass_g": round(float(egg_mass_by_week.get(week, 0.0)), 1),
        })
    return {
        "id": profile_id,
        "name": name,
        "breed": breed,
        "species": "layer",
        "sex": "female",
        "source": {
            "weight": {
                "ref": weight_ref,
                "page": 34,
                "basis": "female",
                "url": "https://lohmann-breeders.com/",
            },
            "egg_mass": {
                "ref": egg_ref,
                "page": 38,
                "url": "https://lohmann-breeders.com/",
            },
            "climate": {
                "ref": climate_ref,
                "table": "1",
                "page": 10,
                "method": "lohmann_cage_by_age",
                "source_id": "lohmann_cage_2019",
                "url": "https://lohmann-breeders.com/",
            },
        },
        "points": points,
    }


# ─── Hy-Line Brown (Performance Standards Guide, Dec 2025, p. 4–6, 9) ────────

# (low_g, high_g) по неделям 1..72 из таблиц Rearing (с. 4) и Production (с. 5–6)
HYLINE_BROWN_WEIGHT_RANGE_G: dict[int, tuple[float, float]] = {
    1: (69, 73), 2: (119, 126), 3: (186, 197), 4: (266, 281), 5: (357, 377),
    6: (456, 482), 7: (561, 593), 8: (668, 706), 9: (772, 816), 10: (871, 921),
    11: (963, 1018), 12: (1046, 1105), 13: (1120, 1184), 14: (1186, 1254),
    15: (1246, 1317), 16: (1302, 1377), 17: (1357, 1434),
    18: (1411, 1492), 19: (1467, 1551), 20: (1524, 1611), 21: (1582, 1672),
    22: (1638, 1732), 23: (1691, 1788), 24: (1739, 1838), 25: (1779, 1880),
    26: (1810, 1913), 27: (1832, 1937), 28: (1847, 1953), 29: (1857, 1963),
    30: (1864, 1971), 31: (1871, 1977), 32: (1877, 1984), 33: (1883, 1991),
    34: (1890, 1998), 35: (1896, 2004), 36: (1903, 2012), 37: (1909, 2018),
    38: (1913, 2023), 39: (1917, 2027), 40: (1921, 2030), 41: (1924, 2033),
    42: (1926, 2036), 43: (1928, 2039), 44: (1930, 2041), 45: (1932, 2043),
    46: (1934, 2044), 47: (1935, 2045), 48: (1936, 2047), 49: (1937, 2048),
    50: (1938, 2049), 51: (1939, 2050), 52: (1940, 2051), 53: (1941, 2052),
    54: (1942, 2053), 55: (1943, 2054), 56: (1944, 2055), 57: (1944, 2056),
    58: (1945, 2056), 59: (1946, 2057), 60: (1947, 2058), 61: (1948, 2059),
    62: (1948, 2060), 63: (1949, 2061), 64: (1950, 2061), 65: (1951, 2062),
    66: (1952, 2063), 67: (1952, 2064), 68: (1953, 2065), 69: (1954, 2065),
    70: (1954, 2066), 71: (1955, 2066), 72: (1955, 2067),
}

# (hd_low_pct, hd_high_pct, ew_low_g, ew_high_g) по неделям 18..72 (с. 5–6)
HYLINE_BROWN_LAY_TABLE: dict[int, tuple[float, float, float, float]] = {
    18: (6.7, 7.0, 42.8, 45.5), 19: (24.0, 25.2, 45.2, 48.0), 20: (52.5, 55.0, 47.6, 50.5),
    21: (75.9, 79.6, 49.1, 52.2), 22: (87.0, 91.2, 50.6, 53.7), 23: (90.9, 95.1, 51.9, 55.1),
    24: (92.4, 97.0, 53.1, 56.4), 25: (93.4, 98.1, 54.2, 57.6), 26: (93.6, 98.5, 55.2, 58.6),
    27: (93.6, 98.4, 56.1, 59.6), 28: (93.5, 98.4, 56.8, 60.4), 29: (93.4, 98.3, 57.5, 61.0),
    30: (93.3, 98.2, 58.0, 61.6), 31: (93.2, 98.1, 58.5, 62.1), 32: (93.1, 98.1, 58.9, 62.6),
    33: (92.9, 98.0, 59.3, 62.9), 34: (92.8, 97.9, 59.5, 63.2), 35: (92.7, 97.8, 59.7, 63.4),
    36: (92.5, 97.7, 59.9, 63.6), 37: (92.4, 97.6, 60.0, 63.8), 38: (92.3, 97.5, 60.1, 63.9),
    39: (92.1, 97.3, 60.2, 63.9), 40: (91.9, 97.2, 60.2, 63.9), 41: (91.8, 97.1, 60.2, 64.0),
    42: (91.6, 96.9, 60.3, 64.0), 43: (91.4, 96.8, 60.3, 64.0), 44: (91.2, 96.6, 60.3, 64.1),
    45: (91.1, 96.5, 60.4, 64.1), 46: (90.9, 96.3, 60.4, 64.1), 47: (90.7, 96.1, 60.4, 64.2),
    48: (90.5, 96.0, 60.5, 64.2), 49: (90.2, 95.8, 60.5, 64.3), 50: (90.0, 95.6, 60.5, 64.3),
    51: (89.8, 95.4, 60.6, 64.3), 52: (89.5, 95.2, 60.6, 64.4), 53: (89.3, 94.9, 60.6, 64.4),
    54: (89.1, 94.7, 60.7, 64.4), 55: (88.8, 94.5, 60.7, 64.5), 56: (88.5, 94.2, 60.7, 64.5),
    57: (88.3, 94.0, 60.8, 64.5), 58: (88.0, 93.7, 60.8, 64.6), 59: (87.7, 93.5, 60.8, 64.6),
    60: (87.4, 93.2, 60.9, 64.6), 61: (87.1, 92.9, 60.9, 64.7), 62: (86.4, 92.4, 60.9, 64.7),
    63: (86.1, 92.1, 61.0, 64.8), 64: (85.7, 91.8, 61.0, 64.8), 65: (85.4, 91.5, 61.0, 64.8),
    66: (85.1, 91.2, 61.1, 64.9), 67: (84.7, 90.8, 61.1, 64.9), 68: (84.4, 90.5, 61.1, 64.9),
    69: (84.0, 90.2, 61.2, 65.0), 70: (83.6, 89.8, 61.2, 65.0), 71: (83.3, 89.5, 61.2, 65.0),
    72: (82.9, 89.1, 61.3, 65.1),
}


# ─── Hy-Line W-36 (Performance Standards Guide, Jan 2020, p. 4–6, 9) ─────────

HYLINE_W36_WEIGHT_RANGE_G: dict[int, tuple[float, float]] = {
    1: (60, 73), 2: (100, 118), 3: (150, 181), 4: (200, 259), 5: (290, 349),
    6: (372, 440), 7: (472, 531), 8: (549, 621), 9: (649, 721), 10: (739, 812),
    11: (830, 894), 12: (921, 971), 13: (980, 1039), 14: (1039, 1111),
    15: (1102, 1161), 16: (1152, 1211), 17: (1188, 1252),
    18: (1230, 1300), 19: (1270, 1370), 20: (1320, 1430), 21: (1380, 1470),
    22: (1410, 1490), 23: (1430, 1500), 24: (1450, 1510), 25: (1470, 1530),
    26: (1480, 1540), 27: (1480, 1550), 28: (1490, 1550), 29: (1500, 1560),
    30: (1500, 1560), 31: (1510, 1570), 32: (1510, 1570), 33: (1520, 1580),
    34: (1520, 1580), 35: (1530, 1590), 36: (1530, 1590), 37: (1530, 1590),
    38: (1540, 1600), 39: (1540, 1600), 40: (1540, 1600), 41: (1540, 1600),
}
for _w in range(42, 73):
    HYLINE_W36_WEIGHT_RANGE_G[_w] = (1550, 1610)

# (hd_low_pct, hd_high_pct, ew_g) по неделям 18..72 (с. 5–6)
HYLINE_W36_LAY_TABLE: dict[int, tuple[float, float, float]] = {
    18: (2, 3, 44.2), 19: (15, 22, 45.0), 20: (35, 50, 45.9), 21: (60, 67, 48.0),
    22: (80, 84, 49.8), 23: (88, 92, 51.3), 24: (91, 94, 52.6), 25: (93, 95, 53.7),
    26: (94, 96, 54.7), 27: (95, 96, 55.5), 28: (95, 96, 56.3), 29: (95, 97, 57.0),
    30: (95, 97, 57.6), 31: (95, 97, 58.1), 32: (95, 96, 58.5), 33: (94, 96, 59.0),
    34: (94, 96, 59.3), 35: (94, 95, 59.7), 36: (94, 95, 60.0), 37: (93, 95, 60.3),
    38: (93, 95, 60.5), 39: (93, 95, 60.7), 40: (93, 94, 60.9), 41: (92, 94, 61.1),
    42: (92, 94, 61.3), 43: (92, 93, 61.5), 44: (91, 93, 61.6), 45: (91, 93, 61.8),
    46: (90, 92, 61.9), 47: (90, 92, 62.0), 48: (90, 92, 62.1), 49: (90, 92, 62.2),
    50: (89, 91, 62.3), 51: (89, 91, 62.4), 52: (89, 91, 62.5), 53: (88, 91, 62.5),
    54: (88, 90, 62.6), 55: (88, 90, 62.7), 56: (87, 90, 62.7), 57: (87, 89, 62.8),
    58: (87, 89, 62.9), 59: (86, 88, 62.9), 60: (86, 88, 63.0), 61: (86, 88, 63.0),
    62: (85, 88, 63.0), 63: (85, 87, 63.1), 64: (85, 87, 63.1), 65: (84, 86, 63.2),
    66: (84, 86, 63.2), 67: (83, 85, 63.2), 68: (83, 85, 63.3), 69: (82, 85, 63.3),
    70: (82, 84, 63.3), 71: (81, 84, 63.3), 72: (81, 83, 63.4),
}


def _hyline_temp_c(day: int, day0_3_temp: float) -> float:
    """
    Hy-Line Brooding Temperature Recommendations (Cage Air Temp., p. 9):
      0–3 days: 33–36 °C (34.5 Brown) / 32–33 °C (32.5 W-36)
      4–7 days: 30–32 °C (31.0)
      8–14 days: 28–30 °C (29.0)
      15–21 days: 26–28 °C (27.0)
      22–28 days: 23–26 °C (24.5)
      29–35 days: 21–23 °C (22.0)
      36–119 days (rearing from week 6 to week 17): 21.0 °C
      120+ days (laying period from week 18, p. 17: 18–25 °C comfort): 20.0 °C
    """
    if day <= 3:
        return day0_3_temp
    if day <= 7:
        return 31.0
    if day <= 14:
        return 29.0
    if day <= 21:
        return 27.0
    if day <= 28:
        return 24.5
    if day <= 35:
        return 22.0
    if day <= 119:
        return 21.0
    return 20.0


def build_hyline_brown() -> dict:
    points: list[dict] = [
        {"day": 0, "body_weight_g": 38.0, "min_temp_c": 34.5, "rv_percent": 60.0, "egg_mass_g": 0.0},
        {"day": 3, "body_weight_g": None, "min_temp_c": 34.5, "rv_percent": 60.0},
    ]
    for week in range(1, 73):
        day = week * 7
        w_lo, w_hi = HYLINE_BROWN_WEIGHT_RANGE_G[week]
        weight_g = round((w_lo + w_hi) / 2.0, 1)
        egg_g = 0.0
        if week in HYLINE_BROWN_LAY_TABLE:
            hd_lo, hd_hi, ew_lo, ew_hi = HYLINE_BROWN_LAY_TABLE[week]
            egg_g = round(((hd_lo + hd_hi) / 200.0) * ((ew_lo + ew_hi) / 2.0), 1)
        points.append({
            "day": day,
            "body_weight_g": weight_g,
            "min_temp_c": _hyline_temp_c(day, 34.5),
            "rv_percent": 60.0,
            "egg_mass_g": egg_g,
        })
    return {
        "id": "hyline-brown",
        "name": "Hy-Line Brown — commercial layers",
        "breed": "Hy-Line Brown",
        "species": "layer",
        "sex": "female",
        "min_vent_norm": "hyline_2018_xin",
        "source": {
            "weight": {
                "ref": "Hy-Line Brown Commercial Layers — Performance Standards Guide, Conventional Systems (Dec 2025), Rearing & Production Tables (Weeks 1–72, midpoint)",
                "page": 4,
                "basis": "female",
                "url": "https://www.hyline.com/",
            },
            "egg_mass": {
                "ref": "Hy-Line Brown Performance Standards Guide (Dec 2025), Production Period Table (% Hen-Day × Avg. Egg Weight, Weeks 18–72)",
                "page": 5,
                "url": "https://www.hyline.com/",
            },
            "climate": {
                "ref": "Hy-Line Brown Performance Standards Guide (Dec 2025), Brooding Temperature Recommendations (Cage Air Temp., p. 9) & Hy-Line Brown Management Guide (2018, p. 17)",
                "table": "Brooding Temperature Recommendations",
                "page": 9,
                "method": "hyline_cage_by_age",
                "source_id": "hyline_cage_2025",
                "url": "https://www.hyline.com/",
            },
        },
        "points": points,
    }


def build_hyline_w36() -> dict:
    points: list[dict] = [
        {"day": 0, "body_weight_g": 37.0, "min_temp_c": 32.5, "rv_percent": 60.0, "egg_mass_g": 0.0},
        {"day": 3, "body_weight_g": None, "min_temp_c": 32.5, "rv_percent": 60.0},
    ]
    for week in range(1, 73):
        day = week * 7
        w_lo, w_hi = HYLINE_W36_WEIGHT_RANGE_G[week]
        weight_g = round((w_lo + w_hi) / 2.0, 1)
        egg_g = 0.0
        if week in HYLINE_W36_LAY_TABLE:
            hd_lo, hd_hi, ew_g = HYLINE_W36_LAY_TABLE[week]
            egg_g = round(((hd_lo + hd_hi) / 200.0) * ew_g, 1)
        points.append({
            "day": day,
            "body_weight_g": weight_g,
            "min_temp_c": _hyline_temp_c(day, 32.5),
            "rv_percent": 60.0,
            "egg_mass_g": egg_g,
        })
    return {
        "id": "hyline-w36",
        "name": "Hy-Line W-36 — commercial layers",
        "breed": "Hy-Line W-36",
        "species": "layer",
        "sex": "female",
        "min_vent_norm": "hyline_2018_xin",
        "source": {
            "weight": {
                "ref": "Hy-Line W-36 Commercial Layers — Performance Standards Guide, Conventional Systems (Jan 2020), Rearing & Production Tables (Weeks 1–72, midpoint)",
                "page": 4,
                "basis": "female",
                "url": "https://www.hyline.com/",
            },
            "egg_mass": {
                "ref": "Hy-Line W-36 Performance Standards Guide (Jan 2020), Production Period Table (% Hen-Day × Avg. Egg Weight, Weeks 18–72)",
                "page": 5,
                "url": "https://www.hyline.com/",
            },
            "climate": {
                "ref": "Hy-Line W-36 Performance Standards Guide (Jan 2020), Brooding Temperature Recommendations (Cage Air Temp., p. 9) & Hy-Line Brown Management Guide (2018, p. 17)",
                "table": "Brooding Temperature Recommendations",
                "page": 9,
                "method": "hyline_cage_by_age",
                "source_id": "hyline_cage_2025",
                "url": "https://www.hyline.com/",
            },
        },
        "points": points,
    }


def build_all() -> list[dict]:
    return [
        build_lohmann_profile(
            "lohmann-lsl-classic",
            "Lohmann LSL-Classic — commercial layers",
            "Lohmann LSL-Classic",
            LOHMANN_LSL_WEIGHT_G,
            LOHMANN_LSL_EGG_MASS_G,
            "Lohmann Tierzucht — Management Guide Cage Housing: Lohmann LSL-Classic, Body Weight Development (Weeks 1–72)",
            "Lohmann Tierzucht — Management Guide Cage Housing: Lohmann LSL-Classic, Table 18 Performance Goals (Egg Mass g/H.D., Weeks 19–72)",
            "Lohmann Tierzucht — Management Guide Cage Housing: Lohmann LSL-Classic, Table 1 Desired Temperatures at Bird Level & RH 60–70 %",
        ),
        build_lohmann_profile(
            "lohmann-brown-classic",
            "Lohmann Brown-Classic — commercial layers",
            "Lohmann Brown-Classic",
            LOHMANN_BROWN_WEIGHT_G,
            LOHMANN_BROWN_EGG_MASS_G,
            "Lohmann Tierzucht — Management Guide Cage Housing: Lohmann Brown-Classic, Table 17 Body Weight Development (Weeks 1–72)",
            "Lohmann Tierzucht — Management Guide Cage Housing: Lohmann Brown-Classic, Table 18 Performance Goals (Egg Mass g/H.D., Weeks 19–72)",
            "Lohmann Tierzucht — Management Guide Cage Housing: Lohmann Brown-Classic, Table 1 Desired Temperatures at Bird Level & RH 60–70 %",
        ),
        build_hyline_brown(),
        build_hyline_w36(),
    ]


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for prof in build_all():
        out_path = OUT_DIR / f"{prof['id']}.json"
        out_path.write_text(json.dumps(prof, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote {out_path.relative_to(ROOT)} ({len(prof['points'])} points)")


if __name__ == "__main__":
    main()
