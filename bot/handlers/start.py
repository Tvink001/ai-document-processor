"""/start handler — greeting + main inline keyboard.

Upserts the user row so the rest of the bot can rely on its existence."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.callbacks import NavCB
from bot.keyboards.inline import main_menu_no_folder, main_menu_with_folder
from bot.services.sheets import SheetsService

logger = logging.getLogger(__name__)
start_router = Router()

WELCOME = (
    "Привет, я P3 — парсер банковских выписок.\n\n"
    "Пришли мне PDF (или несколько) — я разнесу транзакции по категориям "
    "и верну Excel с цветной разметкой неуверенных строк.\n\n"
    "Если работаешь с разными клиентами — создай папку, и все файлы "
    "будут аккуратно сложены в неё на Drive."
)

SEND_INFO_HINT = (
    "📎 Просто перетащи PDF в этот чат. Можно сразу несколько "
    "(до 6 за один раз) — обработаю пачкой."
)


@start_router.message(CommandStart())
async def cmd_start(
    message: Message,
    state: FSMContext,
    sheets: SheetsService,
) -> None:
    if message.from_user is None:
        return
    await state.clear()
    user = await sheets.upsert_user(
        chat_id=message.chat.id,
        username=message.from_user.username or "",
        first_name=message.from_user.first_name or "",
    )
    if user.current_folder_id:
        kb = main_menu_with_folder(user.current_folder_name or "папка")
    else:
        kb = main_menu_no_folder()
    await message.answer(WELCOME, reply_markup=kb)


@start_router.callback_query(NavCB.filter(F.action == "send_info"))
async def on_send_info(query: CallbackQuery) -> None:
    await query.answer()
    if isinstance(query.message, Message):
        await query.message.answer(SEND_INFO_HINT)


@start_router.callback_query(NavCB.filter(F.action == "cancel"))
async def on_cancel(query: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await query.answer("Отменено")
    if isinstance(query.message, Message):
        try:
            await query.message.edit_reply_markup(reply_markup=None)
        except Exception:
            logger.debug("cancel edit_reply_markup failed", exc_info=True)
