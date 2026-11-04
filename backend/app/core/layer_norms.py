"""
Нормы содержания ремонтного молодняка и промышленной несушки в клетках
(species="layer", housing="cages").

Первоисточники в репозитории (refs/layers/):
  • CIGR 4th Workgroup Report (2002):
      - §2.7.2, ур. 17 (с. 12): Φ_tot(20 °C) = 6.28 · m^0.75 + 25 · Y₂ [Вт/гол]
      - §2.10, ур. 26 (с. 18):  Φ_tot(t) = Φ_tot(20 °C) · [1000 + 20·(20 − t)] / 1000
      - §3.3.2, ур. 34 (с. 26–27, Pedersen et al., 1998, клеточный зал несушек):
        Φ_s(t) = Φ_tot(20 °C) · [0.67 · (1000 + 20·(20 − t)) − 9.8·10⁻⁸ · t⁶] / 1000
  • Lohmann Tierzucht — Management Guide Cage Housing (LSL-Classic & Brown-Classic):
      - Табл. 1 (с. 10): температура на уровне птицы по возрасту и RH 60–70 %
      - Табл. 17 (с. 34–35): живая масса по неделям 1–95
      - Табл. 18 (с. 38–39): суточная яйцемасса Y₂ (Egg Mass g/H.D.) по неделям 19–72+
  • Hy-Line International — Performance Standards Guide, Conventional Systems:
      - Hy-Line Brown (Dec 2025, с. 4–6, 9) и Hy-Line W-36 (Jan 2020, с. 4–6, 9)
      - Hy-Line Brown Management Guide (Nov 2018, с. 17): таблица воздухообмена
        д-ра Х. Синя (Dr. Hongwei Xin, Iowa State University), м³/ч на 1000 голов:
        строка зимнего минимума (−12…−23 °C): 1 нед. — 75, 3 нед. — 110,
        6 нед. — 210, 12 нед. — 400, 18 нед. — 600, 19+ нед. — 700–850.
  • Hendrix Genetics — Commercial Management Guide Cage Housing (§7.9, с. 47):
      - Минимальный воздухообмен 0.7 м³/ч на 1 кг живой массы.

Этапы содержания (stage):
  • rearing    — ремонтный молодняк несушки в клетках (1–17 недель = 1–119 суток;
                 допускается до 20 недель = 140 суток при поздней пересадке); Y₂ = 0.
  • production — промышленное стадо (яйцекладка в клетках, с 18-й недели = 120 суток
                 до 72–100 недель = 504–700 суток); живая масса стабильна, Y₂ > 0.
"""
from __future__ import annotations

REARING = "rearing"
PRODUCTION = "production"
STAGES = (REARING, PRODUCTION)

# Стандартный возраст перевода молодняка несушки в промышленный зал — 17 недель (119 сут)
REARING_LAST_DAY = 119
MAX_REARING_DAYS = 140
MAX_PRODUCTION_DAYS = 700

HYLINE_2018_XIN = "hyline_2018_xin"
HENDRIX_CAGE_07 = "hendrix_cage_07"
GUIDE_NORMS = (HYLINE_2018_XIN, HENDRIX_CAGE_07)

GUIDE_NORM_SOURCE: dict[str, str] = {
    HYLINE_2018_XIN: "hyline_2018_xin_vent",
    HENDRIX_CAGE_07: "hendrix_cage_2018_vent",
}

# Hy-Line Brown Commercial Layers Management Guide (2018), p. 17 (Dr. Hongwei Xin,
# Iowa State University): минимальный воздухообмен при ≤ −12 °C, м³/ч на 1 голову
# по возрасту (день → м³/ч/гол; для 19+ нед. взят нижний край вилки 700–850 на 1000 гол.)
XIN_MIN_VENT_NODES_M3H: tuple[tuple[int, float], ...] = (
    (7, 0.075),
    (21, 0.110),
    (42, 0.210),
    (84, 0.400),
    (126, 0.600),
    (133, 0.700),
)

HENDRIX_MIN_VENT_M3H_PER_KG = 0.70


def xin_per_bird_m3h(age_days: int) -> float:
    """Линейная интерполяция зимнего минимума д-ра Х. Синя (Hy-Line 2018, с. 17) по возрасту, м³/ч/гол."""
    d = max(1, int(age_days))
    if d <= XIN_MIN_VENT_NODES_M3H[0][0]:
        return XIN_MIN_VENT_NODES_M3H[0][1]
    if d >= XIN_MIN_VENT_NODES_M3H[-1][0]:
        return XIN_MIN_VENT_NODES_M3H[-1][1]
    for (d0, v0), (d1, v1) in zip(XIN_MIN_VENT_NODES_M3H, XIN_MIN_VENT_NODES_M3H[1:]):
        if d0 <= d <= d1:
            if d1 == d0:
                return v0
            return v0 + (v1 - v0) * (d - d0) / (d1 - d0)
    return XIN_MIN_VENT_NODES_M3H[-1][1]


def guide_min_vent_m3h(norm: str, birds: float, weight_kg: float, age_days: int) -> float:
    """Норма минимальной вентиляции руководства кросса для несушек/молодняка, м³/ч на стадо."""
    if norm == HYLINE_2018_XIN:
        return max(birds, 0.0) * xin_per_bird_m3h(age_days)
    if norm == HENDRIX_CAGE_07:
        return max(birds, 0.0) * max(weight_kg, 0.0) * HENDRIX_MIN_VENT_M3H_PER_KG
    raise ValueError(f"Unknown layer min_vent_norm: {norm!r}")
