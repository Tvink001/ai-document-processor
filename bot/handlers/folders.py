"""Folder management — create / list / pick / leave.

State machine (single state, `Folder.awaiting_name`):
- create button  → set state → prompt for name
- text in state  → create Drive folder + Sheets row → unset state
- list   button  → no state change → show picker keyboard
- pick   button  → set current folder → confirm
- leave  button  → clear current folder → confirm

If the user is already inside a folder when they create another, the
new one replaces the active selection (no nesting).
"""

from __future__ import annotations

import logging
import re

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.callbacks import FolderCB
from bot.config import settings
from bot.keyboards.inline import (
    folder_picker,
    main_menu_no_folder,
    main_menu_with_folder,
)
from bot.services.drive import DriveService
from bot.services.sheets import SheetsService
from bot.states import Folder

logger = logging.getLogger(__name__)
folders_router = Router()

MSG_ASK_NAME = (
    "Как назовём папку? Напиши короткое имя (например: Candidate 1, "
    "Иван Петренко, ООО Рога и Копыта)."
)
MSG_NAME_TOO_SHORT = "Имя слишком короткое. Хотя бы 2 символа."
MSG_NAME_TOO_LONG = "Имя слишком длинное. Не больше 80 символов."
MSG_NAME_BAD_CHARS = (
    "В имени остались только пробелы или непечатные символы. Попробуй ещё раз."
)
MSG_CREATE_FAILED = "Не удалось создать папку. Попробуй ещё раз чуть позже."
MSG_NO_FOLDERS = "У тебя пока нет папок. Создай первую кнопкой выше."
MSG_PICK_FOLDER = "Выбери папку для работы:"
MSG_LEFT_FOLDER = "Вышел из папки — теперь файлы будут попадать прямо в архив."
MSG_FOLDER_GONE = "Эта папка больше недоступна (возможно, её удалили в Drive)."

# Drive folder name conventions: trim, collapse whitespace, reject control chars.
_NAME_BAD_RE = re.compile(r"[\x00-\x1f\x7f]")


def _clean_name(raw: str) -> str | None:
    name = re.sub(r"\s+", " ", raw.strip())
    if _NAME_BAD_RE.search(name):
        return None
    return name


@folders_router.callback_query(FolderCB.filter(F.action == "create"))
async def on_create(query: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Folder.awaiting_name)
    await query.answer()
    if isinstance(query.message, Message):
        await query.message.answer(MSG_ASK_NAME)


@folders_router.message(StateFilter(Folder.awaiting_name), F.text)
async def on_create_name_entered(
    message: Message,
    state: FSMContext,
    sheets: SheetsService,
    drive: DriveService,
) -> None:
    raw = message.text or ""
    name = _clean_name(raw)
    if name is None:
        await message.answer(MSG_NAME_BAD_CHARS)
        return
    if len(name) < 2:
        await message.answer(MSG_NAME_TOO_SHORT)
        return
    if len(name) > 80:
        await message.answer(MSG_NAME_TOO_LONG)
        return

    try:
        folder = await drive.create_folder(
            name=name,
            parent_id=settings.archive_folder_id,
        )
    except Exception:
        logger.exception("Drive create_folder failed for %r", name)
        await message.answer(MSG_CREATE_FAILED)
        await state.clear()
        return

    await sheets.add_folder(
        folder_id=folder.id,
        chat_id=message.chat.id,
        folder_name=folder.name,
        drive_url=folder.url,
    )
    await sheets.set_current_folder(
        chat_id=message.chat.id,
        folder_id=folder.id,
        folder_name=folder.name,
    )
    await state.clear()
    await message.answer(
        f"✅ Папка <b>{folder.name}</b> создана и активна.\n"
        f"<a href=\"{folder.url}\">Открыть в Drive</a>\n\n"
        "Теперь PDF-файлы будут попадать в неё.",
        reply_markup=main_menu_with_folder(folder.name),
        disable_web_page_preview=True,
    )


@folders_router.callback_query(FolderCB.filter(F.action == "list"))
async def on_list(query: CallbackQuery, sheets: SheetsService) -> None:
    if not isinstance(query.message, Message):
        await query.answer()
        return
    folders = await sheets.list_folders(chat_id=query.message.chat.id, limit=10)
    await query.answer()
    if not folders:
        if isinstance(query.message, Message):
            await query.message.answer(MSG_NO_FOLDERS)
        return
    if isinstance(query.message, Message):
        await query.message.answer(MSG_PICK_FOLDER, reply_markup=folder_picker(folders))


@folders_router.callback_query(FolderCB.filter(F.action == "pick"))
async def on_pick(
    query: CallbackQuery,
    callback_data: FolderCB,
    sheets: SheetsService,
    drive: DriveService,
) -> None:
    folder_id = callback_data.folder_id
    if not folder_id:
        await query.answer("Не удалось определить папку", show_alert=True)
        return
    if not isinstance(query.message, Message):
        await query.answer()
        return
    chat_id = query.message.chat.id

    # Verify the folder still exists in Drive (user may have deleted it).
    if not await drive.folder_exists(folder_id):
        await query.answer(MSG_FOLDER_GONE, show_alert=True)
        return

    folders = await sheets.list_folders(chat_id=chat_id, limit=50)
    picked = next((f for f in folders if f.folder_id == folder_id), None)
    if picked is None:
        await query.answer(MSG_FOLDER_GONE, show_alert=True)
        return

    await sheets.set_current_folder(
        chat_id=chat_id,
        folder_id=picked.folder_id,
        folder_name=picked.folder_name,
    )
    await sheets.touch_folder(picked.folder_id)
    await query.answer(f"Активная папка: {picked.folder_name}")
    if isinstance(query.message, Message):
        await query.message.answer(
            f"📂 Активная папка: <b>{picked.folder_name}</b>\n"
            f"<a href=\"{picked.drive_url}\">Открыть в Drive</a>",
            reply_markup=main_menu_with_folder(picked.folder_name),
            disable_web_page_preview=True,
        )


@folders_router.callback_query(FolderCB.filter(F.action == "leave"))
async def on_leave(query: CallbackQuery, sheets: SheetsService) -> None:
    if not isinstance(query.message, Message):
        await query.answer()
        return
    await sheets.set_current_folder(
        chat_id=query.message.chat.id,
        folder_id="",
        folder_name="",
    )
    await query.answer("Вышли из папки")
    await query.message.answer(
        MSG_LEFT_FOLDER,
        reply_markup=main_menu_no_folder(),
    )
