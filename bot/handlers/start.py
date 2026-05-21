"""/start handler — greeting + main inline keyboard.

Upserts the user row so the rest of the bot can rely on its existence."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ReplyKeyboardMarkup

from bot.callbacks import NavCB
from bot.keyboards.inline import (
    folder_picker,
)
from bot.keyboards.reply import (
    BTN_CREATE,
    BTN_LEAVE,
    BTN_OPEN,
    BTN_SEND,
    main_reply_no_folder,
    main_reply_with_folder,
)
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


async def _menu_for_user(
    sheets: SheetsService,
    chat_id: int,
) -> tuple[str, ReplyKeyboardMarkup]:
    """Pick the welcome text + sticky reply keyboard based on current folder."""
    user = await sheets.get_user(chat_id)
    if user and user.current_folder_id:
        return (
            f"📂 Текущая папка: <b>{user.current_folder_name}</b>",
            main_reply_with_folder(user.current_folder_name),
        )
    return (WELCOME, main_reply_no_folder())


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
        text = f"📂 Текущая папка: <b>{user.current_folder_name}</b>"
        reply_kb = main_reply_with_folder(user.current_folder_name)
    else:
        text = WELCOME
        reply_kb = main_reply_no_folder()
    await message.answer(text, reply_markup=reply_kb)


@start_router.message(Command("menu"))
async def cmd_menu(message: Message, sheets: SheetsService) -> None:
    text, kb = await _menu_for_user(sheets, message.chat.id)
    await message.answer(text, reply_markup=kb)


@start_router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext, sheets: SheetsService) -> None:
    await state.clear()
    text, kb = await _menu_for_user(sheets, message.chat.id)
    await message.answer("Отменено. " + text, reply_markup=kb)


@start_router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "Я парсю украинские банковские выписки.\n\n"
        "📄 Просто перетащи PDF в чат — я разнесу транзакции по категориям и "
        "верну Excel с подсветкой неуверенных строк.\n\n"
        "Команды:\n"
        "• /start — главное меню\n"
        "• /menu — то же меню (sticky кнопки)\n"
        "• /cancel — прервать ввод (например, имя папки)\n"
        "• /help — это сообщение",
    )


# Reply-keyboard text routing — F.text matches the literal button label.

@start_router.message(F.text == BTN_SEND)
@start_router.message(F.text.startswith("📄 В «"))
async def on_send_reply(message: Message) -> None:
    await message.answer(SEND_INFO_HINT)


@start_router.message(F.text == BTN_CREATE)
async def on_create_reply(message: Message, state: FSMContext) -> None:
    from bot.handlers.folders import MSG_ASK_NAME  # local import to avoid cycle
    from bot.states import Folder

    await state.set_state(Folder.awaiting_name)
    await message.answer(MSG_ASK_NAME)


@start_router.message(F.text == BTN_OPEN)
async def on_open_reply(message: Message, sheets: SheetsService) -> None:
    from bot.handlers.folders import MSG_NO_FOLDERS, MSG_PICK_FOLDER

    folders = await sheets.list_folders(chat_id=message.chat.id, limit=10)
    if not folders:
        await message.answer(MSG_NO_FOLDERS)
        return
    await message.answer(MSG_PICK_FOLDER, reply_markup=folder_picker(folders))


@start_router.message(F.text == BTN_LEAVE)
async def on_leave_reply(message: Message, sheets: SheetsService) -> None:
    await sheets.set_current_folder(
        chat_id=message.chat.id,
        folder_id="",
        folder_name="",
    )
    await message.answer(
        "Вышел из папки — теперь файлы будут попадать прямо в архив.",
        reply_markup=main_reply_no_folder(),
    )


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
