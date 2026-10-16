#!/usr/bin/env python3
"""
Smoke-тест ЖИВОГО сервера Ventilation Min/Max API: отвечает ли развёрнутое
приложение и согласованы ли базовые инварианты.

Это не замена pytest: эталоны физики живут в backend/tests/ и запускаются
без сервера (`make test`). Smoke-тест нужен после деплоя или за прокси.

Запуск:
  uvicorn backend.app.main:app --port 8001      # в другом терминале
  python3 scripts/smoke_test.py                  # по умолчанию http://127.0.0.1:8001
  python3 scripts/smoke_test.py https://host/prefix
"""

from __future__ import annotations

import json
import sys
import urllib.request

DEFAULT_BASE_URL = "http://127.0.0.1:8001"


def post(base_url: str, path: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        base_url.rstrip("/") + path, data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def approx(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol * max(1.0, abs(a), abs(b))


def main() -> int:
    base_url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_BASE_URL
    ok = True

    # house — строка: API валидирует его как str, число даёт 422.
    # Размеры корпуса нужны для туннельного Qmax (без них он равен Qmin)
    base = dict(house="1", birds=35000, age_days=21, outside_t=25,
                house_width_m=18, house_height_m=3.2)

    # Ограничение мощностью: итоговый Qmax не выше заданной мощности и не выше номинала
    cap = 10000
    r_c = post(base_url, "/calc/minmax", {**base, "user_max_m3h": cap})
    if not (r_c["q_max_m3h"] <= cap and r_c["q_max_nominal_m3h"] >= r_c["q_max_m3h"]):
        print("[FAIL] capacity capping")
        ok = False

    # Туннельный расход — свойство корпуса: вдвое меньше птицы, те же вентиляторы
    r_full = post(base_url, "/calc/minmax", base)
    r_half = post(base_url, "/calc/minmax", {**base, "birds": base["birds"] // 2})
    if not (r_full["tunnel_active"] and approx(r_full["q_max_nominal_m3h"], r_half["q_max_nominal_m3h"])):
        print("[FAIL] tunnel airflow depends on bird count")
        ok = False

    print("OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
