"""One-off bootstrap for the two new Sheets tabs the Python bot needs.

Creates `users` and `folders` tabs idempotently — if either already exists,
the script leaves it alone. Headers are written only when the tab is freshly
created so re-running can't clobber operator edits.

Usage (from repo root):

    cd D:\\Users\\Admin\\AppData\\Local\\Programs\\CommercialBuilds\\P3_bot
    python -m bot.scripts.bootstrap_sheets

Requires gspread installed (`pip install gspread==6.2.1`) and a service-account
JSON file readable at the path in GOOGLE_SERVICE_ACCOUNT_PATH (default
`./bot/secrets/credentials.json`). The service account must be granted Editor
access to the target spreadsheet.

Reads two env vars; both have sensible defaults:
    GOOGLE_SERVICE_ACCOUNT_PATH   default: ./bot/secrets/credentials.json
    GOOGLE_SHEET_ID               default: production P3_bot sheet
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import gspread
from gspread.exceptions import WorksheetNotFound
from gspread.utils import ValueInputOption

DEFAULT_SHEET_ID = "1tl3rvKeaMrreDfjQMQQPlZF6hGYbG-h0Ft4BroPRw_w"
DEFAULT_CREDS_PATH = Path("./bot/secrets/credentials.json")

USERS_HEADERS = [
    "chat_id",
    "username",
    "first_name",
    "current_folder_id",
    "current_folder_name",
    "created_at",
    "last_active_at",
]

FOLDERS_HEADERS = [
    "folder_id",
    "chat_id",
    "folder_name",
    "drive_url",
    "created_at",
    "last_used_at",
]


def _ensure_tab(
    sh: gspread.Spreadsheet,
    title: str,
    headers: list[str],
) -> str:
    """Create the tab + write headers if missing. Returns a status string."""
    try:
        sh.worksheet(title)
        return f"  [skip] '{title}' already exists"
    except WorksheetNotFound:
        ws = sh.add_worksheet(title=title, rows=200, cols=max(10, len(headers)))
        ws.append_row(headers, value_input_option=ValueInputOption.user_entered)
        return f"  [done] '{title}' created with {len(headers)} headers"


def main() -> int:
    creds_path = Path(os.environ.get("GOOGLE_SERVICE_ACCOUNT_PATH", DEFAULT_CREDS_PATH))
    sheet_id = os.environ.get("GOOGLE_SHEET_ID", DEFAULT_SHEET_ID)

    if not creds_path.exists():
        print(f"ERROR: service account file not found at {creds_path}", file=sys.stderr)
        print(
            "Set GOOGLE_SERVICE_ACCOUNT_PATH or drop the JSON at "
            f"{DEFAULT_CREDS_PATH}",
            file=sys.stderr,
        )
        return 2

    print(f"Connecting to Sheet {sheet_id} via {creds_path}...")
    gc = gspread.service_account(filename=str(creds_path))
    sh = gc.open_by_key(sheet_id)

    print("Existing tabs:", ", ".join(w.title for w in sh.worksheets()))
    print(_ensure_tab(sh, "users", USERS_HEADERS))
    print(_ensure_tab(sh, "folders", FOLDERS_HEADERS))
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
