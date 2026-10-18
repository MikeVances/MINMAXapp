import hashlib
import os
import re
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, Response
from fastapi.middleware.gzip import GZipMiddleware
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

# Сжатие ответов: словари, страницы и скрипты — текст, gzip уменьшает их в 3–4 раза
# (пять словарей 259 → 84 КБ). Мелочь меньше 1 КБ не жмём — заголовки дороже выигрыша
app.add_middleware(GZipMiddleware, minimum_size=1024)

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

# ─── Статика с версиями по содержимому ───────────────────────────────────────
# Раньше: ETag без Cache-Control (браузер переспрашивал каждый файл на каждой
# странице) и ручной ?v= у двух файлов из десятка — остальные после деплоя могли
# остаться старыми в кэше рядом с новой страницей.
#
# Теперь страница отдаётся с no-cache (проверка по ETag), а каждая её ссылка на
# локальный .js/.css получает ?v=<хеш содержимого файла>. Файл с ?v= кэшируется
# навсегда (immutable): изменился — изменился хеш, браузер возьмёт новый адрес.
# Нумеровать вручную больше нечего.
_ASSET_REF = re.compile(r'(src|href)="\./([^"?#]+\.(?:js|css))(?:\?v=[^"]*)?"')
_IMMUTABLE = "public, max-age=31536000, immutable"


class VersionedStaticFiles(StaticFiles):
    _hash_cache: dict = {}

    def _file_version(self, rel: str) -> str | None:
        path = Path(self.directory) / rel
        try:
            stat = path.stat()
        except OSError:
            return None   # не наш файл (например, /theme.css — маршрут, не статика)
        key = (rel, stat.st_mtime_ns, stat.st_size)
        if key not in self._hash_cache:
            self._hash_cache[key] = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
        return self._hash_cache[key]

    def _versioned_html(self, html: str) -> str:
        def repl(m: re.Match) -> str:
            version = self._file_version(m.group(2))
            return m.group(0) if version is None else f'{m.group(1)}="./{m.group(2)}?v={version}"'
        return _ASSET_REF.sub(repl, html)

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        file_path = getattr(response, "path", None)
        if response.status_code != 200 or file_path is None:
            return response

        if str(file_path).endswith(".html"):
            body = self._versioned_html(Path(file_path).read_text(encoding="utf-8")).encode("utf-8")
            etag = '"' + hashlib.sha256(body).hexdigest()[:16] + '"'
            headers = {"ETag": etag, "Cache-Control": "no-cache"}
            if etag in dict(scope.get("headers") or []).get(b"if-none-match", b"").decode():
                return Response(status_code=304, headers=headers)
            return Response(body, media_type="text/html; charset=utf-8", headers=headers)

        versioned = re.search(rb"(?:^|&)v=", scope.get("query_string", b"")) is not None
        response.headers["Cache-Control"] = _IMMUTABLE if versioned else "no-cache"
        return response


# Static UI (no Node/Next.js needed for MVP)
_static_dir = Path(__file__).parent / "static"
if _static_dir.exists():
    app.mount("/", VersionedStaticFiles(directory=str(_static_dir), html=True), name="ui")
