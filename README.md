# 🐔 MINMAXapp — Broiler House Ventilation Calculator

Web application for calculating ventilation parameters in broiler poultry houses.  
Based on Ross/Cobb/Aviagen breed guides and CIGR thermal standards.

---

## Features

- **Ventilation min/max** — target airflow by flock age and outside conditions
- **Farm Audit** — step-by-step heat balance analysis:
  - Building dimensions & UA coefficient calibration
  - Heater duty cycle estimation
  - Evaporative (Pad & Fan) cooling calculator
  - Tunnel ventilation speed calculator
- **5 languages** — EN / RU / PL / DE / FR with native poultry industry terminology
- **Feedback** — in-app form → Telegram bot
- **Single-page UI** — no build step, pure HTML/CSS/JS

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI (Python 3.10+) |
| Data storage | JSON files (single-farm MVP) |
| Frontend | Vanilla JS + CSS custom properties |
| i18n | Synchronous `window.LOCALES` engine |
| Deploy | Render (free tier) |

## Physics

- Bird heat: `Q = 6.90 × W^0.75 × N` W (CIGR standard)
- Ventilation heat loss: `Q = V̇_min × 0.335 × ΔT`
- UA calibration: temperature drop method in empty house
- Evaporative cooling: pad efficiency × psychrometric correction

## Quick Start

```bash
cd backend
pip install .
uvicorn app.main:app --reload --port 8000
# Open http://localhost:8000
```

## Environment Variables

```bash
cp backend/.env.example backend/.env
# Fill in:
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

## Deploy to Render

| Setting | Value |
|---------|-------|
| Root Directory | `backend` |
| Build Command | `pip install .` |
| Start Command | `uvicorn app.main:app --host 0.0.0.0 --port $PORT` |

Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in Render → Environment.

## Data Sources

- Ross 308 Broiler Performance Objectives 2022
- Cobb Broiler Management Guide
- Aviagen Essential Ventilation Management 2019
- CIGR Report Vol. II — Climatization of Animal Houses

## License

MIT — open source, free to use and adapt.
