"""
API endpoints для управления стадами и дневником.

Endpoints:
    - POST /flock/{house_id}/info - создать/обновить информацию о стаде
    - GET  /flock/{house_id}/info - получить информацию о стаде
    - DELETE /flock/{house_id}/info - удалить стадо

    - POST /flock/{house_id}/diary - добавить запись в дневник
    - GET  /flock/{house_id}/diary - получить записи дневника
    - GET  /flock/{house_id}/diary/{day} - получить запись за день
    - PUT  /flock/{house_id}/diary/{day} - обновить запись за день
    - DELETE /flock/{house_id}/diary/{day} - удалить запись за день

    - GET /flock/{house_id}/analytics/plan-vs-fact - данные для графика
    - GET /flock/{house_id}/analytics/summary - сводная аналитика
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional, List

from ..models.flock import FlockInfo, FlockDiaryEntry, PlanVsFactData, AnalyticsSummary
from ..core import flock_storage
from ..core import analytics


router = APIRouter()


# ============================================================================
# Pydantic модели для API (request/response)
# ============================================================================

class FlockInfoRequest(BaseModel):
    """Запрос на создание/обновление информации о стаде."""
    house_id: str = Field(..., min_length=1, max_length=64)
    flock_name: str = Field(..., min_length=1, max_length=128)
    placement_date: str = Field(..., description="Дата посадки в формате ISO (YYYY-MM-DD)")
    initial_bird_count: int = Field(..., ge=1, le=100000)
    target_days: int = Field(42, ge=1, le=100)
    breed: Optional[str] = Field(None, max_length=64)
    notes: Optional[str] = Field(None, max_length=500)


class FlockInfoResponse(BaseModel):
    """Ответ с информацией о стаде."""
    house_id: str
    flock_name: str
    placement_date: str
    initial_bird_count: int
    target_days: int
    breed: Optional[str]
    notes: Optional[str]
    current_day: int  # Вычисленный текущий день цикла
    created_at: Optional[str]
    updated_at: Optional[str]


class DiaryEntryRequest(BaseModel):
    """Запрос на добавление/обновление записи дневника."""
    date: str = Field(..., description="Дата записи в формате ISO (YYYY-MM-DD)")
    day_of_cycle: int = Field(..., ge=1, le=100)
    actual_weight_g: Optional[float] = Field(None, ge=0, le=10000)
    mortality_count: Optional[int] = Field(None, ge=0)
    feed_consumption_kg: Optional[float] = Field(None, ge=0)
    temp_inside_c: Optional[float] = Field(None, ge=-20, le=60)
    notes: Optional[str] = Field(None, max_length=500)


class DiaryEntryResponse(BaseModel):
    """Ответ с записью дневника."""
    house_id: str
    date: str
    day_of_cycle: int
    actual_weight_g: Optional[float]
    mortality_count: Optional[int]
    feed_consumption_kg: Optional[float]
    temp_inside_c: Optional[float]
    notes: Optional[str]
    created_at: Optional[str]
    updated_at: Optional[str]


# ============================================================================
# Endpoints для FlockInfo
# ============================================================================

@router.post("/flock/{house_id}/info", response_model=FlockInfoResponse)
def create_or_update_flock_info(house_id: str, payload: FlockInfoRequest):
    """
    Создать или обновить информацию о стаде в птичнике.

    Если информация уже существует — она будет перезаписана.
    """
    try:
        flock_info = FlockInfo(
            house_id=house_id,
            flock_name=payload.flock_name,
            placement_date=payload.placement_date,
            initial_bird_count=payload.initial_bird_count,
            target_days=payload.target_days,
            breed=payload.breed,
            notes=payload.notes,
        )

        flock_storage.save_flock_info(house_id, flock_info)

        # Вернуть с вычисленным текущим днём
        return FlockInfoResponse(
            house_id=flock_info.house_id,
            flock_name=flock_info.flock_name,
            placement_date=flock_info.placement_date,
            initial_bird_count=flock_info.initial_bird_count,
            target_days=flock_info.target_days,
            breed=flock_info.breed,
            notes=flock_info.notes,
            current_day=flock_info.get_current_day(),
            created_at=flock_info.created_at,
            updated_at=flock_info.updated_at,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save flock info: {str(e)}")


@router.get("/flock/{house_id}/info", response_model=FlockInfoResponse)
def get_flock_info(house_id: str):
    """Получить информацию о стаде в птичнике."""
    try:
        flock_info = flock_storage.load_flock_info(house_id)
        if flock_info is None:
            raise HTTPException(
                status_code=404,
                detail=f"Flock info not found for house '{house_id}'. Create it first using POST /flock/{house_id}/info"
            )

        return FlockInfoResponse(
            house_id=flock_info.house_id,
            flock_name=flock_info.flock_name,
            placement_date=flock_info.placement_date,
            initial_bird_count=flock_info.initial_bird_count,
            target_days=flock_info.target_days,
            breed=flock_info.breed,
            notes=flock_info.notes,
            current_day=flock_info.get_current_day(),
            created_at=flock_info.created_at,
            updated_at=flock_info.updated_at,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load flock info: {str(e)}")


@router.delete("/flock/{house_id}/info")
def delete_flock_info(house_id: str):
    """
    Удалить информацию о стаде (и весь дневник).

    ВНИМАНИЕ: Это удалит ВСЕ данные о стаде, включая дневник!
    """
    try:
        flock_storage.delete_all_flock_data(house_id)
        return {"ok": True, "message": f"Flock data for '{house_id}' has been deleted"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete flock data: {str(e)}")


# ============================================================================
# Endpoints для Diary
# ============================================================================

@router.post("/flock/{house_id}/diary", response_model=DiaryEntryResponse)
def add_diary_entry(house_id: str, payload: DiaryEntryRequest):
    """
    Добавить запись в дневник стада.

    Если запись за этот день уже существует — она будет обновлена.
    """
    try:
        # Проверить, что flock_info существует
        flock_info = flock_storage.load_flock_info(house_id)
        if flock_info is None:
            raise HTTPException(
                status_code=404,
                detail=f"Flock info not found for house '{house_id}'. Create it first."
            )

        entry = FlockDiaryEntry(
            house_id=house_id,
            date=payload.date,
            day_of_cycle=payload.day_of_cycle,
            actual_weight_g=payload.actual_weight_g,
            mortality_count=payload.mortality_count,
            feed_consumption_kg=payload.feed_consumption_kg,
            temp_inside_c=payload.temp_inside_c,
            notes=payload.notes,
        )

        # Валидация
        errors = entry.validate()
        if errors:
            raise HTTPException(status_code=400, detail={"validation_errors": errors})

        flock_storage.save_diary_entry(house_id, entry)

        return DiaryEntryResponse(
            house_id=entry.house_id,
            date=entry.date,
            day_of_cycle=entry.day_of_cycle,
            actual_weight_g=entry.actual_weight_g,
            mortality_count=entry.mortality_count,
            feed_consumption_kg=entry.feed_consumption_kg,
            temp_inside_c=entry.temp_inside_c,
            notes=entry.notes,
            created_at=entry.created_at,
            updated_at=entry.updated_at,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save diary entry: {str(e)}")


@router.get("/flock/{house_id}/diary", response_model=List[DiaryEntryResponse])
def get_diary_entries(
    house_id: str,
    from_day: int = Query(1, ge=1, le=100, description="Начальный день (включительно)"),
    to_day: int = Query(100, ge=1, le=100, description="Конечный день (включительно)")
):
    """Получить записи дневника за диапазон дней."""
    try:
        entries = flock_storage.load_diary_entries(house_id, from_day=from_day, to_day=to_day)

        return [
            DiaryEntryResponse(
                house_id=e.house_id,
                date=e.date,
                day_of_cycle=e.day_of_cycle,
                actual_weight_g=e.actual_weight_g,
                mortality_count=e.mortality_count,
                feed_consumption_kg=e.feed_consumption_kg,
                temp_inside_c=e.temp_inside_c,
                notes=e.notes,
                created_at=e.created_at,
                updated_at=e.updated_at,
            )
            for e in entries
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load diary entries: {str(e)}")


@router.get("/flock/{house_id}/diary/{day}", response_model=DiaryEntryResponse)
def get_diary_entry_by_day(house_id: str, day: int):
    """Получить запись дневника за конкретный день."""
    try:
        entry = flock_storage.get_diary_entry_by_day(house_id, day)
        if entry is None:
            raise HTTPException(
                status_code=404,
                detail=f"No diary entry found for house '{house_id}' on day {day}"
            )

        return DiaryEntryResponse(
            house_id=entry.house_id,
            date=entry.date,
            day_of_cycle=entry.day_of_cycle,
            actual_weight_g=entry.actual_weight_g,
            mortality_count=entry.mortality_count,
            feed_consumption_kg=entry.feed_consumption_kg,
            temp_inside_c=entry.temp_inside_c,
            notes=entry.notes,
            created_at=entry.created_at,
            updated_at=entry.updated_at,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load diary entry: {str(e)}")


@router.put("/flock/{house_id}/diary/{day}", response_model=DiaryEntryResponse)
def update_diary_entry(house_id: str, day: int, payload: DiaryEntryRequest):
    """Обновить запись дневника за конкретный день."""
    try:
        # Убедиться, что day_of_cycle совпадает
        if payload.day_of_cycle != day:
            raise HTTPException(
                status_code=400,
                detail=f"day_of_cycle in payload ({payload.day_of_cycle}) must match URL parameter ({day})"
            )

        entry = FlockDiaryEntry(
            house_id=house_id,
            date=payload.date,
            day_of_cycle=day,
            actual_weight_g=payload.actual_weight_g,
            mortality_count=payload.mortality_count,
            feed_consumption_kg=payload.feed_consumption_kg,
            temp_inside_c=payload.temp_inside_c,
            notes=payload.notes,
        )

        # Валидация
        errors = entry.validate()
        if errors:
            raise HTTPException(status_code=400, detail={"validation_errors": errors})

        flock_storage.update_diary_entry(house_id, day, entry)

        return DiaryEntryResponse(
            house_id=entry.house_id,
            date=entry.date,
            day_of_cycle=entry.day_of_cycle,
            actual_weight_g=entry.actual_weight_g,
            mortality_count=entry.mortality_count,
            feed_consumption_kg=entry.feed_consumption_kg,
            temp_inside_c=entry.temp_inside_c,
            notes=entry.notes,
            created_at=entry.created_at,
            updated_at=entry.updated_at,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update diary entry: {str(e)}")


@router.delete("/flock/{house_id}/diary/{day}")
def delete_diary_entry(house_id: str, day: int):
    """Удалить запись дневника за конкретный день."""
    try:
        success = flock_storage.delete_diary_entry(house_id, day)
        if not success:
            raise HTTPException(
                status_code=404,
                detail=f"No diary entry found for house '{house_id}' on day {day}"
            )

        return {"ok": True, "message": f"Diary entry for day {day} has been deleted"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete diary entry: {str(e)}")


# ============================================================================
# Endpoints для аналитики
# ============================================================================

@router.get("/flock/{house_id}/analytics/plan-vs-fact")
def get_plan_vs_fact(house_id: str, target_days: int = Query(42, ge=1, le=100)):
    """
    Получить данные для графика план vs факт.

    Возвращает данные для построения линейного графика:
    - days: массив дней [1, 2, 3, ..., 42]
    - plan_weight: плановый вес по дням
    - actual_weight: фактический вес по дням (из дневника)
    - delta: отклонение (факт - план)
    """
    try:
        data = analytics.get_plan_vs_fact_data(house_id, target_days=target_days)
        return data.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get plan vs fact data: {str(e)}")


@router.get("/flock/{house_id}/analytics/summary")
def get_analytics_summary(house_id: str):
    """
    Получить сводную аналитику по стаду.

    Возвращает ключевые метрики:
    - Средний привес в день (г)
    - Отклонение веса от плана (г и %)
    - Прогноз финального веса к целевому дню
    - Кумулятивный падёж (голов и %)
    - Текущее поголовье
    - Общий расход корма (кг)
    - Средний расход корма на голову (кг)
    """
    try:
        summary = analytics.get_analytics_summary(house_id)
        return summary.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get analytics summary: {str(e)}")
