"""
Модели данных для управления стадом птицы.

Эти модели используются для:
- Хранения информации о стаде (FlockInfo)
- Ведения ежедневного дневника показателей (FlockDiaryEntry)
- Аналитики план vs факт
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import date, datetime
from typing import Optional


@dataclass
class FlockInfo:
    """
    Информация о стаде в конкретном птичнике.

    Это базовые параметры, которые задаются при посадке птицы
    и определяют цикл выращивания.
    """
    house_id: str                    # ID птичника (A-1, B-2, и т.д.)
    flock_name: str                  # Название партии/стада
    placement_date: str              # Дата посадки (ISO format: "2025-10-15")
    initial_bird_count: int          # Начальное поголовье
    target_days: int = 42            # Целевая длительность цикла (обычно 42)

    # Опциональные параметры
    breed: Optional[str] = None      # Кросс птицы (Ross 308, Cobb 500, и т.д.)
    notes: Optional[str] = None      # Примечания

    # Метаданные
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    def to_dict(self) -> dict:
        """Преобразовать в словарь для JSON сериализации."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> FlockInfo:
        """Создать объект из словаря."""
        return cls(**{k: v for k, v in data.items() if k in cls.__annotations__})

    def get_current_day(self) -> int:
        """
        Вычислить текущий день цикла на основе даты посадки.

        Returns:
            Номер дня (1-42+), или 0 если дата посадки в будущем
        """
        try:
            placement = datetime.fromisoformat(self.placement_date).date()
            today = date.today()
            delta = (today - placement).days + 1  # День 1 = день посадки
            return max(0, delta)
        except (ValueError, TypeError):
            return 0


@dataclass
class FlockDiaryEntry:
    """
    Запись в дневнике стада (фактические показатели за день).

    Пользователь вносит эти данные ежедневно для отслеживания
    производительности стада и сравнения с плановыми показателями.
    """
    house_id: str                           # ID птичника
    date: str                               # Дата записи (ISO: "2025-10-27")
    day_of_cycle: int                       # День цикла (1-42)

    # Фактические показатели
    actual_weight_g: Optional[float] = None      # Фактический вес птицы (г)
    mortality_count: Optional[int] = None        # Падёж за день (голов)
    feed_consumption_kg: Optional[float] = None  # Расход корма за день (кг)
    temp_inside_c: Optional[float] = None        # Температура внутри помещения (°C)
    notes: Optional[str] = None                  # Примечания

    # Метаданные
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    def to_dict(self) -> dict:
        """Преобразовать в словарь для JSON сериализации."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> FlockDiaryEntry:
        """Создать объект из словаря."""
        return cls(**{k: v for k, v in data.items() if k in cls.__annotations__})

    def validate(self) -> list[str]:
        """
        Валидация данных записи.

        Returns:
            Список ошибок валидации (пустой если всё ОК)
        """
        errors = []

        if self.day_of_cycle < 1 or self.day_of_cycle > 100:
            errors.append(f"День цикла должен быть в диапазоне 1-100, получено: {self.day_of_cycle}")

        if self.actual_weight_g is not None:
            if self.actual_weight_g < 0 or self.actual_weight_g > 10000:
                errors.append(f"Вес должен быть в диапазоне 0-10000г, получено: {self.actual_weight_g}")

        if self.mortality_count is not None:
            if self.mortality_count < 0:
                errors.append(f"Падёж не может быть отрицательным: {self.mortality_count}")

        if self.feed_consumption_kg is not None:
            if self.feed_consumption_kg < 0:
                errors.append(f"Расход корма не может быть отрицательным: {self.feed_consumption_kg}")

        if self.temp_inside_c is not None:
            if self.temp_inside_c < -20 or self.temp_inside_c > 60:
                errors.append(f"Температура должна быть в диапазоне -20..60°C, получено: {self.temp_inside_c}")

        return errors


@dataclass
class PlanVsFactData:
    """
    Данные для сравнения плановых и фактических показателей.

    Используется для построения графиков и аналитики.
    """
    days: list[int]                      # Дни цикла [1, 2, 3, ..., 42]
    plan_weight: list[Optional[float]]   # Плановый вес по дням
    actual_weight: list[Optional[float]] # Фактический вес по дням
    delta: list[Optional[float]]         # Отклонение (факт - план)

    def to_dict(self) -> dict:
        """Преобразовать в словарь для JSON сериализации."""
        return asdict(self)


@dataclass
class AnalyticsSummary:
    """
    Сводная аналитика по стаду.

    Автоматически рассчитывается на основе дневника и планового профиля.
    """
    house_id: str
    current_day: int

    # Показатели веса
    avg_daily_gain_g: Optional[float] = None        # Средний привес в день (г)
    weight_deviation_g: Optional[float] = None      # Отклонение веса от плана (г)
    weight_deviation_pct: Optional[float] = None    # Отклонение веса от плана (%)
    projected_final_weight_g: Optional[float] = None # Прогноз веса к 42 дню

    # Показатели падежа
    cumulative_mortality: int = 0                   # Кумулятивный падёж (голов)
    mortality_rate_pct: Optional[float] = None      # Процент падежа от стартового поголовья
    current_bird_count: Optional[int] = None        # Текущее поголовье

    # Показатели корма (опционально)
    total_feed_consumed_kg: Optional[float] = None  # Общий расход корма (кг)
    avg_feed_per_bird_kg: Optional[float] = None    # Средний расход на голову (кг)

    def to_dict(self) -> dict:
        """Преобразовать в словарь для JSON сериализации."""
        return asdict(self)
