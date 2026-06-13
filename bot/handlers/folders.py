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
from bot.keyboards.inline import folder_picker
from bot.keyboards.reply import main_reply_no_folder, main_reply_with_folder
from bot.services.drive import DriveService
from bot.services.sheets import SheetsService
from bot.states import Folder

logger = logging.getLogger(__name__)
folders_router = Router()

MSG_ASK_NAME = (
    "What should we name the folder? Send a short name (e.g. Candidate 1, "
    "John Smith, Acme LLC)."
)
MSG_NAME_TOO_SHORT = "Name too short. At least 2 characters."
MSG_NAME_TOO_LONG = "Name too long. 80 characters max."
MSG_NAME_BAD_CHARS = (
    "The name has only spaces or non-printable characters. Please try again."
)
MSG_CREATE_FAILED = "Couldn't create the folder. Please try again in a moment."
MSG_NO_FOLDERS = "You don't have any folders yet. Create your first with the button above."
MSG_PICK_FOLDER = "Pick a folder to work in:"
MSG_LEFT_FOLDER = "Left the folder — files will now go straight to the archive."
MSG_FOLDER_GONE = "This folder is no longer available (it may have been deleted in Drive)."

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
        f"✅ Folder <b>{folder.name}</b> created and active.\n"
        f"<a href=\"{folder.url}\">Открыть в Drive</a>\n\n"
        "PDFs will now go into it.",
        reply_markup=main_reply_with_folder(folder.name),
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
        await query.answer("Couldn't identify the folder", show_alert=True)
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
    await query.answer(f"Active folder: {picked.folder_name}")
    if isinstance(query.message, Message):
        await query.message.answer(
            f"📂 Active folder: <b>{picked.folder_name}</b>\n"
            f"<a href=\"{picked.drive_url}\">Open in Drive</a>",
            reply_markup=main_reply_with_folder(picked.folder_name),
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
    await query.answer("Left the folder")
    await query.message.answer(
        MSG_LEFT_FOLDER,
        reply_markup=main_reply_no_folder(),
    )
