"""Google Drive v3 wrapper — folder create/check only.

The bot does NOT upload PDFs from Python; n8n's Drive node still does
that (it already has the Telegram-file-binary in hand inside WF03b).
Python's Drive responsibilities are limited to per-user folder
management:

- create_folder: make a new subfolder under the archive root and
  return its id + webViewLink.
- folder_exists: cheap existence check before sending a session to
  n8n with a stale target_folder_id (e.g. the user deleted the folder
  in the Drive UI since their last bot interaction).

All blocking googleapiclient calls are wrapped via `asyncio.to_thread`
so they don't stall the aiogram event loop.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)

FOLDER_MIME = "application/vnd.google-apps.folder"
DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive"]


@dataclass(frozen=True)
class DriveFolder:
    id: str
    name: str
    url: str


class DriveService:
    """Thin async wrapper over Drive v3. One instance per process."""

    def __init__(self, service_account_path: Path) -> None:
        creds = service_account.Credentials.from_service_account_file(
            str(service_account_path),
            scopes=DRIVE_SCOPES,
        )
        # cache_discovery=False — silences the file-cache warning under
        # oauth2client deprecation; we have no use for the discovery cache.
        self._service = build(
            "drive",
            "v3",
            credentials=creds,
            cache_discovery=False,
        )

    async def create_folder(self, name: str, parent_id: str) -> DriveFolder:
        """Create a folder named `name` under `parent_id`. Returns the new folder."""
        body = {
            "name": name,
            "mimeType": FOLDER_MIME,
            "parents": [parent_id],
        }

        def _do() -> dict[str, str]:
            return (
                self._service.files()
                .create(
                    body=body,
                    fields="id, name, webViewLink",
                    supportsAllDrives=True,
                )
                .execute()
            )

        result = await asyncio.to_thread(_do)
        folder_id = result["id"]
        return DriveFolder(
            id=folder_id,
            name=result.get("name", name),
            url=result.get(
                "webViewLink",
                f"https://drive.google.com/drive/folders/{folder_id}",
            ),
        )

    async def folder_exists(self, folder_id: str) -> bool:
        """True if `folder_id` resolves to a non-trashed folder. False on 404."""
        if not folder_id:
            return False

        def _do() -> dict[str, str]:
            return (
                self._service.files()
                .get(
                    fileId=folder_id,
                    fields="id, mimeType, trashed",
                    supportsAllDrives=True,
                )
                .execute()
            )

        try:
            result = await asyncio.to_thread(_do)
        except HttpError as e:
            if e.resp.status == 404:
                return False
            logger.warning("drive.folder_exists(%s) failed: %s", folder_id, e)
            return False
        return result.get("mimeType") == FOLDER_MIME and not result.get("trashed", False)
