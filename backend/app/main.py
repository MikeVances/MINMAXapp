import os
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI

load_dotenv()  # загружает .env локально; на Render переменные берутся из дашборда
from fastapi.staticfiles import StaticFiles
from .routers import calc
from .routers import settings as settings_router
from .routers import flock
from .routers import thermal
from .routers import tools

app = FastAPI(title="Ventilation Min/Max API", version="0.2.0")


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/version")
def version():
    # RENDER_GIT_COMMIT прокидывается Render автоматически при каждом деплое
    commit = os.environ.get("RENDER_GIT_COMMIT", "local")[:7]
    return {"commit": commit}


app.include_router(calc.router, prefix="/calc", tags=["calc"])
app.include_router(settings_router.router, prefix="/settings", tags=["settings"])
app.include_router(flock.router, tags=["flock"])
app.include_router(thermal.router, prefix="/thermal", tags=["thermal"])
app.include_router(tools.router, prefix="/calc/tools", tags=["tools"])

# Static UI (no Node/Next.js needed for MVP)
_static_dir = Path(__file__).parent / "static"
if _static_dir.exists():
    app.mount("/", StaticFiles(directory=str(_static_dir), html=True), name="ui")
