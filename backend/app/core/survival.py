"""
Доля живой птицы на день цикла — одна формула для всего приложения.

Раньше падёж считался в трёх местах по-разному: с зашитыми 41 днями в расчёте
и с cycle_days − 1 в сводке. При цикле 49 дней одна и та же партия на 49-й день
давала разное поголовье в разных частях приложения.

Модель: постоянный суточный падёж, подобранный так, чтобы к последнему дню
цикла выжило ровно (1 − total) от посадки:
    survival(day) = (1 − total) ^ ((day − 1) / (cycle_days − 1))
День 1 — день посадки (survival = 1). После конца цикла падёж продолжается
с тем же суточным темпом.
"""

from __future__ import annotations


def survival_fraction(day: int, total_mortality_pct: float, cycle_days: int) -> float:
    total = min(max(total_mortality_pct, 0.0), 100.0) / 100.0
    if total >= 1.0:
        return 0.0 if day > 1 else 1.0
    span = max(cycle_days - 1, 1)
    return (1.0 - total) ** (max(day - 1, 0) / span)


def daily_mortality_to_total(daily_pct: float, cycle_days: int) -> float:
    """Перевод старого формата настроек (падёж %/сутки) в падёж за цикл, %."""
    daily = min(max(daily_pct, 0.0), 100.0) / 100.0
    return (1.0 - (1.0 - daily) ** max(cycle_days - 1, 1)) * 100.0
