"""Inline keyboard builders for the main menu + folder pickers.

Telegram caps `callback_data` at 64 bytes, so we keep payloads short.
Folder picker passes `folder_id` (the Drive id, ~33 chars) inside
FolderCB; that fits.
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.callbacks import FolderCB, NavCB
from bot.services.sheets import FolderRecord


def main_menu_no_folder() -> InlineKeyboardMarkup:
    """Three buttons shown when the user is in Drive root."""
    kb = InlineKeyboardBuilder()
    kb.button(
        text="📄 Отправить документ",
        callback_data=NavCB(action="send_info").pack(),
    )
    kb.button(
        text="📁 Создать папку",
        callback_data=FolderCB(action="create").pack(),
    )
    kb.button(
        text="📂 Открыть существующую",
        callback_data=FolderCB(action="list").pack(),
    )
    kb.adjust(1)
    return kb.as_markup()


def main_menu_with_folder(folder_name: str) -> InlineKeyboardMarkup:
    """Four buttons shown when the user is currently inside a folder."""
    kb = InlineKeyboardBuilder()
    kb.button(
        text=f"📄 Отправить в «{folder_name}»",
        callback_data=NavCB(action="send_info").pack(),
    )
    kb.button(
        text="📁 Создать новую папку",
        callback_data=FolderCB(action="create").pack(),
    )
    kb.button(
        text="📂 Сменить папку",
        callback_data=FolderCB(action="list").pack(),
    )
    kb.button(
        text="🚪 Выйти в корень",
        callback_data=FolderCB(action="leave").pack(),
    )
    kb.adjust(1)
    return kb.as_markup()


def folder_picker(folders: list[FolderRecord]) -> InlineKeyboardMarkup:
    """One button per recent folder, plus a 'cancel' row."""
    kb = InlineKeyboardBuilder()
    for f in folders:
        kb.button(
            text=f"📂 {f.folder_name}",
            callback_data=FolderCB(action="pick", folder_id=f.folder_id).pack(),
        )
    kb.button(
        text="✖ Отмена",
        callback_data=NavCB(action="cancel").pack(),
    )
    kb.adjust(1)
    return kb.as_markup()
