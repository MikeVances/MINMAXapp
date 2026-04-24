"""
Модуль интерполяции для заполнения профиля роста.

Основная функция: interpolate_to_42_days()
Принимает 7 опорных точек (дни 1, 7, 14, 21, 28, 35, 42)
и возвращает полный профиль на 42 дня с линейной интерполяцией.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from ..core.day_master import DayInfo


# Стандартные опорные дни (понедельный профиль)
ANCHOR_DAYS = [1, 7, 14, 21, 28, 35, 42]


def _linear_interpolate(x: float, x1: float, y1: float, x2: float, y2: float) -> float:
    """
    Линейная интерполяция между двумя точками.

    Args:
        x: Значение X для интерполяции
        x1, y1: Первая точка
        x2, y2: Вторая точка

    Returns:
        Интерполированное значение Y
    """
    if x2 == x1:
        return y1

    t = (x - x1) / (x2 - x1)
    return y1 + (y2 - y1) * t


def _interpolate_field(
    anchor_values: Dict[int, Optional[float]],
    target_day: int,
    anchor_days: List[int]
) -> Optional[float]:
    """
    Интерполировать значение поля для конкретного дня.

    Args:
        anchor_values: Словарь {день: значение} для опорных точек
        target_day: День, для которого нужно получить значение
        anchor_days: Список опорных дней (например [1, 7, 14, 21, 28, 35, 42])

    Returns:
        Интерполированное значение или None, если невозможно интерполировать
    """
    # Если target_day — это опорный день, вернуть значение напрямую
    if target_day in anchor_values:
        return anchor_values[target_day]

    # Найти ближайшие опорные точки слева и справа
    left_day = None
    right_day = None

    for day in sorted(anchor_days):
        if day < target_day:
            left_day = day
        elif day > target_day and right_day is None:
            right_day = day
            break

    # Если не удалось найти границы — вернуть None
    if left_day is None or right_day is None:
        return None

    left_value = anchor_values.get(left_day)
    right_value = anchor_values.get(right_day)

    # Если одно из значений None — вернуть None
    if left_value is None or right_value is None:
        return None

    # Линейная интерполяция
    return _linear_interpolate(
        float(target_day),
        float(left_day),
        left_value,
        float(right_day),
        right_value
    )


def interpolate_to_42_days(anchor_points: Dict[int, DayInfo]) -> Dict[int, DayInfo]:
    """
    Интерполировать 7 опорных точек до полного профиля на 42 дня.

    Принимает словарь с опорными точками (обычно 7: дни 1, 7, 14, 21, 28, 35, 42)
    и возвращает словарь с 42 днями, где промежуточные значения
    интерполированы линейно.

    Args:
        anchor_points: Словарь {день: DayInfo} для опорных точек
                       Минимум 2 точки, рекомендуется 7

    Returns:
        Словарь {день: DayInfo} для всех 42 дней

    Raises:
        ValueError: Если меньше 2 опорных точек или нет дня 1 и дня 42

    Example:
        >>> anchors = {
        ...     1: DayInfo(day=1, body_weight_g=52, min_temp_c=33),
        ...     7: DayInfo(day=7, body_weight_g=228, min_temp_c=30.5),
        ...     42: DayInfo(day=42, body_weight_g=2364, min_temp_c=19)
        ... }
        >>> full_profile = interpolate_to_42_days(anchors)
        >>> len(full_profile)
        42
        >>> full_profile[14].body_weight_g  # Интерполировано
        434.0
    """
    if len(anchor_points) < 2:
        raise ValueError("At least 2 anchor points required for interpolation")

    # Проверить, что есть день 1 и день 42 (критически важно)
    if 1 not in anchor_points:
        raise ValueError("Day 1 must be present in anchor points")
    if 42 not in anchor_points:
        raise ValueError("Day 42 must be present in anchor points")

    anchor_days = sorted(anchor_points.keys())

    # Подготовить словари значений для интерполяции
    weights = {day: info.body_weight_g for day, info in anchor_points.items()}
    temps = {day: info.min_temp_c for day, info in anchor_points.items()}
    rvs = {day: info.rv_percent for day, info in anchor_points.items()}

    # Результирующий словарь
    result: Dict[int, DayInfo] = {}

    # Интерполировать для всех дней 1-42
    for day in range(1, 43):
        interpolated_weight = _interpolate_field(weights, day, anchor_days)
        interpolated_temp = _interpolate_field(temps, day, anchor_days)
        interpolated_rv = _interpolate_field(rvs, day, anchor_days)

        result[day] = DayInfo(
            day=day,
            body_weight_g=interpolated_weight,
            min_temp_c=interpolated_temp,
            rv_percent=interpolated_rv
        )

    return result


def extract_anchor_points(full_profile: Dict[int, DayInfo], anchor_days: List[int] = None) -> Dict[int, DayInfo]:
    """
    Извлечь опорные точки из полного профиля.

    Обратная операция к interpolate_to_42_days().
    Используется для получения 7 опорных точек из полного профиля на 42 дня.

    Args:
        full_profile: Полный профиль {день: DayInfo}
        anchor_days: Список дней для извлечения (по умолчанию [1, 7, 14, 21, 28, 35, 42])

    Returns:
        Словарь {день: DayInfo} только для опорных дней

    Example:
        >>> full = {day: DayInfo(day=day, body_weight_g=50+day*10) for day in range(1, 43)}
        >>> anchors = extract_anchor_points(full)
        >>> list(anchors.keys())
        [1, 7, 14, 21, 28, 35, 42]
    """
    if anchor_days is None:
        anchor_days = ANCHOR_DAYS

    return {day: full_profile[day] for day in anchor_days if day in full_profile}


def validate_anchor_points(anchor_points: Dict[int, DayInfo]) -> List[str]:
    """
    Валидация опорных точек.

    Проверяет:
    - Наличие минимум 2 точек
    - Наличие дня 1 и дня 42
    - Корректность значений (вес должен расти, температура падать)

    Args:
        anchor_points: Словарь опорных точек

    Returns:
        Список ошибок валидации (пустой если всё ОК)
    """
    errors = []

    if len(anchor_points) < 2:
        errors.append("Требуется минимум 2 опорные точки")

    if 1 not in anchor_points:
        errors.append("Отсутствует день 1 (обязательный)")

    if 42 not in anchor_points:
        errors.append("Отсутствует день 42 (обязательный)")

    # Проверить монотонность роста веса
    sorted_days = sorted(anchor_points.keys())
    for i in range(len(sorted_days) - 1):
        day1 = sorted_days[i]
        day2 = sorted_days[i + 1]

        w1 = anchor_points[day1].body_weight_g
        w2 = anchor_points[day2].body_weight_g

        if w1 is not None and w2 is not None:
            if w2 < w1:
                errors.append(f"Вес должен расти: день {day1} ({w1}г) > день {day2} ({w2}г)")

    # Проверить, что температура не растёт (обычно падает)
    for i in range(len(sorted_days) - 1):
        day1 = sorted_days[i]
        day2 = sorted_days[i + 1]

        t1 = anchor_points[day1].min_temp_c
        t2 = anchor_points[day2].min_temp_c

        if t1 is not None and t2 is not None:
            if t2 > t1 + 1:  # Допуск +1°C
                errors.append(f"Температура не должна расти: день {day1} ({t1}°C) < день {day2} ({t2}°C)")

    return errors
