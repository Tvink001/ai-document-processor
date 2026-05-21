"""Entry point — placeholder; wired in M13.

Two modes gated by `settings.mode`:
- polling: local dev. aiogram long-polling + FastAPI uvicorn server, joined
  via asyncio.gather so the n8n callback endpoint is reachable while the bot
  is reading updates.
- webhook: prod. aiogram's SimpleRequestHandler is mounted into the same
  FastAPI app — single uvicorn process handles both Telegram and n8n.
"""

from __future__ import annotations

import logging
import sys

logger = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(
        level="INFO",
        stream=sys.stdout,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logger.warning(
        "bot.main is a scaffold — wired by M13. Run after M10..M13 ship.",
    )


if __name__ == "__main__":
    main()
