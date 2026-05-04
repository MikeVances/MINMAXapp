from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Dict, Optional, Iterable

# Keep the same ENV var name already used in the app/UI
DAY_MASTER_PATH = os.getenv("DAY_MASTER_JSON", "data/day_master.json")


@dataclass
class DayInfo:
    day: int
    body_weight_g: Optional[float] = None
    min_temp_c: Optional[float] = None
    rv_percent: Optional[float] = None
    # Нормы вентиляции для данного возраста (м³/ч на голову)
    q_min_per_bird: Optional[float] = None  # Минимальная вентиляция
    q_max_per_bird: Optional[float] = None  # Максимальная вентиляция


def _to_float(x):
    try:
        if x is None or x == "":
            return None
        return float(x)
    except Exception:
        return None


def _linear_fill(points: Dict[int, Optional[float]], days: Iterable[int]) -> Dict[int, Optional[float]]:
    """Linear interpolation over integer days; if a value can't be interpolated (no bounds), keep None."""
    known = {d: v for d, v in points.items() if v is not None}
    if not known:
        return {d: None for d in days}

    anchors = dict(sorted(known.items()))
    ak = list(anchors.keys())
    out: Dict[int, Optional[float]] = {}

    for d in sorted(days):
        if d in anchors:
            out[d] = anchors[d]
            continue
        left = [k for k in ak if k < d]
        right = [k for k in ak if k > d]
        if not left or not right:
            out[d] = None
            continue
        l = left[-1]
        r = right[0]
        vl = anchors[l]
        vr = anchors[r]
        out[d] = vl + (vr - vl) * (float(d - l) / float(r - l))
    return out


def _parse_list(raw_list: list) -> Dict[int, DayInfo]:
    by_day: Dict[int, DayInfo] = {}
    for item in raw_list:
        if not isinstance(item, dict):
            continue
        d = item.get("day")
        try:
            day = int(d)
        except Exception:
            continue
        by_day[day] = DayInfo(
            day=day,
            body_weight_g=_to_float(item.get("body_weight_g")),
            min_temp_c=_to_float(item.get("min_temp_c")),
            rv_percent=_to_float(item.get("rv_percent")),
            q_min_per_bird=_to_float(item.get("q_min_per_bird")),
            q_max_per_bird=_to_float(item.get("q_max_per_bird")),
        )
    return by_day


def _parse_dict(raw_dict: dict) -> Dict[int, DayInfo]:
    by_day: Dict[int, DayInfo] = {}
    for k, v in (raw_dict or {}).items():
        try:
            day = int(k)
        except Exception:
            continue
        if not isinstance(v, dict):
            continue
        by_day[day] = DayInfo(
            day=day,
            body_weight_g=_to_float(v.get("body_weight_g")),
            min_temp_c=_to_float(v.get("min_temp_c")),
            rv_percent=_to_float(v.get("rv_percent")),
            q_min_per_bird=_to_float(v.get("q_min_per_bird")),
            q_max_per_bird=_to_float(v.get("q_max_per_bird")),
        )
    return by_day


def _interpolate_missing(by_day: Dict[int, DayInfo], cycle_days: int = 42) -> Dict[int, DayInfo]:
    # Fill gaps for all days 1..max_day; max_day is the larger of cycle_days and actual data range
    max_day = max(max(by_day.keys(), default=cycle_days), cycle_days)
    all_days = list(range(1, max_day + 1))
    if len(by_day) >= len(all_days) and all(d in by_day for d in all_days):
        return by_day

    w_points = {d: (by_day[d].body_weight_g if d in by_day else None) for d in all_days}
    t_points = {d: (by_day[d].min_temp_c if d in by_day else None) for d in all_days}
    rh_points = {d: (by_day[d].rv_percent if d in by_day else None) for d in all_days}
    qmin_points = {d: (by_day[d].q_min_per_bird if d in by_day else None) for d in all_days}
    qmax_points = {d: (by_day[d].q_max_per_bird if d in by_day else None) for d in all_days}

    w_filled = _linear_fill(w_points, all_days)
    t_filled = _linear_fill(t_points, all_days)
    qmin_filled = _linear_fill(qmin_points, all_days)
    qmax_filled = _linear_fill(qmax_points, all_days)

    out: Dict[int, DayInfo] = {}
    for d in all_days:
        out[d] = DayInfo(
            day=d,
            body_weight_g=w_points[d] if w_points[d] is not None else w_filled[d],
            min_temp_c=t_points[d] if t_points[d] is not None else t_filled[d],
            rv_percent=rh_points[d],  # RH is not interpolated intentionally
            q_min_per_bird=qmin_points[d] if qmin_points[d] is not None else qmin_filled[d],
            q_max_per_bird=qmax_points[d] if qmax_points[d] is not None else qmax_filled[d],
        )
    return out


def load_day_master(path: str = DAY_MASTER_PATH, cycle_days: int = 42) -> Dict[int, DayInfo]:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        return {}

    if isinstance(raw, list):
        by_day = _parse_list(raw)
    elif isinstance(raw, dict):
        by_day = _parse_dict(raw)
    else:
        by_day = {}

    return _interpolate_missing(by_day, cycle_days)


def save_day_master(items: Dict[int, DayInfo], path: str = DAY_MASTER_PATH) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    arr = [
        {
            "day": d,
            "body_weight_g": v.body_weight_g,
            "min_temp_c": v.min_temp_c,
            "rv_percent": v.rv_percent,
            "q_min_per_bird": v.q_min_per_bird,
            "q_max_per_bird": v.q_max_per_bird,
        }
        for d, v in sorted(items.items())
    ]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(arr, f, ensure_ascii=False, indent=2)