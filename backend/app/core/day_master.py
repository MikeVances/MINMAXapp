from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Dict, Optional

DAY_MASTER_PATH = os.getenv("DAY_MASTER_JSON", "data/day_master.json")


@dataclass
class DayInfo:
    day: int
    body_weight_g: Optional[float] = None
    min_temp_c: Optional[float] = None
    rv_percent: Optional[float] = None


def load_day_master(path: str = DAY_MASTER_PATH) -> Dict[int, DayInfo]:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {}
    out: Dict[int, DayInfo] = {}
    for item in data or []:
        try:
            d = int(item.get("day"))
        except Exception:
            continue
        out[d] = DayInfo(
            day=d,
            body_weight_g=_to_float(item.get("body_weight_g")),
            min_temp_c=_to_float(item.get("min_temp_c")),
            rv_percent=_to_float(item.get("rv_percent")),
        )
    return out


def save_day_master(items: Dict[int, DayInfo], path: str = DAY_MASTER_PATH) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    arr = [
        {
            "day": d,
            "body_weight_g": v.body_weight_g,
            "min_temp_c": v.min_temp_c,
            "rv_percent": v.rv_percent,
        }
        for d, v in sorted(items.items())
    ]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(arr, f, ensure_ascii=False, indent=2)


def _to_float(x):
    try:
        if x is None:
            return None
        return float(x)
    except Exception:
        return None

