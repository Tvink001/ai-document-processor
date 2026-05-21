"""PDF intake — debounce media_group, count pages, decide tier, POST to n8n.

The bot owns the Telegram surface end-to-end, so what arrives here is
the canonical event: a Telegram update with a PDF document attachment.

Pipeline per session:
1. Buffer media-group siblings for ~5 s (Telegram delivers album items
   as separate updates).
2. Download each PDF to a temp file (we need bytes for pypdf; Telegram
   keeps the file for 1 h after upload but our flow uses it inside that
   window).
3. Count pages of every PDF; pick model_tier from the largest count.
4. POST file_ids + metadata + chat state to the WF01 webhook. n8n
   re-downloads the binaries via its own Telegram credential and runs
   the extraction pipeline.
5. Reply optimistically to the user — the real result arrives later
   via the /n8n-callback FastAPI endpoint (M13).
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from tempfile import NamedTemporaryFile

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.config import settings
from bot.services.n8n import FileRef, N8nClient, SubmitFilesRequest
from bot.services.pdf import OPUS_MAX_PAGES, count_pages, decide_model_tier
from bot.services.sheets import SheetsService

logger = logging.getLogger(__name__)
documents_router = Router()

# Telegram album debounce: typical album items arrive within ~1 s of each
# other; 2.5 s catches stragglers without making single-file uploads feel
# slow. (We hit this path only when media_group_id is set — single-file
# uploads bypass the debounce entirely.)
ALBUM_DEBOUNCE_S = 2.5
MAX_FILES_PER_SESSION = 6
HARD_REJECT_PAGES = OPUS_MAX_PAGES

# Per-process album buffer. `media_group_id` is unique per Telegram album.
_pending: dict[str, list[Message]] = {}
_pending_lock = asyncio.Lock()

MSG_NOT_PDF = (
    "Я обрабатываю только PDF. Если у тебя другой формат — экспортируй "
    "выписку в PDF из приложения банка."
)
MSG_TOO_MANY = (
    "Слишком много файлов за раз (максимум {max}). Раздели на несколько "
    "сообщений, пожалуйста."
)
MSG_TOO_LARGE = (
    "Этот файл слишком большой ({pages} стр). Hard cap — {max} стр.\n"
    "Разбей PDF пополам и пришли двумя сообщениями, пожалуйста."
)
MSG_QUEUED_TEMPLATE = (
    "🔄 Принято {count} файл(ов), {pages} стр. суммарно.\n"
    "Маршрутизирую через {tier} — пришлю Excel, как только готов."
)


async def _send_pdf_to_processor(
    messages: list[Message],
    bot: Bot,
    sheets: SheetsService,
    n8n: N8nClient,
) -> None:
    """Process a finalized album (or a single document)."""
    if not messages:
        return
    first = messages[0]
    chat_id = first.chat.id
    if first.from_user is None:
        return

    pdf_docs = [m for m in messages if m.document and m.document.mime_type == "application/pdf"]
    if not pdf_docs:
        await first.answer(MSG_NOT_PDF)
        return
    if len(pdf_docs) > MAX_FILES_PER_SESSION:
        await first.answer(MSG_TOO_MANY.format(max=MAX_FILES_PER_SESSION))
        return

    # Download + count pages.
    tmp_paths: list[Path] = []
    files_meta: list[FileRef] = []
    try:
        for m in pdf_docs:
            doc = m.document
            assert doc is not None  # filtered above
            with NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp_path = Path(tmp.name)
            tmp_paths.append(tmp_path)
            await bot.download(doc.file_id, destination=tmp_path)
            pages = count_pages(tmp_path)
            files_meta.append(
                FileRef(
                    file_id=doc.file_id,
                    file_name=doc.file_name or "statement.pdf",
                    file_size=doc.file_size or 0,
                    mime_type=doc.mime_type or "application/pdf",
                    page_count=pages,
                ),
            )

        total_pages = sum(f.page_count for f in files_meta)
        if total_pages > HARD_REJECT_PAGES:
            await first.answer(
                MSG_TOO_LARGE.format(pages=total_pages, max=HARD_REJECT_PAGES),
            )
            return

        tier = decide_model_tier(total_pages)
        if tier is None:  # defense-in-depth; the >HARD branch should catch this first
            await first.answer(
                MSG_TOO_LARGE.format(pages=total_pages, max=HARD_REJECT_PAGES),
            )
            return

        user = await sheets.upsert_user(
            chat_id=chat_id,
            username=first.from_user.username or "",
            first_name=first.from_user.first_name or "",
        )

        session_id = f"{chat_id}_{int(time.time() * 1000)}"
        callback_url = (
            settings.callback_base_url.rstrip("/") + "/n8n-callback"
        )
        payload = SubmitFilesRequest(
            chat_id=chat_id,
            session_id=session_id,
            files=files_meta,
            target_folder_id=user.current_folder_id,
            target_folder_name=user.current_folder_name,
            model_tier=tier,
            callback_url=callback_url,
            user_id=first.from_user.id,
            username=first.from_user.username or "",
            first_name=first.from_user.first_name or "",
        )

        await n8n.submit_files(payload)

        if user.current_folder_id:
            await sheets.touch_folder(user.current_folder_id)

        total_pages = sum(f.page_count for f in files_meta)
        await first.answer(
            MSG_QUEUED_TEMPLATE.format(
                count=len(files_meta),
                pages=total_pages,
                tier=tier,
            ),
        )
    except Exception:
        logger.exception("documents._send_pdf_to_processor crashed")
        await first.answer("Что-то пошло не так на стороне n8n. Попробуй ещё раз.")
    finally:
        for p in tmp_paths:
            try:
                p.unlink(missing_ok=True)
            except OSError:
                logger.debug("Could not delete temp file %s", p, exc_info=True)


async def _flush_album_after_delay(
    group_id: str,
    bot: Bot,
    sheets: SheetsService,
    n8n: N8nClient,
) -> None:
    await asyncio.sleep(ALBUM_DEBOUNCE_S)
    async with _pending_lock:
        messages = _pending.pop(group_id, [])
    await _send_pdf_to_processor(messages, bot, sheets, n8n)


@documents_router.message(F.document)
async def on_document(
    message: Message,
    state: FSMContext,
    bot: Bot,
    sheets: SheetsService,
    n8n: N8nClient,
) -> None:
    # If the user is in the middle of an FSM (e.g. naming a folder),
    # the dedicated FSM handler should win — defensive guard.
    if await state.get_state() is not None:
        return

    group_id = message.media_group_id
    if group_id is None:
        await _send_pdf_to_processor([message], bot, sheets, n8n)
        return

    async with _pending_lock:
        first_in_group = group_id not in _pending
        _pending.setdefault(group_id, []).append(message)
    if first_in_group:
        asyncio.create_task(
            _flush_album_after_delay(group_id, bot, sheets, n8n),
        )
