"""gspread wrapper for the two state tabs the Python front-end owns.

`users` is one row per Telegram chat_id with the current folder selection.
`folders` is the audit log of every folder ever created, scoped by chat_id,
sorted by last_used_at for the "open existing" picker.

All public methods are async; sync gspread calls are wrapped via
`asyncio.to_thread`. Worksheets are opened once in the constructor —
~200-500 ms cold cost on first request after a long idle.

Statements / transactions / sessions / _errors tabs are owned by n8n and
NOT touched here. The Python service only writes the two user-facing
state tabs.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import gspread
from gspread.exceptions import WorksheetNotFound
from gspread.utils import ValueInputOption

logger = logging.getLogger(__name__)


def _iso_now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


@dataclass(frozen=True)
class UserState:
    chat_id: int
    username: str
    first_name: str
    current_folder_id: str
    current_folder_name: str
    created_at: str
    last_active_at: str


@dataclass(frozen=True)
class FolderRecord:
    folder_id: str
    chat_id: int
    folder_name: str
    drive_url: str
    created_at: str
    last_used_at: str


class SheetsService:
    """Async wrapper over gspread for the `users` + `folders` tabs."""

    USERS_TAB = "users"
    FOLDERS_TAB = "folders"

    def __init__(self, service_account_path: Path, sheet_id: str) -> None:
        gc = gspread.service_account(filename=str(service_account_path))
        self._sh = gc.open_by_key(sheet_id)
        try:
            self._users = self._sh.worksheet(self.USERS_TAB)
            self._folders = self._sh.worksheet(self.FOLDERS_TAB)
        except WorksheetNotFound as e:
            raise RuntimeError(
                f"Missing Sheets tab {e}. Run `python -m bot.scripts.bootstrap_sheets` "
                "to create the users + folders tabs.",
            ) from e

    # ---------- users ----------

    async def get_user(self, chat_id: int) -> UserState | None:
        rows = await asyncio.to_thread(self._users.get_all_records, head=1)
        for r in rows:
            if str(r.get("chat_id")) == str(chat_id):
                return UserState(
                    chat_id=int(r["chat_id"]),
                    username=str(r.get("username") or ""),
                    first_name=str(r.get("first_name") or ""),
                    current_folder_id=str(r.get("current_folder_id") or ""),
                    current_folder_name=str(r.get("current_folder_name") or ""),
                    created_at=str(r.get("created_at") or ""),
                    last_active_at=str(r.get("last_active_at") or ""),
                )
        return None

    async def upsert_user(
        self,
        chat_id: int,
        username: str,
        first_name: str,
    ) -> UserState:
        """Insert the user if new; otherwise refresh username/first_name + last_active_at."""
        existing = await self.get_user(chat_id)
        now = _iso_now()
        if existing is None:
            row = [chat_id, username, first_name, "", "", now, now]
            await asyncio.to_thread(
                self._users.append_row,
                row,
                value_input_option=ValueInputOption.user_entered,
            )
            return UserState(
                chat_id=chat_id,
                username=username,
                first_name=first_name,
                current_folder_id="",
                current_folder_name="",
                created_at=now,
                last_active_at=now,
            )
        await self._update_user_fields(
            chat_id,
            username=username,
            first_name=first_name,
            last_active_at=now,
        )
        return UserState(
            chat_id=chat_id,
            username=username,
            first_name=first_name,
            current_folder_id=existing.current_folder_id,
            current_folder_name=existing.current_folder_name,
            created_at=existing.created_at,
            last_active_at=now,
        )

    async def set_current_folder(
        self,
        chat_id: int,
        folder_id: str,
        folder_name: str,
    ) -> None:
        await self._update_user_fields(
            chat_id,
            current_folder_id=folder_id,
            current_folder_name=folder_name,
            last_active_at=_iso_now(),
        )

    async def _update_user_fields(self, chat_id: int, **fields: Any) -> None:
        row_idx = await self._find_user_row(chat_id)
        if row_idx is None:
            logger.warning("update_user_fields: chat_id %s not found", chat_id)
            return
        header = await asyncio.to_thread(self._users.row_values, 1)
        idx_map = {name: i + 1 for i, name in enumerate(header)}
        updates: list[dict[str, Any]] = []
        for key, val in fields.items():
            if key not in idx_map:
                logger.warning("update_user_fields: unknown column %s", key)
                continue
            updates.append(
                {
                    "range": gspread.utils.rowcol_to_a1(row_idx, idx_map[key]),
                    "values": [[val]],
                },
            )
        if updates:
            await asyncio.to_thread(self._users.batch_update, updates)

    async def _find_user_row(self, chat_id: int) -> int | None:
        values = await asyncio.to_thread(self._users.get_all_values)
        if not values:
            return None
        header = values[0]
        if "chat_id" not in header:
            return None
        col_idx = header.index("chat_id")
        for i, row in enumerate(values[1:], start=2):
            if col_idx < len(row) and str(row[col_idx]) == str(chat_id):
                return i
        return None

    # ---------- folders ----------

    async def add_folder(
        self,
        folder_id: str,
        chat_id: int,
        folder_name: str,
        drive_url: str,
    ) -> FolderRecord:
        now = _iso_now()
        row = [folder_id, chat_id, folder_name, drive_url, now, now]
        await asyncio.to_thread(
            self._folders.append_row,
            row,
            value_input_option=ValueInputOption.user_entered,
        )
        return FolderRecord(
            folder_id=folder_id,
            chat_id=chat_id,
            folder_name=folder_name,
            drive_url=drive_url,
            created_at=now,
            last_used_at=now,
        )

    async def list_folders(self, chat_id: int, limit: int = 10) -> list[FolderRecord]:
        """Return the user's last `limit` folders, most-recently-used first."""
        rows = await asyncio.to_thread(self._folders.get_all_records, head=1)
        out: list[FolderRecord] = []
        for r in rows:
            if str(r.get("chat_id")) != str(chat_id):
                continue
            try:
                out.append(
                    FolderRecord(
                        folder_id=str(r["folder_id"]),
                        chat_id=int(r["chat_id"]),
                        folder_name=str(r.get("folder_name") or ""),
                        drive_url=str(r.get("drive_url") or ""),
                        created_at=str(r.get("created_at") or ""),
                        last_used_at=str(r.get("last_used_at") or ""),
                    ),
                )
            except (KeyError, ValueError, TypeError) as e:
                logger.warning("Skipping malformed folders row: %s", e)
        out.sort(key=lambda f: f.last_used_at, reverse=True)
        return out[:limit]

    async def touch_folder(self, folder_id: str) -> None:
        """Bump last_used_at on the given folder_id row."""
        row_idx = await self._find_folder_row(folder_id)
        if row_idx is None:
            return
        header = await asyncio.to_thread(self._folders.row_values, 1)
        if "last_used_at" not in header:
            return
        col_idx = header.index("last_used_at") + 1
        cell_a1 = gspread.utils.rowcol_to_a1(row_idx, col_idx)
        await asyncio.to_thread(
            self._folders.update,
            [[_iso_now()]],
            cell_a1,
            value_input_option=ValueInputOption.user_entered,
        )

    async def _find_folder_row(self, folder_id: str) -> int | None:
        values = await asyncio.to_thread(self._folders.get_all_values)
        if not values:
            return None
        header = values[0]
        if "folder_id" not in header:
            return None
        col_idx = header.index("folder_id")
        for i, row in enumerate(values[1:], start=2):
            if col_idx < len(row) and row[col_idx] == folder_id:
                return i
        return None
