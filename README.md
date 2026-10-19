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
Pad outlet temperature, airflow at the fan operating point with pad resistance, water use and recommended pad area; sufficiency is judged at the fan end.

### Tunnel Ventilation
Air speed, wind cooling and THVI at the fan end, tunnel temperature limit. Flags when pad cooling becomes necessary.

---

## Physics

The app uses first-principles balances, not lookup tables. One house-level heat model
(CIGR 2002) feeds every balance:

```
f_T     = (1000 + 20 × (20 − T_in)) / 1000                 total heat vs 20 °C (+2 %/°C below)
Q_sens  = [0.61 × (1000 + 20 × (20 − T_in)) − 0.228 × T_in²] / 1000 × 10.62 × W^0.75   (W/bird)
Q_lat   = 10.62 × W^0.75 × f_T − Q_sens                     (W/bird, birds + litter)
```

Minimum ventilation is the larger of two limits, with open-flame burners in both:

```
Q_min,CO2      = 10.62 × W^0.75 × 0.153 / 2.6 × 1.5 × N_eff  + Q_dilution(d)   (CIGR 1984)
Q_min,moisture = (G_birds + G_burner(d)) / (ρ_in × (W_in − W_out))  ≤  Q_ceiling
Q_ceiling      = 4 × Q_min,CO2 before tunnel age, tunnel flow after
```

Maximum ventilation is the sensible heat balance, capped by the same ceiling:

```
Q_max = (N_eff × Q_sens − UA × ΔT) × 3600 / (ρ_in × 1006 × ΔT)
```

Burner duty `d` is solved together with the burners' own CO₂-dilution air
(≈ 58 m³/h per kW), which has to be heated as well:

```
P × d = UA × ΔT + ρ_in × 1006 × ΔT × Q_min(d) / 3600 − N_eff × Q_sens
```

Where `UA` is the building heat-loss coefficient (W/K) from a cooling-curve test in the
empty house — used only for its own house and only if plausible (test ≥ 10 min, mean
envelope U 0.1–8 W/(m²·K)). Tunnel mode starts when the heat balance needs more than half
of the tunnel flow (transitional ventilation covers 40–50 %, Ross 2025), with air speed
limited by age (Cobb 2021). Tunnel and pad checks are judged at the fan end, where the air
is warmer by `N × Q_sens / (ρ × Cp × Q)`.

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
cd MINMAXapp
pip install -r requirements.txt
uvicorn backend.app.main:app --reload
# → http://localhost:8000
```

`requirements.txt` is the single list of dependencies — Render, `make venv` and
a local install all read it. Or `make run-api` to create a venv and start the API in one step.

Requires Python 3.10+. No database, no external services needed for core functionality.

**Behind a reverse proxy under a path prefix.** The UI uses relative URLs (`./calc/...`), so it
works at `https://host/prefix/` without any configuration — but only with the trailing slash.
At `https://host/prefix` (no slash) the browser resolves `./calc` to `/calc` and every request
misses. Redirect the bare prefix at the proxy, for nginx:

```nginx
location = /prefix { return 301 /prefix/; }
location /prefix/ { proxy_pass http://127.0.0.1:8000/; }
```

**Shared deployments.** Saved settings and growth profiles are one shared state for
all visitors. On a public instance set `WRITE_TOKEN` in the environment: endpoints that change
saved data then require the `X-Write-Token` header (the UI asks for the token once and remembers
it). Calculations stay open. Without `WRITE_TOKEN` writes are open — fine for local use.

**Where data lives.** The list of houses (sizes, birds, fans) is kept in each browser's local
storage — every device has its own. Heat-loss data — dimensions, heaters and the UA calibration —
is stored on the server per house id (`data/thermal_config.json`, `{"houses": {...}}`); renaming a
house on the home page moves its record. Settings and growth profiles are shared server-side.

**Updating the copy on the internal server.** `scripts/deploy_lan.sh` does the whole update and
checks it: git and pip as the repository owner, local edits on the server stashed (not lost),
`pull --ff-only`, `pip install`, service restart, then it waits for `/healthz` and compares the
commit in `/version` with the one just pulled; if the new version does not come up it rolls back to
the previous revision. `--dry-run` only lists the incoming commits.

```bash
ssh -t cdto@192.168.10.245 sudo /srv/minmax/scripts/deploy_lan.sh
```

**Backup.** Farm Settings → *Download farm data* saves settings, your growth profiles, heat-loss data
per house and this browser's houses to one JSON file; *Restore from file* puts them back (all parts are
validated before anything is written). Use it before deploying to a host with an ephemeral disk.

**Site climate.** Farm Settings take the farm altitude (site pressure, ASHRAE standard atmosphere) and
coordinates; *Get design conditions* derives ASHRAE ch. 14 design values (99.6 % heating, 0.4 % cooling
with coincident wet bulb, 0.4 % wet bulb) from 10 years of hourly ERA5 reanalysis via Open-Meteo —
data CC BY 4.0, free access for non-commercial use.

**Behind a reverse proxy.** The feedback form allows 5 messages per 10 minutes per client address.
A proxy appends the address it saw to the end of `X-Forwarded-For`; everything to the left is
whatever the client sent. Set `TRUSTED_PROXY_HOPS` to the number of entries your own proxies append
(`1` for a single nginx or the Render load balancer — `render.yaml` sets it). With `0` (the default)
the header is ignored and the connection address is used: without a proxy the header is untrusted.

---

## Customizing the look

All colours, radii and the font are CSS custom properties declared once in
`backend/app/static/styles.css` (`:root`). Markup and scripts reference only `var(--…)`.
To restyle a deployment, create `data/theme.css` (see `data/theme.example.css`) and
override the variables you need — the file is served at `/theme.css` after the base
stylesheet and is not tracked by git, so updates never overwrite it. Path can be
changed with the `THEME_CSS` environment variable.

The markup carries no inline styles: layout uses small utility classes and a few
named components (`.hint`, `.note-ok`, `.res-table` …) defined in the same file, and
scripts switch *tones* (`setTone(el, 'danger')`, `ui.js`) rather than colours, so a
theme reaches dynamic status colours too. A test fails if inline styles creep back.

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

**Tests.** `make test` runs the suite (physics references, API, page code; some tests run the
real `i18n.js` in Node). `make test-e2e` adds a browser smoke test: it starts its own server on
temporary data, opens every page in Chromium, presses the main buttons and fails on any JS error.
GitHub Actions runs both on every push (Python 3.11, as on Render).

Issues and pull requests are welcome. If you work in poultry production and notice something wrong with the numbers — please open an issue with the flock parameters and expected values. Real-world corrections are the most valuable contribution.

---

## License

MIT — use freely, adapt for your farm or software.
