"""CallbackData factories — enforces typed schema on inline button payloads.

64-byte Telegram limit on `callback_data` means we keep keys short and rely
on aiogram's CallbackData pack/unpack. Populated by M12.
"""

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData


class FolderCB(CallbackData, prefix="f"):
    action: str  # "create" | "list" | "leave" | "pick"
    folder_id: str = ""  # only for action="pick"


class NavCB(CallbackData, prefix="n"):
    action: str  # "send_info" | "cancel"
