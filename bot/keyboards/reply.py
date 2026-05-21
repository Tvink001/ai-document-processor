"""Persistent reply keyboards (sticky bottom buttons in the chat).

Telegram inline keyboards disappear when the user scrolls past them;
reply keyboards stay at the bottom of the input area until cleared.
Taps fire the button's text as a regular message — handlers route on
F.text equality.

Two layouts:
- main_menu_no_folder: 3 sticky buttons when the user is in Drive root.
- main_menu_with_folder: 4 sticky buttons when a folder is selected.
"""

from __future__ import annotations

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

# Button labels — handlers match on these exact strings via F.text.
BTN_SEND = "📄 Отправить документ"
BTN_CREATE = "📁 Создать папку"
BTN_OPEN = "📂 Открыть папку"
BTN_LEAVE = "🚪 Выйти в корень"


def main_reply_no_folder() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_SEND)],
            [KeyboardButton(text=BTN_CREATE), KeyboardButton(text=BTN_OPEN)],
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Перетащи PDF или выбери действие…",
    )


def main_reply_with_folder(folder_name: str) -> ReplyKeyboardMarkup:
    """Minimalist in-folder keyboard — drop PDFs is implicit; only exit
    needs a button. (Switch folder = leave first, then open from root.)"""
    short = folder_name if len(folder_name) <= 20 else folder_name[:17] + "…"
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_LEAVE)],
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder=f"📂 {short} — перетащи PDF…",
    )
