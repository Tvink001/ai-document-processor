"""Entry point. Runs the aiogram polling loop + the FastAPI callback
server together in one process via asyncio.gather.

Architecture:
- aiogram: owns the Telegram webhook (set via long-polling in v1).
- FastAPI/uvicorn: exposes `/health` + `/n8n-callback` on WEB_PORT.
- One Bot instance is shared — Python is the only thing that talks
  to Telegram in the whole pipeline.

The `mode` setting in pydantic-Settings is forward-compat: today both
"polling" and "webhook" run the same way (polling + uvicorn). A future
revision can flip aiogram into webhook mode and mount it under the same
FastAPI app for a single-port deploy.
"""

from __future__ import annotations

import asyncio
import logging
import sys

import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from bot.callbacks_app.n8n_result import build_app
from bot.config import settings
from bot.handlers.documents import documents_router
from bot.handlers.folders import folders_router
from bot.handlers.start import start_router
from bot.services.drive import DriveService
from bot.services.n8n import N8nClient
from bot.services.sheets import SheetsService

logger = logging.getLogger(__name__)


def _build_bot() -> Bot:
    return Bot(
        token=settings.telegram_bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


def _build_dispatcher() -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())

    # Singletons injected into every handler via aiogram workflow-data DI.
    dp["sheets"] = SheetsService(
        service_account_path=settings.google_service_account_path,
        sheet_id=settings.google_sheet_id,
    )
    dp["drive"] = DriveService(
        service_account_path=settings.google_service_account_path,
    )
    dp["n8n"] = N8nClient(
        webhook_url=settings.n8n_webhook_url,
        secret=settings.n8n_webhook_secret.get_secret_value(),
    )

    dp.include_router(start_router)
    dp.include_router(folders_router)
    dp.include_router(documents_router)
    return dp


async def _run() -> None:
    bot = _build_bot()
    dp = _build_dispatcher()
    app = build_app(bot)

    config = uvicorn.Config(
        app,
        host=settings.web_host,
        port=settings.web_port,
        log_level=settings.log_level.lower(),
        loop="asyncio",
    )
    server = uvicorn.Server(config)

    # delete_webhook drops anything Telegram might still have from the
    # n8n era. drop_pending_updates=True clears the buffer so old test
    # messages don't re-fire on first boot.
    await bot.delete_webhook(drop_pending_updates=True)

    logger.info(
        "Starting bot: polling=on, fastapi=%s:%s",
        settings.web_host,
        settings.web_port,
    )

    await asyncio.gather(
        dp.start_polling(bot),
        server.serve(),
    )


def main() -> None:
    logging.basicConfig(
        level=settings.log_level.upper(),
        stream=sys.stdout,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    asyncio.run(_run())


if __name__ == "__main__":
    main()
