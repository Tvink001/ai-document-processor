"""FastAPI app that receives WF04b's POST callback and replies on Telegram.

The bot is the only Telegram surface; n8n owns no Telegram credentials.
n8n calls this endpoint with the finished session result and Python
posts the final message — Excel link + short summary — to the user's chat.

Auth: X-Callback-Token header MUST match `settings.callback_token`.
Anything missing or wrong → 401, NO Telegram side-effect.
"""

from __future__ import annotations

import logging
from typing import Annotated

from aiogram import Bot
from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field

from bot.config import settings

logger = logging.getLogger(__name__)


class N8nCallbackPayload(BaseModel):
    chat_id: int
    session_id: str
    xlsx_url: str = ""
    summary: str = ""
    error: str = ""
    completed_at: str = Field(default="")


async def _health(_request: Request) -> dict[str, str]:
    return {"status": "ok"}


def build_app(bot: Bot) -> FastAPI:
    """Construct a FastAPI app whose handlers can send messages via `bot`."""
    app = FastAPI(
        title="P3 bot — n8n callback receiver",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return await _health(None)  # type: ignore[arg-type]

    @app.post("/n8n-callback")
    async def n8n_callback(
        payload: N8nCallbackPayload,
        x_callback_token: Annotated[str | None, Header(alias="X-Callback-Token")] = None,
    ) -> dict[str, str]:
        expected = settings.callback_token.get_secret_value()
        if not expected or x_callback_token != expected:
            logger.warning(
                "Rejected callback for chat_id=%s — bad/missing token",
                payload.chat_id,
            )
            raise HTTPException(status_code=401, detail="bad token")

        if payload.error:
            text = (
                "⚠ Не удалось обработать сессию.\n"
                f"<code>{payload.error[:300]}</code>"
            )
        elif payload.xlsx_url:
            body = payload.summary.strip() or "Готово."
            text = (
                f"✅ {body}\n\n"
                f"<a href=\"{payload.xlsx_url}\">Открыть Excel</a>"
            )
        else:
            text = payload.summary.strip() or "✅ Готово (без файла)."

        try:
            await bot.send_message(
                chat_id=payload.chat_id,
                text=text,
                disable_web_page_preview=True,
            )
        except Exception:
            logger.exception(
                "Telegram send failed for callback session_id=%s",
                payload.session_id,
            )
            # Still 200 — n8n shouldn't retry; investigate logs.
        # 200 + JSON body (not 204) so n8n's responseFormat:json doesn't
        # interpret empty body as a transient failure and retry 3x.
        return {"status": "ok", "session_id": payload.session_id}

    return app
