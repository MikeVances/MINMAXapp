"""
Тепло бройлеров на уровне КОРПУСА (CIGR 2002) — одна модель для всех балансов.

До аудита 2026-10-18 в коде было две несогласованные модели:
  • тепловой баланс (Qmax, горелки) брал явное тепло на уровне ПТИЦЫ 6.90·W^0.75
    (65 % полного) — без учёта того, что часть тепла уходит на испарение влаги
    из подстилки и воздух не греет;
  • влажностный баланс брал долю явного тепла на уровне КОРПУСА, но скрытое
    тепло считал от полного тепла БЕЗ температурной поправки.
В сумме тепла выходило больше 100 %, а скрытое тепло при 32 °C было завышено
в 1.45 раза. Здесь — одна модель, из которой берут и Qmax, и горелки, и влага.

Источник: CIGR Working Group (2002) «Heat and moisture production at animal and
house levels», в изложении Aarnink (CIGR Journal, art. 4781):
  ур. 11:  Q_total(20 °C) = 10.62 · W^0.75                                  [Вт/гол]
  ур. 13:  Q_sensible = [0.61 · (1000 + 20·(20 − T)) − 0.228 · T²] · Q_total / 1000
           «Q_total — полное тепло, скорректированное по температуре».
Поправку полного тепла (1000 + 20·(20 − T)) / 1000 — +2 % на каждый градус ниже
20 °C — ВЫВОДИМ из той же формулы: у свиней в ур. 5 стоит (1000 + 12·(20 − T)),
и статья прямо называет это поправкой 1.2 %/°C. Статус: INFERRED (сильная
аналогия), не прямая цитата для бройлеров.

Ограничение (Aarnink): формула не зависит от массы птицы и в первые недели
переоценивает скрытую долю (в термонейтральной зоне цыплята испаряют мало) —
для влажностного Qmin это ошибка в безопасную сторону.

Норма CO₂ (ventilation_calc, CIGR 1984) этой поправкой намеренно не меняется:
она сверена с таблицей Aviagen 2018 в пределах ~10 %.

Индейка (с 2026-10-26): полное тепло — свой закон CIGR 2002, §2.7.4, ур. 19:
Q_total(20 °C) = 9.86 · m^0.77 (Chepete & Xin 2002, индейка 1992–1998). Своей
формулы доли явного тепла на уровне корпуса у индейки в CIGR нет — берём бройлерную
ур. 13 (тоже подстилка): решение владельца, в ответе — пометка turkey_sensible_from_broiler.
Сверка (косвенная): у индюка 8.9 кг при 18 °C явное тепло 69 % полного (Ota & McNally
1961, NC State AG-775, табл. 1), ур. 13 при 18 °C даёт 0.61·1040 − 74 = 560 из 1040 —
54 %. Сравнение не прямое: камера Ota & McNally — уровень ПТИЦЫ, без испарения из
подстилки, а ур. 13 — уровень корпуса. Если у индейки подстилка испаряет меньше, чем
у бройлера, формула занижает явное тепло, а с ним летний Qmax.
"""

from __future__ import annotations

from dataclasses import dataclass

# ур. 11: полное тепло при 20 °C, Вт на (кг живой массы)^0.75
TOTAL_HEAT_COEFF_20C = 10.62

BROILER = "broiler"
TURKEY = "turkey"

# Полное тепло при 20 °C по виду птицы: (коэффициент, показатель степени массы).
# Бройлер — CIGR 2002 ур. 11 (как и раньше); индейка — CIGR 2002 ур. 19
SPECIES_TOTAL_HEAT_20C = {
    BROILER: (TOTAL_HEAT_COEFF_20C, 0.75),
    TURKEY: (9.86, 0.77),
}


def total_heat_20c_w(weight_kg: float, species: str = BROILER) -> float:
    """Полное тепло одной птицы при 20 °C, Вт. Неизвестный вид — ошибка, а не бройлер."""
    coeff, exponent = SPECIES_TOTAL_HEAT_20C[species]
    return coeff * max(weight_kg, 0.0) ** exponent

# Теплота парообразования воды при температуре корпуса, Дж/г (~25 °C)
LATENT_HEAT_J_PER_G = 2430.0


def total_heat_factor(t_inside_c: float) -> float:
    """Полное тепло при T относительно 20 °C: +2 % на градус ниже, −2 % выше (не < 0)."""
    return max(0.0, (1000.0 + 20.0 * (20.0 - t_inside_c)) / 1000.0)


def house_sensible_fraction(t_inside_c: float) -> float:
    """
    Явное тепло корпуса в долях полного тепла ПРИ 20 °C (ур. 13 без множителя
    Q_total/1000): 0.519 при 20 °C, 0.407 при 25 °C, 0.230 при 32 °C.
    Сравнивать её с total_heat_factor(T), а не с 1: скрытое = factor − fraction.
    """
    s = (0.61 * (1000.0 + 20.0 * (20.0 - t_inside_c)) - 0.228 * t_inside_c ** 2) / 1000.0
    return min(max(s, 0.0), total_heat_factor(t_inside_c))


@dataclass(frozen=True)
class HouseHeat:
    """Тепло на одну птицу на уровне корпуса, Вт."""
    total_w: float      # полное, с температурной поправкой
    sensible_w: float   # греет воздух — для Qmax и горелок
    latent_w: float     # уходит с паром (дыхание + подстилка) — для влажностного Qmin

    @property
    def vapour_g_per_h(self) -> float:
        """Пар, г/ч на птицу: скрытое тепло / теплота парообразования."""
        return self.latent_w * 3600.0 / LATENT_HEAT_J_PER_G


# Доля явного тепла на уровне ПТИЦЫ в термонейтральной зоне — Aarnink et al.,
# CIGR Journal art. 4781 (2018), разд. 3: «a constant level of fQs during the
# growing period of 0.67 might be assumed». Без испарения из подстилки — модель
# клеток с помётом на лентах, верхний край явного тепла (см. docs/api/v1/README.md,
# «Клетки»). Вне термонейтральной зоны птица отдаёт больше пара, явная доля
# ниже — значит 0.67 завышает явное тепло: для летнего Qmax это безопасная сторона.
ANIMAL_LEVEL_SENSIBLE_FRACTION = 0.67


def animal_heat_per_bird(weight_kg: float, t_inside_c: float, species: str = BROILER) -> HouseHeat:
    """Тепло одной птицы на уровне ПТИЦЫ: полное — как у корпуса, явное — 0.67 полного."""
    total = total_heat_20c_w(weight_kg, species) * total_heat_factor(t_inside_c)
    sensible = ANIMAL_LEVEL_SENSIBLE_FRACTION * total
    return HouseHeat(total_w=total, sensible_w=sensible, latent_w=total - sensible)


def house_heat_per_bird(weight_kg: float, t_inside_c: float, species: str = BROILER) -> HouseHeat:
    """Явное и скрытое тепло одной птицы массой weight_kg при температуре корпуса T."""
    q20 = total_heat_20c_w(weight_kg, species)
    total = q20 * total_heat_factor(t_inside_c)
    sensible = q20 * house_sensible_fraction(t_inside_c)
    return HouseHeat(total_w=total, sensible_w=sensible, latent_w=total - sensible)
