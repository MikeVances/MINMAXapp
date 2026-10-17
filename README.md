# 🐔 MINMAXapp — Broiler House Ventilation Calculator

Open-source web tool for poultry farm engineers and technologists.  
Calculates ventilation parameters, heat balance, and cooling requirements for broiler houses — directly in the browser, no installation needed.

> Built for practical use on real farms. Physics-based, not rule-of-thumb.

---

## What it does

### Ventilation Min/Max
Enter flock age and outside temperature — get target airflow ranges for the current grow-out day. Supports multi-house farms with independent tabs per house.

### Farm Audit (Heat Balance)
Step-by-step analysis of the thermal envelope:

1. **Building dimensions** — volume, wall/roof area
2. **Heater configuration** — gas or electric, total installed capacity
3. **UA calibration** — measure the building's actual heat loss coefficient from a temperature-drop test in an empty house
4. **Heater cycle analysis** — required heating power vs. installed capacity at any outside temperature, bird age and stocking density

### Evaporative Cooling (Pad & Fan)
Calculates effective temperature reduction from wet pad systems. Accounts for outside humidity and pad efficiency.

### Tunnel Ventilation
Minimum cross-section airspeed for effective tunnel mode. Flags when evaporative cooling becomes necessary.

---

## Physics

The app uses first-principles heat balance, not lookup tables:

```
Q_heater = Q_walls + Q_ventilation − Q_birds

Q_walls        = UA × ΔT                          (W)
Q_ventilation  = V̇_min × 0.335 × ΔT              (W)
Q_birds        = 6.90 × W^0.75 × N                (W)   ← CIGR standard
```

Where:
- `UA` — overall heat transfer coefficient of the building envelope (W/K), measured by calibration
- `V̇_min` — minimum ventilation rate (m³/h)
- `W` — average bird weight (kg), `N` — number of birds
- `0.335` — volumetric heat capacity of air (Wh/m³·K)

Minimum ventilation is the larger of two limits:

```
Q_min,CO2      = 10.62 × W^0.75 × 0.153 / 2.6 × safety      (m³/h per bird, CIGR 1984)
Q_min,moisture = G / (ρ × (W_in − W_out))                    (m³/h)
G              = 10.62 × W^0.75 × (1 − f_s(T)) / h_fg × N    (vapour from birds and litter)
f_s(T)         = [0.61 × (1000 + 20 × (20 − T)) − 0.228 × T²] / 1000   (CIGR 2002, house level)
```

Growth curves (body weight by day) come from breeder performance objectives; the
temperature setpoint follows the Ross Broiler Handbook 2025 apparent-temperature table
(by body weight and target RH).

---

## Interface

- Single-page app — works offline after first load
- **5 languages**: 🇬🇧 EN · 🇷🇺 RU · 🇵🇱 PL · 🇩🇪 DE · 🇫🇷 FR  
  Translations use native poultry industry terminology, not literal translation
- Inline feedback form → Telegram

---

## Run locally

```bash
git clone https://github.com/MikeVances/MINMAXapp
cd MINMAXapp/backend
pip install .
uvicorn app.main:app --reload
# → http://localhost:8000
```

Requires Python 3.10+. No database, no external services needed for core functionality.

**Shared deployments.** Saved settings, growth profile and flock diary are one shared state for
all visitors. On a public instance set `WRITE_TOKEN` in the environment: endpoints that change
saved data then require the `X-Write-Token` header (the UI asks for the token once and remembers
it). Calculations stay open. Without `WRITE_TOKEN` writes are open — fine for local use.

---

## Data Sources

| Source | Used for |
|--------|---------|
| Ross 308 Broiler Performance Objectives, 2022 | Temperature curves, live weight targets |
| Cobb Broiler Management Guide | Ventilation profiles |
| Aviagen Essential Ventilation Management, 2019 | Min/max airflow methodology |
| CIGR Report Vol. II — Climatization of Animal Houses | Bird heat production formula |
| EN 13779 / ASHRAE | Air properties, psychrometrics |

---

## Contributing

Issues and pull requests are welcome. If you work in poultry production and notice something wrong with the numbers — please open an issue with the flock parameters and expected values. Real-world corrections are the most valuable contribution.

---

## License

MIT — use freely, adapt for your farm or software.
