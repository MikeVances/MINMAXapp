MINMAXapp Utilities

Scripts to extract and prepare data from the provided Excel file for further development.

What’s included
- `scripts/parse_ventilation.py`: Zero-dependency XLSX-to-CSV exporter that reads the sheet "Ventilation required" from `Вентиляция Минимум и максимум.xlsx` and writes a CSV of the visible table (print area).

- Backend (MVP): FastAPI app with a `/calc/minmax` endpoint that computes min/max ventilation based on a season profile and bird age. The backend can work with a seed JSON profile or a built-in demo profile if seed is empty.

Usage
1) Ensure you have Python 3.8+ installed locally.
2) Run:

```
python3 scripts/parse_ventilation.py \
  --xlsx "Вентиляция Минимум и максимум.xlsx" \
  --out data/ventilation_required.csv
```

Notes
- The script doesn’t require any third‑party packages. It parses the XLSX (ZIP) and XML directly using Python’s stdlib.
- It respects the print area defined in the workbook for the sheet, exporting only that region. If none is found, it falls back to the worksheet dimension.
- You can change the sheet via `--sheet` (default: `Ventilation required`).

Backend + UI (MVP)
- Launch (local): `uvicorn backend.app.main:app --reload --port 8001`
  or use Makefile: `make run-api` (auto-creates venv and installs deps)
- Health: GET `http://127.0.0.1:8001/healthz`
- Web UI: open `http://127.0.0.1:8001/` (static page)
- Calc API: POST `http://127.0.0.1:8001/calc/minmax`
  Body example:
  `{"house":1, "birds":35000, "age_days":21, "mode_id":"winter", "display_unit":"per_bird", "outside_t":10, "heater_on":true, "user_max_m3h":1000000}`

Smoke tests
- Start API as above, then run: `python3 scripts/smoke_test.py` or `make test-smoke`
- The script checks:
  - temperature interpolation (qmin: winter ≤ mid ≤ summer)
  - capacity capping (qmax ≤ user_max)
  - per_bird vs per_kg equivalence (same total flow)

Data seed for calculation
- Preferred: put real profile data into `data/vent_profile_seed.json`.
- Structure (per mode → array of points):
  - `day` (1..42), `body_weight_g`, `min_per_bird`, `max_per_bird`, `min_per_kg`, `max_per_kg`, optional `min_temp_c`, `rv_percent`.
- Daily mode: the engine reads exact daily points (no interpolation). If a specific day is missing, it falls back to the nearest previous day.
- If the file is empty or missing, the backend uses a built-in demo profile (synthetic values) just to visualize the flow.

Temperature interpolation and max capacity
- Calculation uses outside air temperature `outside_t` (°C):
  - `t <= 0` → uses Winter column
  - `0 < t < 15` → linear blend between Spring/Autumn (at 0°C) and Summer (at 15°C)
  - `t >= 15` → uses Summer column
- Tropical defaults to Summer behavior (> 15°C).
- Optional `user_max_m3h` caps the resulting Qmax (final `q_max_m3h` ≤ `user_max_m3h`). Raw (uncapped) value is returned as `q_max_nominal_m3h`.
- Heater correction: if `heater_on` is true, Qmin increases by per-bird adders: `+0.10` (days ≤14), `+0.05` (15–28), `+0.025` (≥29). Floor minimum ventilation applied: `≥0.15` (days 1–7) and `≥0.25` (days 8–14) in m³/h per bird.

Next
- We can add a transformer script to convert `data/ventilation_required.csv` into `data/vent_profile_seed.json` once we lock exact cell mapping from your Excel.

CSV → JSON seed (daily, no interpolation)
- Convert with: `python3 scripts/csv_to_seed.py --csv data/ventilation_required.csv --out data/vent_profile_seed.json --day-col <N> --weight-col <N> --winter-bird-col <N> --winter-kg-col <N> --spring-bird-col <N> --spring-kg-col <N> --summer-bird-col <N> --summer-kg-col <N> [--tropical-bird-col <N> --tropical-kg-col <N>] [--winter-bird-max-col <N> --winter-kg-max-col <N> ...] [--min-temp-col <N> --rv-col <N>]`
  or `make export-csv` + `make seed-json` (uses default column indices from the screenshots)
- Column indices are 1-based. Tropical defaults to summer mapping unless provided via `--tropical-*`.
- Use the screenshot to pick columns:
  - `day-col`: колонка с «Dag/Day» (1..42)
  - `weight-col`: синяя «Body weight» (в граммах — скрипт поймёт и кг)
  - winter = блок «Outside < 0°C» → `m3/br`, `m3/kg` (минимум)
  - spring_autumn = блок «Outside 0–15°C» → `m3/br`, `m3/kg` (минимум)
  - summer = блок «Outside > 15°C» → `m3/br`, `m3/kg` (минимум)
  - tropical: по вашему решению — используем нормы «> 15°C» (summer) по умолчанию
  - MAX (по желанию): задайте `--*-bird-max-col` и/или `--*-kg-max-col`; если указана только kg, per_bird вычисляется как kg * weight_kg
  - `min-temp-col` и `rv-col` — уставки «Min. Temp.» и «RV» (в %), берутся слева от таблицы и записываются для каждого дня (одни и те же для всех режимов)

Notes
- If your CSV uses comma decimals, the converter handles them.
- Only days 1..42 are included; missing days are skipped.
