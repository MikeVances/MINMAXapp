#!/usr/bin/env python3
"""
Simple smoke tests for the Ventilation Min/Max API.

Prereq: run the API locally:
  uvicorn backend.app.main:app --reload --port 8001

Then run:
  python3 scripts/smoke_test.py
"""

from __future__ import annotations

import json
import sys
import urllib.request


API = "http://127.0.0.1:8001/calc/minmax"


def post(payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(API, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def approx(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol * max(1.0, abs(a), abs(b))


def main() -> int:
    ok = True
    base = dict(house=1, birds=35000, age_days=21, mode_id="winter", display_unit="per_bird")

    # Temperature interpolation monotonicity: Winter <= Mid <= Summer
    r_w = post({**base, "outside_t": -5})
    r_m = post({**base, "outside_t": 10})
    r_s = post({**base, "outside_t": 25})
    if not (r_w["q_min_m3h"] <= r_m["q_min_m3h"] <= r_s["q_min_m3h"]):
        print("[FAIL] q_min monotonic with temperature", r_w["q_min_m3h"], r_m["q_min_m3h"], r_s["q_min_m3h"]) 
        ok = False

    # Capacity capping
    cap = 10000
    r_c = post({**base, "outside_t": 25, "user_max_m3h": cap})
    if not (r_c["q_max_m3h"] <= cap and r_c["q_max_nominal_m3h"] >= r_c["q_max_m3h"]):
        print("[FAIL] capacity capping")
        ok = False

    # per_bird vs per_kg equivalence
    r_bird = r_s
    r_kg = post({**base, "outside_t": 25, "display_unit": "per_kg"})
    if not (approx(r_bird["q_min_m3h"], r_kg["q_min_m3h"]) and approx(r_bird["q_max_nominal_m3h"], r_kg["q_max_nominal_m3h"])):
        print("[FAIL] per_bird vs per_kg equivalence")
        ok = False

    print("OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

