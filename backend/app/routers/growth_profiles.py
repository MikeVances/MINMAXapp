"""
API библиотеки профилей роста (см. core/growth_profiles.py).

  GET    /profiles        — список: встроенные (производители) и пользовательские
  GET    /profiles/{id}   — профиль: исходные точки + все дни с интерполяцией и нормой Qmin
  PUT    /profiles/{id}   — создать или обновить пользовательский профиль
  DELETE /profiles/{id}   — удалить пользовательский профиль

Встроенные профили менять нельзя (403): чтобы поправить кросс под свою площадку,
клиент копирует его под новым id и сохраняет копию.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Union

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..api_errors import api_error
from ..write_access import require_write_token
from ..core.app_config import load_app_config
from ..core.ventilation_calc import calc_q_min_per_bird
from ..core.growth_profiles import (
    PROFILE_ID_PATTERN,
    BuiltinProfileReadOnly,
    GrowthPoint,
    GrowthProfile,
    ProfileNotFound,
    delete_custom_profile,
    list_profiles,
    load_profile,
    save_custom_profile,
)

router = APIRouter()


# ─── Модели ──────────────────────────────────────────────────────────────────

# Источник данных профиля: строка (свободный текст) или структура с полями
# ref/page/table/column/basis/method/url — клиент собирает из неё подпись на своём языке
SourceValue = Union[str, Dict[str, Union[str, int, float]]]

class PointModel(BaseModel):
    day: int = Field(..., ge=0, le=70)
    body_weight_g: Optional[float] = Field(None, gt=0, le=10_000)
    min_temp_c: Optional[float] = Field(None, ge=0, le=45)
    rv_percent: Optional[float] = Field(None, ge=0, le=100)


class DayModel(PointModel):
    # Норма CO₂ (CIGR) из массы — та же формула, что в расчёте; только для чтения
    q_min_per_bird: Optional[float] = None


class ProfileSummary(BaseModel):
    id: str
    name: str
    breed: Optional[str] = None
    builtin: bool
    source: Dict[str, SourceValue] = {}
    first_day: int
    last_day: int


class ProfileOut(ProfileSummary):
    points: List[PointModel]
    days: List[DayModel]


class ProfileIn(BaseModel):
    # Имя и кросс выводятся в UI (через textContent) — ограничиваем длину
    name: str = Field(..., min_length=1, max_length=80)
    breed: Optional[str] = Field(None, max_length=80)
    source: Dict[str, SourceValue] = Field(default_factory=dict)
    points: List[PointModel] = Field(..., min_length=2, max_length=71)


# ─── Преобразования ──────────────────────────────────────────────────────────

def _summary(p: GrowthProfile) -> ProfileSummary:
    days = [pt.day for pt in p.points]
    return ProfileSummary(
        id=p.id, name=p.name, breed=p.breed, builtin=p.builtin, source=p.source,
        first_day=min(days), last_day=max(days),
    )


def _full(p: GrowthProfile) -> ProfileOut:
    safety = float(getattr(load_app_config(), "safety_factor_qmin", 1.5))
    days = [
        DayModel(
            day=d.day, body_weight_g=d.body_weight_g, min_temp_c=d.min_temp_c,
            rv_percent=d.rv_percent,
            q_min_per_bird=(calc_q_min_per_bird(d.body_weight_g / 1000.0, safety)
                            if d.body_weight_g else None),
        )
        for d in p.daily().values()
    ]
    return ProfileOut(
        **_summary(p).model_dump(),
        points=[PointModel(**vars(pt)) for pt in p.points],
        days=days,
    )


def _check_path_id(profile_id: str) -> None:
    if not re.fullmatch(PROFILE_ID_PATTERN, profile_id):
        raise api_error(422, "profile_id_invalid", id=profile_id)


# ─── Эндпоинты ───────────────────────────────────────────────────────────────

@router.get("", response_model=List[ProfileSummary])
def get_profiles():
    return [_summary(p) for p in list_profiles()]


@router.get("/{profile_id}", response_model=ProfileOut)
def get_profile(profile_id: str):
    _check_path_id(profile_id)
    try:
        return _full(load_profile(profile_id))
    except ProfileNotFound:
        raise api_error(404, "profile_not_found", id=profile_id)


@router.put("/{profile_id}", response_model=ProfileOut, dependencies=[Depends(require_write_token)])
def put_profile(profile_id: str, payload: ProfileIn):
    _check_path_id(profile_id)

    days = [pt.day for pt in payload.points]
    if len(days) != len(set(days)):
        raise api_error(422, "profile_days_duplicate")
    # Без массы расчёт невозможен: хотя бы две точки с весом нужны для интерполяции
    if sum(1 for pt in payload.points if pt.body_weight_g is not None) < 2:
        raise api_error(422, "profile_needs_two_weights")

    profile = GrowthProfile(
        id=profile_id,
        name=payload.name,
        breed=payload.breed,
        source=payload.source,
        points=[GrowthPoint(**pt.model_dump()) for pt in payload.points],
    )
    try:
        return _full(save_custom_profile(profile))
    except BuiltinProfileReadOnly:
        raise api_error(403, "builtin_profile_read_only")


@router.delete("/{profile_id}", dependencies=[Depends(require_write_token)])
def delete_profile(profile_id: str):
    _check_path_id(profile_id)
    try:
        delete_custom_profile(profile_id)
    except BuiltinProfileReadOnly:
        raise api_error(403, "builtin_profile_read_only")
    except ProfileNotFound:
        raise api_error(404, "profile_not_found", id=profile_id)
    return {"deleted": profile_id}
