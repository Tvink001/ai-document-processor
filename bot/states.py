"""aiogram FSM states for the P3 front-end. Populated by M12."""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class Folder(StatesGroup):
    awaiting_name = State()
