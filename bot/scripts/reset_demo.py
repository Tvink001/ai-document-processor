"""One-shot demo reset: clear the n8n-owned state tabs so a re-sent file
processes fresh. The MD5 dedup lives in `statements` (matched by `statement_id`
within this chat's `session_id` prefix); clearing it lets the same PDF be
re-uploaded and fully reprocessed on camera. Header rows stay; the reference
tabs (`categories`, `template`) and the Python-owned tabs (`users`, `folders`)
are left untouched.

Run before a recording take:
    python -m bot.scripts.reset_demo
"""

from __future__ import annotations

import gspread

from bot.config import settings

TABS_TO_CLEAR = ["statements", "transactions", "sessions", "_report", "_errors"]


def main() -> None:
    gc = gspread.service_account(filename=str(settings.google_service_account_path))
    sh = gc.open_by_key(settings.google_sheet_id)
    for name in TABS_TO_CLEAR:
        try:
            ws = sh.worksheet(name)
        except gspread.exceptions.WorksheetNotFound:
            print(f"skip (not found): {name}")
            continue
        last_cell = gspread.utils.rowcol_to_a1(ws.row_count, ws.col_count)
        ws.batch_clear([f"A2:{last_cell}"])
        print(f"cleared: {name}")
    print("demo state reset")


if __name__ == "__main__":
    main()
