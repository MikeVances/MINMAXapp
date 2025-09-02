from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from .routers import calc
from .routers import settings as settings_router

app = FastAPI(title="Ventilation Min/Max API", version="0.1.0")


@app.get("/healthz")
def healthz():
    return {"ok": True}


app.include_router(calc.router, prefix="/calc", tags=["calc"])
app.include_router(settings_router.router, prefix="/settings", tags=["settings"])

# Static UI (no Node/Next.js needed for MVP)
_static_dir = Path(__file__).parent / "static"
if _static_dir.exists():
    app.mount("/", StaticFiles(directory=str(_static_dir), html=True), name="ui")
