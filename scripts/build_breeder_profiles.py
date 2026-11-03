"""
Сборка встроенных профилей родительского стада бройлеров (data/growth_profiles/builtin/*.json)
из таблиц руководств производителей (Aviagen Ross 308 PS и Cobb 500 FF / Cobb MX).

Почему генератор, а не JSON руками: таблицы ниже переписаны из PDF дословно (неделя →
масса и суточная яйцемасса Y₂, возраст → температура и RH), а профиль — их раскладка
по дням. Проверить число по первоисточнику проще в таблице со ссылкой на страницу,
чем в 80 точках JSON; правка таблицы — один перезапуск.

Запуск из корня репозитория:  python scripts/build_breeder_profiles.py
Первоисточники лежат локально в refs/breeders/ (не в git), ссылки — в source профиля.
"""
from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "data" / "growth_profiles" / "builtin"


# ─── Ross 308 Parent Stock (Aviagen, PO 2021 & Management Handbook 2023) ─────

# Aviagen, Ross 308 Parent Stock Performance Objectives (2021):
# Day-old weight = 40 g (прямо в таблицах с. 4 для курочек и с. 7 для петушков)
ROSS_DAY0_WEIGHT_G = 40.0

# Female Body Weight and Feeding Program — In-Season (с. 4), недели 1–64, г
ROSS_FEMALE_WEIGHTS_G = [
    115, 215, 335, 465, 585, 695, 795, 895, 995, 1095,
    1195, 1295, 1395, 1495, 1595, 1705, 1825, 1950, 2085, 2230,
    2380, 2530, 2680, 2830, 2970, 3090, 3190, 3290, 3360, 3410,
    3450, 3490, 3530, 3570, 3600, 3630, 3655, 3680, 3705, 3725,
    3745, 3765, 3785, 3805, 3825, 3845, 3865, 3885, 3905, 3925,
    3945, 3960, 3975, 3985, 3995, 4005, 4015, 4025, 4035, 4045,
    4055, 4065, 4075, 4085,
]

# Male Body Weight and Feeding Program (с. 7), недели 1–64, г
ROSS_MALE_WEIGHTS_G = [
    150, 320, 525, 755, 945, 1130, 1280, 1420, 1545, 1670,
    1795, 1920, 2045, 2170, 2295, 2420, 2560, 2715, 2875, 3035,
    3195, 3355, 3515, 3675, 3825, 3960, 4035, 4090, 4120, 4150,
    4180, 4210, 4240, 4270, 4300, 4330, 4360, 4390, 4420, 4450,
    4480, 4510, 4540, 4570, 4600, 4630, 4660, 4690, 4720, 4750,
    4780, 4810, 4840, 4870, 4900, 4930, 4960, 4990, 5020, 5050,
    5080, 5110, 5140, 5170,
]

# Egg Production and Hatchability (с. 10), колонка Daily Egg Mass (g):
# недели 1–24 = 0.0 г/сут, недели 25–64 (40 недель продуктивности)
ROSS_EGG_MASS_W25_64_G = [
    2.7, 12.2, 28.9, 41.8, 47.8, 50.6, 52.0, 52.4, 52.3, 52.2,
    52.1, 51.9, 51.6, 51.3, 51.0, 50.6, 50.2, 49.8, 49.4, 49.0,
    48.6, 48.2, 47.7, 47.2, 46.7, 46.3, 45.8, 45.3, 44.8, 44.3,
    43.7, 43.1, 42.5, 41.8, 41.2, 40.5, 39.8, 39.1, 38.4, 37.5,
]
ROSS_EGG_MASS_G = [0.0] * 24 + ROSS_EGG_MASS_W25_64_G

# Ross PS Management Handbook 2023, Table 4 «Recommended temperature guide at bird level
# at an RH of 60-70%», с. 25, колонка Whole-House Brooding Temp:
# дни 0–27 (Day-old: 30, 3: 28, 6: 27, 9: 26, 12: 25, 15: 24, 18: 23, 21: 22, 24: 21, 27: 20).
# По решению владельца 2026-11-03 (нижняя граница диапазона гида по периодам):
# в ремонте после брудинга (с 24-го по 140-й день, Aviagen Rearing House Table 1 с. 4:
# 24–27 и 28+ дн = 70 °F = 21 °C) держим 21 °C; в продуктивном периоде (с 141-го дня,
# 21 нед, Ross PO 2021 с. 6: 20–21 °C; Ross PS Table 4 день 27: 20 °C) — 20 °C.
ROSS_TEMPS = [
    (1, 30.0),
    (3, 28.0),
    (6, 27.0),
    (9, 26.0),
    (12, 25.0),
    (15, 24.0),
    (18, 23.0),
    (21, 22.0),
    (24, 21.0),
    (141, 20.0),
]

# Ross PS Management Handbook 2023, с. 25 (Table 4): RH 60–70 % (верхняя граница — 70 %)
ROSS_RH = 70.0


# ─── Cobb 500 FF & Cobb MX (Cobb Supplements 2026 & Breeder Guide 2021) ──────

# В таблицах Cobb 2026 строки начинаются с недели 1 (день 7). Суточная масса 40 г —
# из Ross 308 PS PO 2021 с. 4 (и согласуется с Cobb 500 FF 2026 с. 9: масса цыплёнка
# от пикового яйца ~40 г), оформлена отдельным источником weight_day0
COBB_DAY0_WEIGHT_G = 40.0
COBB_DAY0_SOURCE = {
    "ref": "Aviagen, Ross 308 Parent Stock Performance Objectives (2021), Day-old weight 40 g "
           "(Cobb 500 FF / MX supplements start at week 1)",
    "value_g": COBB_DAY0_WEIGHT_G,
    "url": "https://aviagen.com/assets/Tech_Center/Ross_PS/Ross308-ParentStock-PerformanceObjectives-2021-EN.pdf",
}

# Cobb500 Fast Feather Female Parent Stock Performance & Nutrition Supplement (2026),
# Body Weight (g), с. 5–8, недели 1–65
COBB_FEMALE_WEIGHTS_G = [
    145, 280, 405, 520, 630, 740, 840, 940, 1030, 1120,
    1210, 1300, 1390, 1490, 1590, 1690, 1830, 1980, 2140, 2300,
    2450, 2600, 2850, 3000, 3130, 3260, 3360, 3460, 3540, 3600,
    3645, 3680, 3715, 3750, 3780, 3810, 3835, 3860, 3880, 3900,
    3920, 3940, 3960, 3980, 4000, 4020, 4040, 4060, 4080, 4095,
    4110, 4125, 4140, 4150, 4160, 4170, 4180, 4190, 4200, 4210,
    4220, 4230, 4240, 4250, 4260,
]

# Cobb MV & MX Male Parent Stock Performance & Nutrition Supplement (2026),
# Cobb MX Male Body Weight (g), с. 11, недели 1–65
COBB_MALE_WEIGHTS_G = [
    150, 350, 545, 725, 870, 1010, 1130, 1245, 1360, 1470,
    1580, 1710, 1845, 1975, 2110, 2240, 2385, 2535, 2680, 2840,
    3000, 3190, 3360, 3500, 3620, 3750, 3870, 3960, 4030, 4090,
    4140, 4180, 4210, 4235, 4260, 4285, 4310, 4335, 4360, 4385,
    4410, 4435, 4460, 4485, 4510, 4535, 4560, 4585, 4610, 4635,
    4660, 4680, 4700, 4720, 4740, 4760, 4780, 4800, 4820, 4840,
    4860, 4880, 4900, 4920, 4940,
]

# Cobb500 FF Supplement (2026): Egg Production (% Hen-Day / %HW, с. 9) и Egg Weight (g, с. 10),
# недели 24–65 (42 недели яйцекладки); суточная яйцемасса Y₂ = %HW × EggWeight / 100
COBB_HW_PCT_W24_65 = [
    3.0, 22.0, 53.0, 73.5, 82.2, 85.1, 86.0, 85.8, 84.8, 84.1,
    82.8, 81.9, 80.9, 79.9, 79.1, 78.1, 77.0, 75.9, 74.8, 73.6,
    72.4, 71.2, 70.2, 69.0, 67.8, 66.6, 65.4, 64.1, 62.8, 61.5,
    60.1, 58.7, 57.6, 56.2, 54.9, 53.2, 51.7, 49.8, 48.5, 46.9,
    45.3, 43.7,
]
COBB_EGG_WEIGHT_W24_65_G = [
    48.5, 50.0, 51.4, 53.0, 54.6, 56.0, 57.2, 58.3, 59.2, 60.0,
    60.7, 61.4, 62.0, 62.6, 63.1, 63.6, 64.0, 64.5, 64.9, 65.3,
    65.7, 66.1, 66.5, 66.8, 67.2, 67.5, 67.8, 68.1, 68.4, 68.7,
    68.9, 69.1, 69.3, 69.5, 69.7, 69.9, 70.1, 70.3, 70.5, 70.7,
    70.9, 71.1,
]
COBB_EGG_MASS_G = [0.0] * 23 + [
    round(hw * ew / 100.0, 1)
    for hw, ew in zip(COBB_HW_PCT_W24_65, COBB_EGG_WEIGHT_W24_65_G)
]

# Cobb Breeder Management Guide (2021), с. 26 (PDF с. 32), таблица брудинга
# «Floor Temperature (60% RH)»:
#   0–3 дн: 31 °C, 4–7 дн: 30 °C, 8–15 дн: 29 °C, 16–18 дн: 28 °C,
#   19–21 дн: 26 °C, 22–24 дн: 24 °C, 25–27 дн: 22 °C.
# С 28-го дня до конца жизни (и в ремонте, и в продуктивном периоде): 21 °C
# (Cobb Breeder Guide с. 55: 21–22 °C, нижняя граница; Cobb 500FF/MX supplements: 21 °C)
COBB_TEMPS = [
    (1, 31.0),
    (4, 30.0),
    (8, 29.0),
    (16, 28.0),
    (19, 26.0),
    (22, 24.0),
    (25, 22.0),
    (28, 21.0),
]

# Cobb Breeder Management Guide (2021), с. 116: целевая RH 45–65 % (верхняя граница — 65 %)
COBB_RH = 65.0


# ─── Источники ───────────────────────────────────────────────────────────────

ROSS_PO_URL = "https://aviagen.com/assets/Tech_Center/Ross_PS/Ross308-ParentStock-PerformanceObjectives-2021-EN.pdf"
ROSS_HB_URL = "https://aviagen.com/assets/Tech_Center/Ross_PS/RossPSHandBook2023.pdf"

ROSS_FEMALE_WEIGHT_REF = {
    "ref": "Aviagen, Ross 308 Parent Stock Performance Objectives (2021), Female Body Weight (In-Season)",
    "page": 4,
    "basis": "female",
    "url": ROSS_PO_URL,
}
ROSS_MALE_WEIGHT_REF = {
    "ref": "Aviagen, Ross 308 Parent Stock Performance Objectives (2021), Male Body Weight",
    "page": 7,
    "basis": "male",
    "url": ROSS_PO_URL,
}
ROSS_EGG_REF = {
    "ref": "Aviagen, Ross 308 Parent Stock Performance Objectives (2021), Daily Egg Mass (g)",
    "page": 10,
    "url": ROSS_PO_URL,
}
ROSS_CLIMATE = {
    "ref": "Aviagen, Ross Parent Stock Management Handbook (2023)",
    "table": "4",
    "page": 25,
    "column": "Whole-House Brooding Temp, lower bound",
    "method": "ross_ps_by_age",
    "source_id": "ross_ps_2023_t4",
    "url": ROSS_HB_URL,
}

COBB_FEMALE_URL = "https://www.cobbgenetics.com/assets/Cobb-Files/Cobb500-Fast-Feather-Breeder-Performance-Supplement.pdf"
COBB_MALE_URL = "https://www.cobbgenetics.com/assets/Cobb-Files/Cobb-Male-Supplement.pdf"
COBB_GUIDE_URL = "https://www.cobbgenetics.com/assets/Cobb-Files/Cobb-Breeder-Management-Guide.pdf"

COBB_FEMALE_WEIGHT_REF = {
    "ref": "Cobb-Vantress, Cobb500 Fast Feather Female Parent Stock Supplement (2026), Body Weight (g)",
    "page": 5,
    "basis": "female",
    "url": COBB_FEMALE_URL,
}
COBB_MALE_WEIGHT_REF = {
    "ref": "Cobb-Vantress, Cobb MV & MX Male Parent Stock Supplement (2026), Cobb MX Body Weight (g)",
    "page": 11,
    "basis": "male",
    "url": COBB_MALE_URL,
}
COBB_EGG_REF = {
    "ref": "Cobb-Vantress, Cobb500 Fast Feather Female Parent Stock Supplement (2026), %HW × Egg Weight (g)",
    "page": 9,
    "url": COBB_FEMALE_URL,
}
COBB_CLIMATE = {
    "ref": "Cobb-Vantress, Cobb Breeder Management Guide (2021)",
    "table": "Floor Temperature (60% RH)",
    "page": 26,
    "column": "Floor Temperature at 60 % RH, lower bound",
    "method": "cobb_breeder_by_age",
    "source_id": "cobb_breeder_2021_temp",
    "url": COBB_GUIDE_URL,
}


def _step_temp(temps: list[tuple[int, float]], day: int) -> float:
    """Температура ступени, в которую попадает день (день 0 — как день 1)."""
    value = temps[0][1]
    for first_day, t in temps:
        if day >= first_day:
            value = t
    return float(value)


def _points(
    day0_g: float,
    weights_g: list[float],
    temps: list[tuple[int, float]],
    rh: float,
    egg_mass_g: list[float] | None = None,
) -> list[dict]:
    """
    Точки профиля. Таблица температуры ступенчатая, а профиль интерполирует линейно
    между точками: чтобы ступень осталась ступенью, у каждой ступени две точки —
    первый и последний её день. Масса и суточная яйцемасса Y₂ — на конец недели
    (день 7·N) и день 0.
    """
    last_day = 7 * len(weights_g)
    days = {0, last_day} | {7 * (i + 1) for i in range(len(weights_g))}
    for i, (first_day, _) in enumerate(temps):
        days.add(first_day)
        if i:
            days.add(first_day - 1)
    days = sorted(d for d in days if d <= last_day)

    points = []
    for d in days:
        weight = day0_g if d == 0 else (
            float(weights_g[d // 7 - 1]) if d % 7 == 0 else None
        )
        pt: dict = {
            "day": d,
            "body_weight_g": weight,
            "min_temp_c": _step_temp(temps, d),
            "rv_percent": rh,
        }
        if egg_mass_g is not None:
            egg = 0.0 if d == 0 else (
                float(egg_mass_g[d // 7 - 1]) if d % 7 == 0 else None
            )
            if egg is not None:
                pt["egg_mass_g"] = egg
        points.append(pt)
    return points


def build() -> list[dict]:
    return [
        {
            "id": "ross308-ps-females",
            "name": "Ross 308 PS — females",
            "breed": "Ross 308 PS",
            "species": "broiler_breeder",
            "sex": "female",
            "min_vent_norm": "ross_ps_table25",
            "source": {
                "weight": ROSS_FEMALE_WEIGHT_REF,
                "egg_mass": ROSS_EGG_REF,
                "climate": ROSS_CLIMATE,
            },
            "points": _points(
                ROSS_DAY0_WEIGHT_G, ROSS_FEMALE_WEIGHTS_G, ROSS_TEMPS, ROSS_RH, ROSS_EGG_MASS_G
            ),
        },
        {
            "id": "ross308-ps-males",
            "name": "Ross 308 PS — males",
            "breed": "Ross 308 PS",
            "species": "broiler_breeder",
            "sex": "male",
            "min_vent_norm": "ross_ps_table25",
            "source": {
                "weight": ROSS_MALE_WEIGHT_REF,
                "climate": ROSS_CLIMATE,
            },
            "points": _points(
                ROSS_DAY0_WEIGHT_G, ROSS_MALE_WEIGHTS_G, ROSS_TEMPS, ROSS_RH
            ),
        },
        {
            "id": "cobb500ff-females",
            "name": "Cobb 500 FF — females",
            "breed": "Cobb 500 FF",
            "species": "broiler_breeder",
            "sex": "female",
            "source": {
                "weight": COBB_FEMALE_WEIGHT_REF,
                "weight_day0": COBB_DAY0_SOURCE,
                "egg_mass": COBB_EGG_REF,
                "climate": COBB_CLIMATE,
            },
            "points": _points(
                COBB_DAY0_WEIGHT_G, COBB_FEMALE_WEIGHTS_G, COBB_TEMPS, COBB_RH, COBB_EGG_MASS_G
            ),
        },
        {
            "id": "cobb-mx-males",
            "name": "Cobb MX — males",
            "breed": "Cobb MX",
            "species": "broiler_breeder",
            "sex": "male",
            "source": {
                "weight": COBB_MALE_WEIGHT_REF,
                "weight_day0": COBB_DAY0_SOURCE,
                "climate": COBB_CLIMATE,
            },
            "points": _points(
                COBB_DAY0_WEIGHT_G, COBB_MALE_WEIGHTS_G, COBB_TEMPS, COBB_RH
            ),
        },
    ]


if __name__ == "__main__":
    for profile in build():
        path = OUT / f"{profile['id']}.json"
        path.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(path.relative_to(OUT.parents[2]), len(profile["points"]), "points")
