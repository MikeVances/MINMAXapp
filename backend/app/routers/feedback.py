import os
import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


class FeedbackPayload(BaseModel):
    message: str
    page: str = ""


@router.post("/feedback")
async def send_feedback(payload: FeedbackPayload):
    token   = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        raise HTTPException(status_code=503, detail="Feedback not configured")

    if not payload.message.strip():
        raise HTTPException(status_code=400, detail="Empty message")

    text = f"📬 *MINMAXapp Feedback*\n"
    if payload.page:
        text += f"📄 Page: `{payload.page}`\n"
    text += f"\n{payload.message}"

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
        )

    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail="Telegram delivery failed")

    return {"ok": True}
