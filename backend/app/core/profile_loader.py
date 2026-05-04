from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Dict, List, Literal, Optional, Tuple

from math import isfinite

def _to_float(v, default: float | None = None) -> float | None:
    try:
        if v is None or v == "":
            return default
        x = float(v)
        return x if isfinite(x) else default
    except Exception:
        return default


Mode = Literal["winter", "summer", "spring_autumn", "tropical"]


@dataclass
class ProfilePoint:
    day: int
    body_weight_g: float
    min_per_bird: float
    max_per_bird: float
    min_per_kg: float
    max_per_kg: float
    # Дополнительные справочные поля (опционально):
    # уставка минимальной температуры (внутри), целевой уровень RH (%)
    min_temp_c: float | None = None
    rv_percent: float | None = None
    authoritative_basis: Literal['per_kg','per_bird'] | None = None


class VentProfile:
    def __init__(self, points_by_mode: Dict[Mode, List[ProfilePoint]]):
        self.points: Dict[Mode, List[ProfilePoint]] = {}
        for m, pts in points_by_mode.items():
            self.points[m] = sorted(pts, key=lambda p: p.day)

    def _find_bounds(self, pts: List[ProfilePoint], day: int) -> Tuple[ProfilePoint, ProfilePoint]:
        if day <= pts[0].day:
            return pts[0], pts[0]
        if day >= pts[-1].day:
            return pts[-1], pts[-1]
        lo = pts[0]
        for i in range(1, len(pts)):
            hi = pts[i]
            if lo.day <= day <= hi.day:
                return lo, hi
            lo = hi
        return pts[-1], pts[-1]

    def resolve(self, mode: Mode, day: int, strategy: Literal["linear", "nearest", "floor"] = "linear") -> ProfilePoint:
        pts = self.points.get(mode, [])
        if not pts:
            raise KeyError(f"No profile for mode: {mode}")
        a, b = self._find_bounds(pts, day)
        if a.day == b.day or strategy == "floor":
            return a
        if strategy == "nearest":
            return a if (day - a.day) <= (b.day - day) else b
        # linear interpolation
        span = float(b.day - a.day)
        t = (day - a.day) / span
        def lerp(x: float, y: float) -> float:
            return x + (y - x) * t
        return ProfilePoint(
            day=day,
            body_weight_g=lerp(a.body_weight_g, b.body_weight_g),
            min_per_bird=lerp(a.min_per_bird, b.min_per_bird),
            max_per_bird=lerp(a.max_per_bird, b.max_per_bird),
            min_per_kg=lerp(a.min_per_kg, b.min_per_kg),
            max_per_kg=lerp(a.max_per_kg, b.max_per_kg),
            min_temp_c=(None if a.min_temp_c is None or b.min_temp_c is None else lerp(a.min_temp_c, b.min_temp_c)),
            rv_percent=(None if a.rv_percent is None or b.rv_percent is None else lerp(a.rv_percent, b.rv_percent)),
        )

    # Удобный псевдоним
    get_point = resolve


def load_profile_from_json(path: str) -> VentProfile:
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    points_by_mode: Dict[Mode, List[ProfilePoint]] = {}
    valid_modes: Tuple[Mode, ...] = ("winter", "spring_autumn", "summer", "tropical")

    for mode_key, rows in raw.items():
        if mode_key not in valid_modes:
            # игнорируем незнакомые ключи режимов, чтобы не завалить загрузку
            continue
        pts: List[ProfilePoint] = []
        for r in rows:
            day = int(r.get("day"))
            bw_g = _to_float(r.get("body_weight_g"), 0.0) or 0.0
            w_kg = max(bw_g / 1000.0, 1e-6)

            # читаем ставки (они могут отсутствовать в seed)
            min_bird = _to_float(r.get("min_per_bird"))
            max_bird = _to_float(r.get("max_per_bird"))
            min_kg   = _to_float(r.get("min_per_kg"))
            max_kg   = _to_float(r.get("max_per_kg"))

            # восстанавливаем недостающие значения по массе
            if min_bird is None and min_kg is not None:
                min_bird = min_kg * w_kg
            if min_kg is None and min_bird is not None:
                min_kg = min_bird / w_kg

            if max_bird is None and max_kg is not None:
                max_bird = max_kg * w_kg
            if max_kg is None and max_bird is not None:
                max_kg = max_bird / w_kg

            # справочные поля
            min_temp_c = _to_float(r.get("min_temp_c"))
            rv_percent = _to_float(r.get("rv_percent"))

            basis = r.get("authoritative_basis")
            if basis not in ("per_kg", "per_bird", None):
                basis = None

            pts.append(
                ProfilePoint(
                    day=day,
                    body_weight_g=bw_g,
                    min_per_bird=float(min_bird or 0.0),
                    max_per_bird=float(max_bird or 0.0),
                    min_per_kg=float(min_kg or 0.0),
                    max_per_kg=float(max_kg or 0.0),
                    min_temp_c=min_temp_c,
                    rv_percent=rv_percent,
                    authoritative_basis=basis,
                )
            )
        # сортируем по дню
        points_by_mode[mode_key] = sorted(pts, key=lambda p: p.day)

    # простая валидация присутствия ключевых режимов
    required = ("winter", "spring_autumn", "summer")
    if not all(points_by_mode.get(m) for m in required):
        # дополним демо‑данными, чтобы приложение не упало целиком
        demo = demo_profile()
        for m in valid_modes:
            if not points_by_mode.get(m):
                points_by_mode[m] = demo.points.get(m, [])

    return VentProfile(points_by_mode)


def demo_profile() -> VentProfile:
    # Демонстрационный профиль на 7 опорных точек (1,7,14,21,28,35,42)
    # Значения условные, только для визуализации. Реальные подтянем из Excel seed.
    days = [1, 7, 14, 21, 28, 35, 42]
    def mk_row(d: int, factor: float) -> Dict[str, float]:
        # Примитивная демо‑модель роста массы и норм вентиляции
        weight_g = 40 + d * 20  # ~0.04 кг на старте → ~0.9 кг к 42 дню (условно)
        min_bird = 0.2 + 0.01 * (d/7) * factor
        max_bird = 0.5 + 0.02 * (d/7) * factor
        min_kg = min_bird / max(weight_g/1000.0, 0.001)
        max_kg = max_bird / max(weight_g/1000.0, 0.001)
        return dict(
            day=d,
            body_weight_g=weight_g,
            min_per_bird=round(min_bird, 4),
            max_per_bird=round(max_bird, 4),
            min_per_kg=round(min_kg, 4),
            max_per_kg=round(max_kg, 4),
            authoritative_basis="per_bird",
        )
    base = {d: mk_row(d, 1.0) for d in days}
    colder = {d: mk_row(d, 0.9) for d in days}
    hotter = {d: mk_row(d, 1.1) for d in days}
    data = {
        "winter": list(colder.values()),
        "spring_autumn": list(base.values()),
        "summer": list(hotter.values()),
        "tropical": list(hotter.values()),
    }
    return load_profile_from_json(_write_tmp(data))


def _write_tmp(data) -> str:
    import tempfile, json
    fd, p = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    return p


def get_profile_from_day_master(dm_path: str = "data/day_master.json") -> VentProfile | None:
    """Строит VentProfile из day_master.json — единственный источник правды.

    day_master хранит mode-независимый профиль; сезонная поправка (k_temp)
    применяется в calc_core в рантайме, поэтому все режимы получают одинаковые
    точки.
    """
    if not os.path.exists(dm_path):
        return None
    try:
        with open(dm_path, encoding="utf-8") as f:
            rows = json.load(f)
        if not isinstance(rows, list) or not rows:
            return None
        pts: List[ProfilePoint] = []
        for r in rows:
            bw_g  = _to_float(r.get("body_weight_g"))
            qminB = _to_float(r.get("q_min_per_bird"))
            qmaxB = _to_float(r.get("q_max_per_bird"))
            # Пропускаем дни без данных о весе или нормах вентиляции
            if bw_g is None or qminB is None or qmaxB is None:
                continue
            w_kg = max(bw_g / 1000.0, 1e-6)
            pts.append(ProfilePoint(
                day           = int(r["day"]),
                body_weight_g = bw_g,
                min_per_bird  = qminB,
                max_per_bird  = qmaxB,
                min_per_kg    = qminB / w_kg,
                max_per_kg    = qmaxB / w_kg,
                min_temp_c    = _to_float(r.get("min_temp_c")),
                rv_percent    = _to_float(r.get("rv_percent")),
            ))
        if len(pts) < 2:
            return None
        pts.sort(key=lambda p: p.day)
        # Один набор точек для всех режимов — k_temp в calc_core делает поправку
        modes: Dict[str, List[ProfilePoint]] = {
            m: list(pts) for m in ("winter", "spring_autumn", "summer", "tropical")
        }
        return VentProfile(modes)
    except Exception:
        return None


def get_profile(seed_path: Optional[str] = None) -> VentProfile:
    # Приоритет: day_master.json → seed → demo
    dm = get_profile_from_day_master()
    if dm is not None:
        return dm
    path = seed_path or os.getenv("VENT_PROFILE_JSON")
    if path and os.path.exists(path):
        vp = load_profile_from_json(path)
        required = ("winter", "spring_autumn", "summer")
        try:
            if all(vp.points.get(m) for m in required):
                if not vp.points.get("tropical"):
                    demo = demo_profile()
                    vp.points["tropical"] = demo.points.get("tropical", [])
                return vp
        except Exception:
            pass
        return demo_profile()
    return demo_profile()
