"""
Модуль аналитики для сравнения плановых и фактических показателей стада.

Основные функции:
- get_plan_vs_fact_data() - данные для графика план vs факт
- get_analytics_summary() - сводная аналитика (метрики)
"""

from __future__ import annotations

from typing import Optional

from ..models.flock import PlanVsFactData, AnalyticsSummary
from ..core import flock_storage
from ..core.day_master import load_day_master


def get_plan_vs_fact_data(house_id: str, target_days: int = 42) -> PlanVsFactData:
    """
    Получить данные для графика план vs факт.

    Объединяет плановый профиль (day_master) с фактическими данными
    из дневника стада.

    Args:
        house_id: ID птичника
        target_days: Количество дней для анализа (обычно 42)

    Returns:
        PlanVsFactData с массивами данных для графика

    Raises:
        ValueError: Если не удалось загрузить данные
    """
    # Загрузить плановый профиль
    day_master = load_day_master()
    if not day_master:
        raise ValueError("Plan profile (day_master) is empty or not configured")

    # Загрузить фактические записи дневника
    diary_entries = flock_storage.load_diary_entries(house_id, from_day=1, to_day=target_days)

    # Создать словарь фактических данных по дням
    actual_by_day = {entry.day_of_cycle: entry for entry in diary_entries}

    # Подготовить массивы данных
    days = list(range(1, target_days + 1))
    plan_weight = []
    actual_weight = []
    delta = []

    for day in days:
        # Плановый вес
        plan_info = day_master.get(day)
        plan_w = plan_info.body_weight_g if plan_info else None
        plan_weight.append(plan_w)

        # Фактический вес
        actual_entry = actual_by_day.get(day)
        actual_w = actual_entry.actual_weight_g if actual_entry else None
        actual_weight.append(actual_w)

        # Отклонение (факт - план)
        if actual_w is not None and plan_w is not None:
            delta.append(actual_w - plan_w)
        else:
            delta.append(None)

    return PlanVsFactData(
        days=days,
        plan_weight=plan_weight,
        actual_weight=actual_weight,
        delta=delta,
    )


def get_analytics_summary(house_id: str) -> AnalyticsSummary:
    """
    Получить сводную аналитику по стаду.

    Вычисляет ключевые метрики:
    - Средний привес в день
    - Отклонение веса от плана
    - Прогноз финального веса
    - Кумулятивный падёж и процент
    - Текущее поголовье

    Args:
        house_id: ID птичника

    Returns:
        AnalyticsSummary с рассчитанными метриками

    Raises:
        ValueError: Если нет информации о стаде
    """
    # Загрузить информацию о стаде
    flock_info = flock_storage.load_flock_info(house_id)
    if flock_info is None:
        raise ValueError(f"Flock info not found for house '{house_id}'")

    current_day = flock_info.get_current_day()

    # Загрузить дневник
    diary_entries = flock_storage.load_diary_entries(house_id, from_day=1, to_day=current_day)

    # Загрузить плановый профиль
    day_master = load_day_master()

    # Инициализация метрик
    avg_daily_gain_g: Optional[float] = None
    weight_deviation_g: Optional[float] = None
    weight_deviation_pct: Optional[float] = None
    projected_final_weight_g: Optional[float] = None
    cumulative_mortality = 0
    mortality_rate_pct: Optional[float] = None
    current_bird_count: Optional[int] = None
    total_feed_consumed_kg: Optional[float] = None
    avg_feed_per_bird_kg: Optional[float] = None

    # === Расчёт падежа ===
    for entry in diary_entries:
        if entry.mortality_count is not None:
            cumulative_mortality += entry.mortality_count

    current_bird_count = flock_info.initial_bird_count - cumulative_mortality

    if flock_info.initial_bird_count > 0:
        mortality_rate_pct = (cumulative_mortality / flock_info.initial_bird_count) * 100.0

    # === Расчёт среднего привеса ===
    weights_with_days = [(e.day_of_cycle, e.actual_weight_g) for e in diary_entries if e.actual_weight_g is not None]

    if len(weights_with_days) >= 2:
        # Взять первую и последнюю записи
        first_day, first_weight = weights_with_days[0]
        last_day, last_weight = weights_with_days[-1]

        if last_day > first_day:
            avg_daily_gain_g = (last_weight - first_weight) / (last_day - first_day)

    # === Отклонение веса от плана ===
    if weights_with_days:
        last_day, last_weight = weights_with_days[-1]
        plan_info = day_master.get(last_day)

        if plan_info and plan_info.body_weight_g is not None:
            plan_weight = plan_info.body_weight_g
            weight_deviation_g = last_weight - plan_weight

            if plan_weight > 0:
                weight_deviation_pct = (weight_deviation_g / plan_weight) * 100.0

    # === Прогноз финального веса (линейная экстраполяция) ===
    if avg_daily_gain_g is not None and weights_with_days:
        last_day, last_weight = weights_with_days[-1]
        target_day = flock_info.target_days
        days_remaining = target_day - last_day

        if days_remaining > 0:
            projected_final_weight_g = last_weight + (avg_daily_gain_g * days_remaining)
        else:
            projected_final_weight_g = last_weight

    # === Расход корма ===
    total_feed = 0.0
    for entry in diary_entries:
        if entry.feed_consumption_kg is not None:
            total_feed += entry.feed_consumption_kg

    if total_feed > 0:
        total_feed_consumed_kg = total_feed

        if current_bird_count and current_bird_count > 0:
            avg_feed_per_bird_kg = total_feed / current_bird_count

    return AnalyticsSummary(
        house_id=house_id,
        current_day=current_day,
        avg_daily_gain_g=avg_daily_gain_g,
        weight_deviation_g=weight_deviation_g,
        weight_deviation_pct=weight_deviation_pct,
        projected_final_weight_g=projected_final_weight_g,
        cumulative_mortality=cumulative_mortality,
        mortality_rate_pct=mortality_rate_pct,
        current_bird_count=current_bird_count,
        total_feed_consumed_kg=total_feed_consumed_kg,
        avg_feed_per_bird_kg=avg_feed_per_bird_kg,
    )
