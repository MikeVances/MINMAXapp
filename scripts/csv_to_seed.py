#!/usr/bin/env python3
"""
Convert a CSV exported from the Excel print area (sheet "Ventilation required")
into a JSON seed (data/vent_profile_seed.json) used by the backend.

This tool is mapping-driven: you must specify which CSV columns contain
the day index, body weight, and the min ventilation rates per bird/kg for each
season group. Tropical can optionally reuse summer mapping if not supplied.

Example usage:

  python scripts/csv_to_seed.py \
    --csv data/ventilation_required.csv \
    --out data/vent_profile_seed.json \
    --day-col 1 \
    --weight-col 8 \
    --winter-bird-col 12 --winter-kg-col 14 \
    --spring-bird-col 18 --spring-kg-col 20 \
    --summer-bird-col 24 --summer-kg-col 26

Notes:
- Column indices are 1-based (human friendly). Non-numeric cells are ignored.
- Only rows with day in [1..42] are taken. No interpolation is applied.
- The script tolerates both '.' and ',' decimal separators.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import dataclass
from typing import Dict, List, Optional


def parse_float(x: str) -> Optional[float]:
    if x is None:
        return None
    s = x.strip().replace("\xa0", " ")
    if not s:
        return None
    # replace comma decimal if present
    if s.count(",") == 1 and s.count(".") == 0:
        s = s.replace(",", ".")
    # strip percent sign
    s = s.replace("%", "")
    try:
        return float(s)
    except ValueError:
        return None


def parse_int(x: str) -> Optional[int]:
    f = parse_float(x)
    if f is None or math.isnan(f):
        return None
    return int(round(f))


@dataclass
class Map:
    day_col: int
    weight_col: int
    winter_bird_col: int
    winter_kg_col: int
    spring_bird_col: int
    spring_kg_col: int
    summer_bird_col: int
    summer_kg_col: int
    # Optional explicit tropical mapping; if absent, summer is reused
    tropical_bird_col: Optional[int] = None
    tropical_kg_col: Optional[int] = None
    # Optional MAX columns per mode
    winter_bird_max_col: Optional[int] = None
    winter_kg_max_col: Optional[int] = None
    spring_bird_max_col: Optional[int] = None
    spring_kg_max_col: Optional[int] = None
    summer_bird_max_col: Optional[int] = None
    summer_kg_max_col: Optional[int] = None
    tropical_bird_max_col: Optional[int] = None
    tropical_kg_max_col: Optional[int] = None
    # Optional day setpoints
    min_temp_col: Optional[int] = None
    rv_col: Optional[int] = None

    @staticmethod
    def from_args(ns: argparse.Namespace) -> "Map":
        return Map(
            day_col=ns.day_col,
            weight_col=ns.weight_col,
            winter_bird_col=ns.winter_bird_col,
            winter_kg_col=ns.winter_kg_col,
            spring_bird_col=ns.spring_bird_col,
            spring_kg_col=ns.spring_kg_col,
            summer_bird_col=ns.summer_bird_col,
            summer_kg_col=ns.summer_kg_col,
            tropical_bird_col=ns.tropical_bird_col,
            tropical_kg_col=ns.tropical_kg_col,
            winter_bird_max_col=ns.winter_bird_max_col,
            winter_kg_max_col=ns.winter_kg_max_col,
            spring_bird_max_col=ns.spring_bird_max_col,
            spring_kg_max_col=ns.spring_kg_max_col,
            summer_bird_max_col=ns.summer_bird_max_col,
            summer_kg_max_col=ns.summer_kg_max_col,
            tropical_bird_max_col=ns.tropical_bird_max_col,
            tropical_kg_max_col=ns.tropical_kg_max_col,
            min_temp_col=ns.min_temp_col,
            rv_col=ns.rv_col,
        )


def build_seed(rows: List[List[str]], m: Map) -> Dict[str, List[dict]]:
    def get(row: List[str], col1: Optional[int]) -> str:
        # 1-based index to 0-based
        if col1 is None:
            return ""
        idx = col1 - 1
        return row[idx] if 0 <= idx < len(row) else ""

    out: Dict[str, List[dict]] = {
        "winter": [],
        "spring_autumn": [],
        "summer": [],
        "tropical": [],
    }

    for row in rows:
        day = parse_int(get(row, m.day_col))
        if day is None or not (1 <= day <= 42):
            continue
        weight_g = parse_float(get(row, m.weight_col))
        # Допускаем вес в граммах; если он явно в кг (малое число) — конвертируем в граммы
        if weight_g is None:
            weight_g = 0.0
        elif weight_g < 10:  # вероятно кг
            weight_g = weight_g * 1000.0

        # опционально извлекаем уставки температуры/влажности, если заданы колонки
        min_temp_c = parse_float(get(row, getattr(m, 'min_temp_col', None)))
        rv_percent = parse_float(get(row, getattr(m, 'rv_col', None)))

        def pack(
            bird_col: int,
            kg_col: int,
            bird_max_col: Optional[int] = None,
            kg_max_col: Optional[int] = None,
        ) -> dict:
            bird = parse_float(get(row, bird_col)) or 0.0
            kg = parse_float(get(row, kg_col)) or 0.0
            # Max columns may be absent — derive from available values and weight
            max_bird_val = parse_float(get(row, bird_max_col)) if bird_max_col else None
            max_kg_val = parse_float(get(row, kg_max_col)) if kg_max_col else None
            if max_bird_val is None and max_kg_val is not None:
                # derive per bird from per kg
                max_bird_val = (max_kg_val * (weight_g / 1000.0)) if weight_g else 0.0
            if max_kg_val is None and max_bird_val is not None:
                # derive per kg from per bird
                max_kg_val = (max_bird_val / (weight_g / 1000.0)) if weight_g else 0.0
            if max_bird_val is None:
                max_bird_val = bird
            if max_kg_val is None:
                max_kg_val = kg
            return dict(
                day=day,
                body_weight_g=weight_g,
                min_per_bird=bird,
                max_per_bird=max_bird_val,
                min_per_kg=kg,
                max_per_kg=max_kg_val,
                min_temp_c=min_temp_c,
                rv_percent=rv_percent,
            )

        out["winter"].append(
            pack(m.winter_bird_col, m.winter_kg_col, m.winter_bird_max_col, m.winter_kg_max_col)
        )
        out["spring_autumn"].append(
            pack(m.spring_bird_col, m.spring_kg_col, m.spring_bird_max_col, m.spring_kg_max_col)
        )
        out["summer"].append(
            pack(m.summer_bird_col, m.summer_kg_col, m.summer_bird_max_col, m.summer_kg_max_col)
        )
        tb = m.tropical_bird_col or m.summer_bird_col
        tk = m.tropical_kg_col or m.summer_kg_col
        tbm = m.tropical_bird_max_col or m.summer_bird_max_col
        tkm = m.tropical_kg_max_col or m.summer_kg_max_col
        out["tropical"].append(pack(tb, tk, tbm, tkm))

    # Сортируем по дню
    for v in out.values():
        v.sort(key=lambda x: x["day"])
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--day-col", type=int, required=True)
    ap.add_argument("--weight-col", type=int, required=True)
    ap.add_argument("--winter-bird-col", type=int, required=True)
    ap.add_argument("--winter-kg-col", type=int, required=True)
    ap.add_argument("--spring-bird-col", type=int, required=True)
    ap.add_argument("--spring-kg-col", type=int, required=True)
    ap.add_argument("--summer-bird-col", type=int, required=True)
    ap.add_argument("--summer-kg-col", type=int, required=True)
    ap.add_argument("--tropical-bird-col", type=int)
    ap.add_argument("--tropical-kg-col", type=int)
    # Optional MAX mapping (if provided). If missing, MAX is derived or equals MIN.
    ap.add_argument("--winter-bird-max-col", type=int)
    ap.add_argument("--winter-kg-max-col", type=int)
    ap.add_argument("--spring-bird-max-col", type=int)
    ap.add_argument("--spring-kg-max-col", type=int)
    ap.add_argument("--summer-bird-max-col", type=int)
    ap.add_argument("--summer-kg-max-col", type=int)
    ap.add_argument("--tropical-bird-max-col", type=int)
    ap.add_argument("--tropical-kg-max-col", type=int)
    # Optional per-day setpoints (same for all modes): inside min temp and target RH%
    ap.add_argument("--min-temp-col", type=int)
    ap.add_argument("--rv-col", type=int)
    ns = ap.parse_args()

    with open(ns.csv, "r", encoding="utf-8") as f:
        rdr = csv.reader(f)
        rows = [r for r in rdr]

    seed = build_seed(rows, Map.from_args(ns))

    with open(ns.out, "w", encoding="utf-8") as f:
        json.dump(seed, f, ensure_ascii=False, indent=2)

    print(f"Wrote seed -> {ns.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
