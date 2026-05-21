"""HTTP client for the n8n WF01 webhook.

POSTs a typed payload describing one session's intake — the n8n pipeline
takes it from there (WF02b extract → WF03b persist → WF04b xlsx → POST
callback). Submission is fire-and-forget: a 2xx response means n8n
accepted the work; the actual result arrives later via the callback URL.

The 30 s submission timeout is conservative — the n8n Webhook node
responds within seconds; longer waits indicate an upstream issue worth
surfacing.
"""

from __future__ import annotations

import logging
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

ModelTier = Literal["haiku", "sonnet", "opus"]


class FileRef(BaseModel):
    """One Telegram file to be processed by n8n."""

    file_id: str
    file_name: str
    file_size: int
    mime_type: str
    page_count: int = Field(ge=0)


class SubmitFilesRequest(BaseModel):
    """JSON body POSTed to the WF01 webhook."""

    model_config = ConfigDict(protected_namespaces=())

    chat_id: int
    session_id: str
    files: list[FileRef]
    target_folder_id: str = ""  # "" = drop in root archive
    target_folder_name: str = ""
    model_tier: ModelTier
    callback_url: str
    # Optional Telegram metadata — flows into the `sessions` Sheet tab.
    user_id: int = 0  # falls back to chat_id when 0
    username: str = ""
    first_name: str = ""


class N8nClient:
    def __init__(self, webhook_url: str, secret: str, timeout: float = 30.0) -> None:
        self._url = webhook_url
        self._headers = {"X-Webhook-Secret": secret}
        self._timeout = timeout

    async def submit_files(self, payload: SubmitFilesRequest) -> dict[str, object]:
        """POST the payload; return the parsed JSON response (or {} on 204)."""
        body = payload.model_dump(mode="json")
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(self._url, json=body, headers=self._headers)
            resp.raise_for_status()
            if resp.status_code == 204 or not resp.content:
                return {}
            try:
                data = resp.json()
            except ValueError:
                logger.warning("n8n webhook returned non-JSON body: %r", resp.text[:200])
                return {}
            return dict(data) if isinstance(data, dict) else {"raw": data}
