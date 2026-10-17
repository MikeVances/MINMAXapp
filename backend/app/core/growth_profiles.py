"""
Библиотека профилей роста: данные КРОССА по дням — живая масса, целевая
температура и влажность в птичнике.

Нормы вентиляции здесь не хранятся: Qmin считается из массы (CIGR), Qmax — из
теплового баланса и сечения корпуса (calc_core). Профиль описывает птицу,
а не птичник.

Хранилище — JSON-файлы, один профиль на файл:
  data/growth_profiles/builtin/<id>.json  — профили производителей, только чтение,
                                            лежат в git, у каждого указан источник
  data/growth_profiles/custom/<id>.json   — профили пользователя (копия кросса
                                            с правками или собственный график)

Формат файла:
  {
    "id": "ross308", "name": "Ross 308 — as-hatched", "breed": "Ross 308",
    "source": {"weight": "...", "climate": "..."},
    "points": [{"day": 0, "body_weight_g": 44, "min_temp_c": 33, "rv_percent": 60}, ...]
  }

Точки могут идти с пропусками (например, понедельно): промежуточные дни
заполняются линейной интерполяцией при чтении.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from .json_store import atomic_write_json
from .paths import data_path

logger = logging.getLogger(__name__)

GROWTH_PROFILES_DIR = data_path("GROWTH_PROFILES_DIR", "data/growth_profiles")

# id попадает в имя файла: только строчные латинские буквы, цифры, «-» и «_»,
# без точек и слэшей — иначе через id можно было бы выйти из каталога
PROFILE_ID_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,63}$"

DEFAULT_PROFILE_ID = "ross308"


class ProfileNotFound(LookupError):
    """Профиля с таким id нет ни среди встроенных, ни среди пользовательских."""


class BuiltinProfileReadOnly(PermissionError):
    """Попытка изменить или удалить профиль производителя."""


# ─── Модель ──────────────────────────────────────────────────────────────────

@dataclass
class GrowthPoint:
    day: int
    body_weight_g: Optional[float] = None
    min_temp_c: Optional[float] = None
    rv_percent: Optional[float] = None


@dataclass
class GrowthProfile:
    id: str
    name: str
    breed: Optional[str] = None
    builtin: bool = False
    # Откуда взяты числа: {"weight": "...", "climate": "..."} — свободный текст
    source: Dict[str, str] = field(default_factory=dict)
    points: List[GrowthPoint] = field(default_factory=list)

    def daily(self) -> Dict[int, GrowthPoint]:
        """Все дни от первой до последней точки, пропуски — линейной интерполяцией."""
        return _interpolate_daily(self.points)

    def point_for_day(self, day: int) -> GrowthPoint:
        """
        Значения на день цикла. За пределами профиля берётся ближайший край:
        расчёт на 60-й день по профилю до 56-го дня использует 56-й, а не падает.
        """
        days = self.daily()
        if not days:
            raise ValueError(f"Профиль '{self.id}' не содержит точек")
        clamped = min(max(day, min(days)), max(days))
        return days[clamped]


# ─── Интерполяция ────────────────────────────────────────────────────────────

def _lerp_field(points: List[GrowthPoint], attr: str, day: int) -> Optional[float]:
    """Линейная интерполяция одного поля; точки без значения поля пропускаются."""
    known = [(p.day, getattr(p, attr)) for p in points if getattr(p, attr) is not None]
    if not known:
        return None
    for d, v in known:
        if d == day:
            return v
    left = [(d, v) for d, v in known if d < day]
    right = [(d, v) for d, v in known if d > day]
    if not left:
        return right[0][1]
    if not right:
        return left[-1][1]
    (d0, v0), (d1, v1) = left[-1], right[0]
    return v0 + (v1 - v0) * (day - d0) / (d1 - d0)


def _interpolate_daily(points: List[GrowthPoint]) -> Dict[int, GrowthPoint]:
    if not points:
        return {}
    ordered = sorted(points, key=lambda p: p.day)
    first, last = ordered[0].day, ordered[-1].day
    return {
        d: GrowthPoint(
            day=d,
            body_weight_g=_lerp_field(ordered, "body_weight_g", d),
            min_temp_c=_lerp_field(ordered, "min_temp_c", d),
            rv_percent=_lerp_field(ordered, "rv_percent", d),
        )
        for d in range(first, last + 1)
    }


# ─── Файлы ───────────────────────────────────────────────────────────────────

def _builtin_dir() -> Path:
    return GROWTH_PROFILES_DIR / "builtin"


def _custom_dir() -> Path:
    return GROWTH_PROFILES_DIR / "custom"


def _check_id(profile_id: str) -> None:
    if not re.fullmatch(PROFILE_ID_PATTERN, profile_id or ""):
        raise ValueError(f"Недопустимый id профиля: {profile_id!r}")


def _from_file(path: Path, builtin: bool) -> GrowthProfile:
    raw = json.loads(path.read_text(encoding="utf-8"))
    points = [
        GrowthPoint(
            day=int(p["day"]),
            body_weight_g=p.get("body_weight_g"),
            min_temp_c=p.get("min_temp_c"),
            rv_percent=p.get("rv_percent"),
        )
        for p in raw.get("points", [])
    ]
    return GrowthProfile(
        # id и признак «встроенный» берём из расположения файла, а не из его
        # содержимого: файл в custom/ не может объявить себя профилем производителя
        id=path.stem,
        name=raw.get("name") or path.stem,
        breed=raw.get("breed"),
        builtin=builtin,
        source=dict(raw.get("source") or {}),
        points=sorted(points, key=lambda p: p.day),
    )


def _to_json(profile: GrowthProfile) -> dict:
    return {
        "id": profile.id,
        "name": profile.name,
        "breed": profile.breed,
        "source": profile.source,
        "points": [
            {
                "day": p.day,
                "body_weight_g": p.body_weight_g,
                "min_temp_c": p.min_temp_c,
                "rv_percent": p.rv_percent,
            }
            for p in sorted(profile.points, key=lambda p: p.day)
        ],
    }


# ─── Публичный API ───────────────────────────────────────────────────────────

def list_profiles() -> List[GrowthProfile]:
    """Встроенные профили, затем пользовательские; битый файл пропускается с записью в лог."""
    result: List[GrowthProfile] = []
    for directory, builtin in ((_builtin_dir(), True), (_custom_dir(), False)):
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.json")):
            if not re.fullmatch(PROFILE_ID_PATTERN, path.stem):
                continue
            try:
                result.append(_from_file(path, builtin))
            except Exception:
                logger.exception("Профиль роста не читается и пропущен: %s", path)
    return result


def load_profile(profile_id: str) -> GrowthProfile:
    _check_id(profile_id)
    # Встроенный id нельзя перекрыть пользовательским (см. save_custom_profile),
    # поэтому порядок поиска однозначен
    for directory, builtin in ((_builtin_dir(), True), (_custom_dir(), False)):
        path = directory / f"{profile_id}.json"
        if path.is_file():
            return _from_file(path, builtin)
    raise ProfileNotFound(profile_id)


def save_custom_profile(profile: GrowthProfile) -> GrowthProfile:
    _check_id(profile.id)
    if (_builtin_dir() / f"{profile.id}.json").is_file():
        raise BuiltinProfileReadOnly(profile.id)
    if not profile.points:
        raise ValueError("Профиль должен содержать хотя бы одну точку")
    atomic_write_json(_custom_dir() / f"{profile.id}.json", _to_json(profile))
    return load_profile(profile.id)


def delete_custom_profile(profile_id: str) -> None:
    _check_id(profile_id)
    if (_builtin_dir() / f"{profile_id}.json").is_file():
        raise BuiltinProfileReadOnly(profile_id)
    path = _custom_dir() / f"{profile_id}.json"
    if not path.is_file():
        raise ProfileNotFound(profile_id)
    path.unlink()
