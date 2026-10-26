"""
Сборка встроенных профилей индейки (data/growth_profiles/builtin/*.json) из таблиц
руководств производителей.

Почему генератор, а не JSON руками: таблицы ниже переписаны из PDF дословно (неделя →
масса, возраст → температура), а профиль — их раскладка по дням. Проверить число по
первоисточнику проще в таблице со ссылкой на страницу, чем в 40 точках JSON; правка
таблицы — один перезапуск, а не правка каждой точки.

Запуск из корня репозитория:  python scripts/build_turkey_profiles.py
Первоисточники лежат локально в refs/turkey/ (не в git), ссылки — в source профиля.
"""
from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "data" / "growth_profiles" / "builtin"


# ─── Масса, кг на конец недели ───────────────────────────────────────────────

# Aviagen Turkeys, B.U.T. 6 Commercial Performance Objectives (POCLLB6/EN V2, 2022),
# колонка Live Weight (kg): самцы 1–22 нед, самки 1–18 нед
BUT6_MALES = [0.18, 0.37, 0.72, 1.23, 1.93, 2.81, 3.84, 5.00, 6.26, 7.60, 8.99,
              10.42, 11.87, 13.31, 14.75, 16.16, 17.55, 18.91, 20.23, 21.50, 22.72, 23.88]
BUT6_FEMALES = [0.17, 0.34, 0.63, 1.05, 1.61, 2.28, 3.04, 3.88, 4.77, 5.71, 6.67,
                7.65, 8.62, 9.55, 10.45, 11.29, 12.07, 12.79]

# Hybrid Turkeys, Performance Goals Converter Commercial Males / Females — Metric
# (NA012023, 2023), колонка Body Weight (kg)
CONVERTER_MALES = [0.18, 0.39, 0.76, 1.39, 2.13, 3.05, 4.13, 5.28, 6.50, 7.87, 9.34,
                   10.80, 12.33, 13.93, 15.48, 17.07, 18.57, 19.96, 21.25, 22.49, 23.67, 24.81]
CONVERTER_FEMALES = [0.18, 0.37, 0.72, 1.19, 1.76, 2.56, 3.45, 4.43, 5.44, 6.49, 7.52,
                     8.53, 9.47, 10.33, 11.11, 11.83, 12.46, 13.02]

# Hybrid Turkeys, Performance Goals ConverterNOVO Commercial Males / Females
# (202012, 2020; «preliminary trials and projections … deviation of +/- 5%»)
NOVO_MALES = [0.16, 0.34, 0.73, 1.29, 2.02, 2.89, 3.90, 5.01, 6.23, 7.53, 8.90,
              10.32, 11.77, 13.23, 14.70, 16.16, 17.58, 18.96, 20.27, 21.51, 22.65, 23.67]
NOVO_FEMALES = [0.15, 0.31, 0.57, 0.95, 1.49, 2.18, 2.99, 3.91, 4.89, 5.91, 6.91,
                7.88, 8.80, 9.67, 10.50, 11.31, 12.12, 12.96]

# Суточный индюшонок: в таблицах производителей массы дня 0 нет. Без неё профиль
# держал бы 0.18 кг (край недели 1) с первого дня — тепло и CO₂ суточной птицы
# завышены втрое. Берём рецензируемое значение: Xin et al. 1998, ур. 6,
# BM(D = 0) = 55.6 г (индюки Nicholas на подстилке) — другой кросс, поэтому
# источник назван отдельно, а не растворён в таблице производителя
DAY0_WEIGHT_G = 55.6
DAY0_SOURCE = {
    "ref": "Xin H., Chepete H.J., Shao J., Sell J.L. (1998) Trans. ASAE 41(5):1489–1498, eq. 6 "
           "(BM at D = 0, Nicholas toms)",
    "value_g": DAY0_WEIGHT_G,
    "url": "https://doi.org/10.13031/2013.17299",
}


# ─── Температура: (первый день, °C) — ступени таблиц ─────────────────────────

# Aviagen Turkeys, Management Guidelines for Commercial Turkeys (CL23/EN V4),
# Table 5 «Target environmental temperatures», с. 21, колонка Whole House Brooding,
# M+F. Диапазоны — НИЖНЕЙ границей (решение владельца 2026-10-26). Дни 4–7:
# «Decrease 1°C per day» — от нижней границы дня 3 (34 °C): 33, 32, 31, 30 —
# наше прочтение (INFERRED); с недели 10 — 16 °C «until depletion»
AVIAGEN_TEMPS = [(1, 36), (2, 35), (3, 34), (4, 33), (5, 32), (6, 31), (7, 30),
                 (8, 27), (15, 25), (22, 23), (29, 21), (36, 20), (43, 19), (50, 18),
                 (57, 17), (64, 16)]

# Hybrid Turkeys, Technical guide for commercial products (Commercial Management
# Guide EN, 2023), «Interior temperature guidelines (separate sexes)», с. 56,
# колонка Whole room brooding WITHOUT radiant heaters (легенда графика с. 57):
# обогрев всего корпуса — то же, что колонка Aviagen. Строка «> 99» — с 99-го дня
HYBRID_MALE_TEMPS = [(1, 35), (8, 31), (15, 28), (22, 25), (29, 23), (36, 22), (43, 20),
                     (50, 20), (57, 19), (64, 18), (71, 17), (78, 16), (85, 15), (92, 15),
                     (99, 14)]
# Самки: таблица кончается строкой 85–91 (18 °C); дальше профиль держит её край
HYBRID_FEMALE_TEMPS = [(1, 35), (8, 31), (15, 28), (22, 25), (29, 23), (36, 22), (43, 20),
                       (50, 19), (57, 18)]


# ─── Влажность ───────────────────────────────────────────────────────────────

# Целевая RH — потолок влагобаланса: верхняя граница допустимого диапазона.
# Aviagen CL23 Table 8 «Air quality», с. 26: RH 50–70 %;
# Hybrid CMG с. 46: 40 % < RH < 60 %
AVIAGEN_RH = 70.0
HYBRID_RH = 60.0


AVIAGEN_WEIGHT_REF = {
    "ref": "Aviagen Turkeys, B.U.T. 6 Commercial Performance Objectives, POCLLB6/EN V2 (2022), Live Weight",
    "page": 1,
    "url": "https://aviagenturkeys.com/wp-content/uploads/2025/08/POCLLB6_V2_BUT-6-Commercial-Goals_UK_2022.pdf",
}
AVIAGEN_CLIMATE = {
    "ref": "Aviagen Turkeys, Management Guidelines for Commercial Turkeys, CL23/EN V4",
    "table": "5", "page": 21, "column": "Whole House Brooding, lower bound",
    "method": "aviagen_turkey_by_age", "source_id": "aviagen_turkey_cl23_t5",
    "url": "https://aviagenturkeys.com/wp-content/uploads/2025/08/"
           "CL23_V4_Management-Guidelines-for-Growing-Commercial-Turkeys_EN.pdf",
}
HYBRID_CLIMATE = {
    "ref": "Hybrid Turkeys, Technical guide for commercial products (Commercial Management Guide EN, 2023)",
    "table": "Interior temperature guidelines (separate sexes)", "page": 56,
    "column": "Whole room brooding without radiant heaters",
    "method": "hybrid_turkey_by_age", "source_id": "hybrid_turkey_cmg_p56",
    "url": "https://www.hendrix-genetics.com/documents/2183/Commercial_Management_Guide_EN.pdf",
}
CONVERTER_WEIGHT_REF = {
    "ref": "Hybrid Turkeys, Performance Goals Converter Commercial {sex} — Metric, NA012023 (2023), Body Weight",
    "page": "1",
    "url": "https://www.hybridturkeys.com/documents/{doc}/ConverterAmericas_CS_Metric_{file}.pdf",
}
NOVO_WEIGHT_REF = {
    "ref": "Hybrid Turkeys, Performance Goals ConverterNOVO Commercial {sex}, 202012 (2020, preliminary, ±5 %)",
    "page": "1",
    "url": "https://www.hybridturkeys.com/documents/{doc}/ConverterNOVO_CS_{file}.pdf",
}


def _step_temp(temps: list[tuple[int, float]], day: int) -> float:
    """Температура ступени, в которую попадает день (день 0 — как день 1)."""
    value = temps[0][1]
    for first_day, t in temps:
        if day >= first_day:
            value = t
    return float(value)


def _points(weights_kg: list[float], temps: list[tuple[int, float]], rh: float) -> list[dict]:
    """
    Точки профиля. Таблица температуры ступенчатая, а профиль интерполирует линейно
    между точками: чтобы ступень осталась ступенью, у каждой ступени две точки —
    первый и последний её день. Масса — на конец недели (день 7·N) и день 0.
    """
    last_day = 7 * len(weights_kg)
    days = {0, last_day} | {7 * (i + 1) for i in range(len(weights_kg))}
    for i, (first_day, _) in enumerate(temps):
        days.add(first_day)
        if i:
            days.add(first_day - 1)
    days = sorted(d for d in days if d <= last_day)

    points = []
    for d in days:
        weight = DAY0_WEIGHT_G if d == 0 else (
            round(weights_kg[d // 7 - 1] * 1000.0, 1) if d % 7 == 0 else None)
        points.append({"day": d, "body_weight_g": weight,
                       "min_temp_c": _step_temp(temps, d), "rv_percent": rh})
    return points


def _profile(pid: str, name: str, breed: str, sex: str, weight_ref: dict, climate: dict,
             norm: str, weights: list[float], temps: list[tuple[int, float]], rh: float) -> dict:
    return {
        "id": pid, "name": name, "breed": breed,
        "species": "turkey", "sex": sex, "min_vent_norm": norm,
        "source": {"weight": {**weight_ref, "basis": sex}, "weight_day0": DAY0_SOURCE,
                   "climate": climate},
        "points": _points(weights, temps, rh),
    }


def build() -> list[dict]:
    # Номер страницы в шаблоне — строка (format), в файле — число, как у бройлеров
    fill = lambda ref, sex, doc, file: {k: int(v) if k == "page" else v.format(sex=sex, doc=doc, file=file)
                                        for k, v in ref.items()}
    conv = lambda sex, doc, file: fill(CONVERTER_WEIGHT_REF, sex, doc, file)
    novo = lambda sex, doc, file: fill(NOVO_WEIGHT_REF, sex, doc, file)
    aviagen = "aviagen_turkey_per_kg"
    hybrid = "hybrid_turkey_per_week"
    return [
        _profile("but6-toms", "B.U.T. 6 — toms", "B.U.T. 6", "male", AVIAGEN_WEIGHT_REF,
                 AVIAGEN_CLIMATE, aviagen, BUT6_MALES, AVIAGEN_TEMPS, AVIAGEN_RH),
        _profile("but6-hens", "B.U.T. 6 — hens", "B.U.T. 6", "female", AVIAGEN_WEIGHT_REF,
                 AVIAGEN_CLIMATE, aviagen, BUT6_FEMALES, AVIAGEN_TEMPS, AVIAGEN_RH),
        _profile("converter-toms", "Converter — toms", "Hybrid Converter", "male",
                 conv("Males", 1908, "Male"), HYBRID_CLIMATE, hybrid,
                 CONVERTER_MALES, HYBRID_MALE_TEMPS, HYBRID_RH),
        _profile("converter-hens", "Converter — hens", "Hybrid Converter", "female",
                 conv("Females", 1907, "Female"), HYBRID_CLIMATE, hybrid,
                 CONVERTER_FEMALES, HYBRID_FEMALE_TEMPS, HYBRID_RH),
        _profile("converter-novo-toms", "ConverterNOVO — toms", "Hybrid ConverterNOVO", "male",
                 novo("Males", 885, "Males"), HYBRID_CLIMATE, hybrid,
                 NOVO_MALES, HYBRID_MALE_TEMPS, HYBRID_RH),
        _profile("converter-novo-hens", "ConverterNOVO — hens", "Hybrid ConverterNOVO", "female",
                 novo("Females", 886, "Females"), HYBRID_CLIMATE, hybrid,
                 NOVO_FEMALES, HYBRID_FEMALE_TEMPS, HYBRID_RH),
    ]


if __name__ == "__main__":
    for profile in build():
        path = OUT / f"{profile['id']}.json"
        path.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(path.relative_to(OUT.parents[2]), len(profile["points"]), "points")
