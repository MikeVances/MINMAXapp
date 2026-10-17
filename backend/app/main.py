import os
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, Response
from fastapi.responses import FileResponse

load_dotenv(Path(__file__).parent.parent / ".env")  # backend/.env — работает из любой рабочей директории
from fastapi.staticfiles import StaticFiles
from .routers import calc
from .routers import settings as settings_router
from .routers import thermal
from .routers import tools
from .routers import feedback as feedback_router
from .routers import growth_profiles as growth_profiles_router
from .core.paths import data_path

app = FastAPI(title="Ventilation Min/Max API", version="0.2.0")

# Оформление площадки: необязательный файл с переопределениями CSS-переменных
# из static/styles.css. Лежит в data/, как и остальные настройки площадки,
# а не в static/ — чтобы кастомизация не требовала правок в коде и не терялась
# при обновлении приложения из git.
THEME_CSS_PATH = data_path("THEME_CSS", "data/theme.css")


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/version")
def version():
    # RENDER_GIT_COMMIT прокидывается Render автоматически при каждом деплое
    commit = os.environ.get("RENDER_GIT_COMMIT", "local")[:7]
    return {"commit": commit}


@app.get("/theme.css", include_in_schema=False)
def theme_css():
    """
    Переопределения оформления (data/theme.css) поверх static/styles.css.
    Страницы подключают его всегда; без файла отдаём пустой CSS, а не 404,
    чтобы консоль браузера не засорялась ошибкой загрузки.
    no-cache: правку темы должно быть видно по обычному обновлению страницы.
    """
    if THEME_CSS_PATH.is_file():
        return FileResponse(THEME_CSS_PATH, media_type="text/css", headers={"Cache-Control": "no-cache"})
    return Response(content="/* no site theme: create data/theme.css */\n", media_type="text/css")


app.include_router(calc.router, prefix="/calc", tags=["calc"])
app.include_router(settings_router.router, prefix="/settings", tags=["settings"])
app.include_router(thermal.router, prefix="/thermal", tags=["thermal"])
app.include_router(tools.router, prefix="/calc/tools", tags=["tools"])
app.include_router(feedback_router.router, tags=["feedback"])
app.include_router(growth_profiles_router.router, prefix="/profiles", tags=["profiles"])

# Static UI (no Node/Next.js needed for MVP)
_static_dir = Path(__file__).parent / "static"
if _static_dir.exists():
    app.mount("/", StaticFiles(directory=str(_static_dir), html=True), name="ui")
