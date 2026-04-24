"""
Файловое хранилище для данных о стадах.

Использует JSON файлы для хранения:
- Информации о стадах (FlockInfo)
- Записей дневника (FlockDiaryEntry)

Структура файлов:
    data/flocks/
        house_A1_info.json       # Информация о стаде в птичнике A-1
        house_A1_diary.json      # Дневник стада в птичнике A-1
        house_B2_info.json
        house_B2_diary.json
        ...
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional, List

from ..models.flock import FlockInfo, FlockDiaryEntry


# Базовая директория для данных о стадах
FLOCKS_DATA_DIR = Path(os.getenv("FLOCKS_DATA_DIR", "data/flocks"))


def _ensure_flocks_dir():
    """Создать директорию для данных, если её нет."""
    FLOCKS_DATA_DIR.mkdir(parents=True, exist_ok=True)


def _sanitize_house_id(house_id: str) -> str:
    """
    Преобразовать house_id в безопасное имя файла.

    Заменяет небезопасные символы на подчёркивание.
    """
    return "".join(c if c.isalnum() or c in ('-', '_') else '_' for c in house_id)


def _get_info_path(house_id: str) -> Path:
    """Путь к файлу с информацией о стаде."""
    safe_id = _sanitize_house_id(house_id)
    return FLOCKS_DATA_DIR / f"house_{safe_id}_info.json"


def _get_diary_path(house_id: str) -> Path:
    """Путь к файлу с дневником стада."""
    safe_id = _sanitize_house_id(house_id)
    return FLOCKS_DATA_DIR / f"house_{safe_id}_diary.json"


# ============================================================================
# FlockInfo — Информация о стаде
# ============================================================================

def save_flock_info(house_id: str, info: FlockInfo) -> None:
    """
    Сохранить информацию о стаде.

    Args:
        house_id: ID птичника
        info: Информация о стаде

    Raises:
        IOError: Если не удалось сохранить файл
    """
    _ensure_flocks_dir()

    # Установить метаданные
    now = datetime.utcnow().isoformat() + "Z"
    if info.created_at is None:
        info.created_at = now
    info.updated_at = now

    path = _get_info_path(house_id)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(info.to_dict(), f, ensure_ascii=False, indent=2)
    except Exception as e:
        raise IOError(f"Failed to save flock info for {house_id}: {e}")


def load_flock_info(house_id: str) -> Optional[FlockInfo]:
    """
    Загрузить информацию о стаде.

    Args:
        house_id: ID птичника

    Returns:
        FlockInfo или None, если файл не существует

    Raises:
        ValueError: Если файл повреждён или формат некорректен
    """
    path = _get_info_path(house_id)
    if not path.exists():
        return None

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return FlockInfo.from_dict(data)
    except json.JSONDecodeError as e:
        raise ValueError(f"Corrupted flock info file for {house_id}: {e}")
    except Exception as e:
        raise ValueError(f"Failed to load flock info for {house_id}: {e}")


def delete_flock_info(house_id: str) -> bool:
    """
    Удалить информацию о стаде.

    Args:
        house_id: ID птичника

    Returns:
        True если файл был удалён, False если файла не было
    """
    path = _get_info_path(house_id)
    if path.exists():
        path.unlink()
        return True
    return False


# ============================================================================
# FlockDiaryEntry — Дневник стада
# ============================================================================

def save_diary_entry(house_id: str, entry: FlockDiaryEntry) -> None:
    """
    Добавить или обновить запись в дневнике.

    Если запись за этот день уже существует — она будет перезаписана.

    Args:
        house_id: ID птичника
        entry: Запись дневника

    Raises:
        IOError: Если не удалось сохранить файл
    """
    _ensure_flocks_dir()

    # Установить метаданные
    now = datetime.utcnow().isoformat() + "Z"
    existing_entries = load_diary_entries(house_id)

    # Найти существующую запись за этот день
    entry_index = None
    for i, e in enumerate(existing_entries):
        if e.day_of_cycle == entry.day_of_cycle:
            entry_index = i
            # Сохраняем created_at
            if e.created_at:
                entry.created_at = e.created_at
            break

    if entry.created_at is None:
        entry.created_at = now
    entry.updated_at = now

    # Обновить или добавить запись
    if entry_index is not None:
        existing_entries[entry_index] = entry
    else:
        existing_entries.append(entry)

    # Отсортировать по дню
    existing_entries.sort(key=lambda e: e.day_of_cycle)

    # Сохранить
    path = _get_diary_path(house_id)
    try:
        with open(path, "w", encoding="utf-8") as f:
            data = [e.to_dict() for e in existing_entries]
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        raise IOError(f"Failed to save diary entry for {house_id}: {e}")


def load_diary_entries(house_id: str, from_day: int = 1, to_day: int = 100) -> List[FlockDiaryEntry]:
    """
    Загрузить записи дневника.

    Args:
        house_id: ID птичника
        from_day: Начальный день (включительно)
        to_day: Конечный день (включительно)

    Returns:
        Список записей дневника, отсортированный по дню

    Raises:
        ValueError: Если файл повреждён
    """
    path = _get_diary_path(house_id)
    if not path.exists():
        return []

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        entries = [FlockDiaryEntry.from_dict(item) for item in data]

        # Фильтровать по диапазону дней
        entries = [e for e in entries if from_day <= e.day_of_cycle <= to_day]

        # Сортировать по дню
        entries.sort(key=lambda e: e.day_of_cycle)

        return entries
    except json.JSONDecodeError as e:
        raise ValueError(f"Corrupted diary file for {house_id}: {e}")
    except Exception as e:
        raise ValueError(f"Failed to load diary for {house_id}: {e}")


def get_diary_entry_by_day(house_id: str, day: int) -> Optional[FlockDiaryEntry]:
    """
    Получить запись дневника за конкретный день.

    Args:
        house_id: ID птичника
        day: День цикла

    Returns:
        Запись или None, если нет записи за этот день
    """
    entries = load_diary_entries(house_id, from_day=day, to_day=day)
    return entries[0] if entries else None


def update_diary_entry(house_id: str, day: int, entry: FlockDiaryEntry) -> None:
    """
    Обновить запись дневника за конкретный день.

    Это алиас для save_diary_entry (который сам обрабатывает обновление).

    Args:
        house_id: ID птичника
        day: День цикла
        entry: Обновлённая запись
    """
    entry.day_of_cycle = day  # Убедиться, что день совпадает
    save_diary_entry(house_id, entry)


def delete_diary_entry(house_id: str, day: int) -> bool:
    """
    Удалить запись дневника за конкретный день.

    Args:
        house_id: ID птичника
        day: День цикла

    Returns:
        True если запись была удалена, False если записи не было

    Raises:
        IOError: Если не удалось сохранить файл
    """
    entries = load_diary_entries(house_id)
    initial_count = len(entries)

    # Удалить запись за указанный день
    entries = [e for e in entries if e.day_of_cycle != day]

    if len(entries) == initial_count:
        return False  # Записи не было

    # Сохранить обновлённый список
    path = _get_diary_path(house_id)
    try:
        with open(path, "w", encoding="utf-8") as f:
            data = [e.to_dict() for e in entries]
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        raise IOError(f"Failed to delete diary entry for {house_id}: {e}")


def delete_all_flock_data(house_id: str) -> None:
    """
    Удалить ВСЕ данные о стаде (информацию и дневник).

    Используется при удалении птичника.

    Args:
        house_id: ID птичника
    """
    delete_flock_info(house_id)

    diary_path = _get_diary_path(house_id)
    if diary_path.exists():
        diary_path.unlink()


def list_all_flocks() -> List[str]:
    """
    Получить список всех house_id, для которых есть данные.

    Returns:
        Список house_id (например: ['A-1', 'B-2', 'C-3'])
    """
    _ensure_flocks_dir()

    house_ids = set()
    for file_path in FLOCKS_DATA_DIR.glob("house_*_info.json"):
        # Извлечь house_id из имени файла
        # Формат: house_{safe_id}_info.json
        filename = file_path.stem  # house_{safe_id}_info
        if filename.startswith("house_") and filename.endswith("_info"):
            safe_id = filename[6:-5]  # Убрать "house_" и "_info"
            house_ids.add(safe_id)

    return sorted(list(house_ids))
