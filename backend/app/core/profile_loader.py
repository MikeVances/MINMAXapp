from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Dict, List, Literal, Optional, Tuple


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
    for mode_key, rows in raw.items():
        pts: List[ProfilePoint] = []
        for r in rows:
            pts.append(
                ProfilePoint(
                    day=int(r["day"]),
                    body_weight_g=float(r["body_weight_g"]),
                    min_per_bird=float(r["min_per_bird"]),
                    max_per_bird=float(r["max_per_bird"]),
                    min_per_kg=float(r["min_per_kg"]),
                    max_per_kg=float(r["max_per_kg"]),
                    min_temp_c=(float(r["min_temp_c"]) if "min_temp_c" in r and r["min_temp_c"] is not None else None),
                    rv_percent=(float(r["rv_percent"]) if "rv_percent" in r and r["rv_percent"] is not None else None),
                )
            )
        points_by_mode[mode_key] = pts
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


def get_profile(seed_path: Optional[str] = None) -> VentProfile:
    path = seed_path or os.getenv("VENT_PROFILE_JSON")
    if path and os.path.exists(path):
        vp = load_profile_from_json(path)
        # Если seed существует, но пустой/неполный — используем демо-профиль
        required = ("winter", "spring_autumn", "summer")
        try:
            if all(vp.points.get(m) for m in required):
                return vp
        except Exception:
            pass
        return demo_profile()
    return demo_profile()
