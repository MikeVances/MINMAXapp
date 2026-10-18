import os
import json
import asyncio
import logging
import threading
import time
import urllib.request
from collections import defaultdict, deque

from fastapi import APIRouter, Request

from ..api_errors import api_error
from pydantic import BaseModel, Field

router = APIRouter()
logger = logging.getLogger(__name__)

# Telegram принимает до 4096 символов; 2000 с запасом на заголовок и адрес страницы
MAX_MESSAGE_LEN = 2000

# Не больше RATE_LIMIT сообщений за RATE_WINDOW_S с одного адреса: форма открыта
# всем, и без лимита её можно использовать для спама в чат владельца
RATE_LIMIT = 5
RATE_WINDOW_S = 600

_recent: dict[str, deque] = defaultdict(deque)
_recent_lock = threading.Lock()

# Больше адресов в памяти не держим: при переполнении выбрасываем тех, чьё окно
# уже истекло. Иначе поток запросов с разных адресов растил бы словарь без предела
MAX_TRACKED_CLIENTS = 10_000

# Длина цепочки X-Forwarded-For пишется в журнал один раз — по ней на живой
# площадке видно, сколько узлов дописывает прокси (сами адреса не пишем)
_chain_logged = False


class FeedbackPayload(BaseModel):
    message: str = Field(..., max_length=MAX_MESSAGE_LEN)
    page: str = Field("", max_length=200)


def _trusted_hops() -> int:
    """Сколько записей в конце X-Forwarded-For дописали НАШИ прокси (env TRUSTED_PROXY_HOPS).

    Читается при каждом запросе, как WRITE_TOKEN: меняется в панели площадки без
    правки кода. 0 — заголовок не учитывается вовсе (без прокси ему нельзя верить).
    """
    try:
        return max(int(os.getenv("TRUSTED_PROXY_HOPS", "0")), 0)
    except ValueError:
        return 0


def _client_key(request: Request) -> str:
    # Прокси ДОПИСЫВАЕТ адрес того, кто к нему пришёл, в конец X-Forwarded-For и
    # не очищает то, что прислал клиент. Поэтому первая запись — что угодно, что
    # клиент написал сам: с ней лимит обходился подстановкой нового адреса в каждом
    # запросе. Верить можно только записи, которую добавил наш последний прокси:
    # она стоит на позиции hops с конца. Короче цепочка — заголовок поддельный
    # или прокси не наш, берём адрес соединения
    global _chain_logged
    peer = request.client.host if request.client else "unknown"
    hops = _trusted_hops()
    forwarded = request.headers.get("x-forwarded-for", "")
    if not hops or not forwarded:
        return peer
    chain = [part.strip() for part in forwarded.split(",") if part.strip()]
    if not _chain_logged:
        logger.info("feedback: X-Forwarded-For из %d записей, TRUSTED_PROXY_HOPS=%d", len(chain), hops)
        _chain_logged = True
    return chain[-hops] if len(chain) >= hops else peer


def _allow(key: str, now: float) -> bool:
    """Скользящее окно: старые отметки выбрасываются, новая добавляется, если есть место."""
    with _recent_lock:
        if len(_recent) >= MAX_TRACKED_CLIENTS and key not in _recent:
            for stale in [k for k, s in _recent.items() if not s or now - s[-1] > RATE_WINDOW_S]:
                del _recent[stale]
            if len(_recent) >= MAX_TRACKED_CLIENTS:
                return False   # все окна живые — новый адрес ждёт, а не растит память
        stamps = _recent[key]
        while stamps and now - stamps[0] > RATE_WINDOW_S:
            stamps.popleft()
        if len(stamps) >= RATE_LIMIT:
            return False
        stamps.append(now)
        return True


def _post_telegram(token: str, chat_id: str, text: str) -> int:
    """Синхронный HTTP POST к Telegram API (запускается в thread pool)."""
    url  = f"https://api.telegram.org/bot{token}/sendMessage"
    # Без parse_mode: текст пользователя уходит как есть. С Markdown любой
    # непарный «_» или «*» в сообщении давал отказ Telegram → 502
    body = json.dumps({"chat_id": chat_id, "text": text})
    req  = urllib.request.Request(
        url, data=body.encode(), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status


@router.post("/feedback")
async def send_feedback(payload: FeedbackPayload, request: Request):
    token   = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        raise api_error(503, "feedback_not_configured")

    if not payload.message.strip():
        raise api_error(400, "feedback_empty")

    if not _allow(_client_key(request), time.monotonic()):
        raise api_error(429, "feedback_rate_limited")

    text = "📬 MINMAXapp Feedback\n"
    if payload.page:
        text += f"📄 Page: {payload.page}\n"
    text += f"\n{payload.message}"

    try:
        status = await asyncio.to_thread(_post_telegram, token, chat_id, text)
    except Exception:
        raise api_error(502, "feedback_delivery_failed")

    if status != 200:
        raise api_error(502, "feedback_delivery_failed")

    return {"ok": True}
