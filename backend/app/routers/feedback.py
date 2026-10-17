import os
import json
import asyncio
import threading
import time
import urllib.request
from collections import defaultdict, deque

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter()

# Telegram принимает до 4096 символов; 2000 с запасом на заголовок и адрес страницы
MAX_MESSAGE_LEN = 2000

# Не больше RATE_LIMIT сообщений за RATE_WINDOW_S с одного адреса: форма открыта
# всем, и без лимита её можно использовать для спама в чат владельца
RATE_LIMIT = 5
RATE_WINDOW_S = 600

_recent: dict[str, deque] = defaultdict(deque)
_recent_lock = threading.Lock()


class FeedbackPayload(BaseModel):
    message: str = Field(..., max_length=MAX_MESSAGE_LEN)
    page: str = Field("", max_length=200)


def _client_key(request: Request) -> str:
    # За прокси Render адрес клиента — первый в X-Forwarded-For. Заголовок можно
    # подделать, но для защиты чата от случайного флуда этого достаточно
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _allow(key: str, now: float) -> bool:
    """Скользящее окно: старые отметки выбрасываются, новая добавляется, если есть место."""
    with _recent_lock:
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
        raise HTTPException(status_code=503, detail="Feedback not configured")

    if not payload.message.strip():
        raise HTTPException(status_code=400, detail="Empty message")

    if not _allow(_client_key(request), time.monotonic()):
        raise HTTPException(status_code=429, detail="Too many messages, try later")

    text = "📬 MINMAXapp Feedback\n"
    if payload.page:
        text += f"📄 Page: {payload.page}\n"
    text += f"\n{payload.message}"

    try:
        status = await asyncio.to_thread(_post_telegram, token, chat_id, text)
    except Exception:
        raise HTTPException(status_code=502, detail="Telegram delivery failed")

    if status != 200:
        raise HTTPException(status_code=502, detail="Telegram delivery failed")

    return {"ok": True}
