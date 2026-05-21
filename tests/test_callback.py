"""Smoke tests for the FastAPI callback endpoint.

Uses a stubbed Bot so we never touch Telegram — verifies token-gating
and the response body shape produced by the handler."""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "stub")
os.environ.setdefault("OWNER_TELEGRAM_CHAT_ID", "1")
os.environ.setdefault("N8N_WEBHOOK_URL", "https://example.com/webhook/x")
os.environ.setdefault("N8N_WEBHOOK_SECRET", "stub")
os.environ.setdefault("CALLBACK_TOKEN", "test-callback-token")
os.environ.setdefault("GOOGLE_SHEET_ID", "stub")
os.environ.setdefault("ARCHIVE_FOLDER_ID", "stub")

from bot.callbacks_app.n8n_result import build_app  # noqa: E402  isort: skip


@pytest.fixture
def stub_bot() -> Any:
    bot = AsyncMock()
    bot.send_message = AsyncMock(return_value=None)
    return bot


def test_callback_rejects_missing_token(stub_bot: Any) -> None:
    app = build_app(stub_bot)
    client = TestClient(app)
    resp = client.post(
        "/n8n-callback",
        json={"chat_id": 1, "session_id": "x"},
    )
    assert resp.status_code == 401
    stub_bot.send_message.assert_not_awaited()


def test_callback_rejects_bad_token(stub_bot: Any) -> None:
    app = build_app(stub_bot)
    client = TestClient(app)
    resp = client.post(
        "/n8n-callback",
        json={"chat_id": 1, "session_id": "x"},
        headers={"X-Callback-Token": "wrong"},
    )
    assert resp.status_code == 401
    stub_bot.send_message.assert_not_awaited()


def test_callback_accepts_valid_token(stub_bot: Any) -> None:
    app = build_app(stub_bot)
    client = TestClient(app)
    resp = client.post(
        "/n8n-callback",
        json={
            "chat_id": 12345,
            "session_id": "abc",
            "xlsx_url": "https://drive.google.com/...",
            "summary": "Готово: 23 транзакции",
        },
        headers={"X-Callback-Token": "test-callback-token"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    stub_bot.send_message.assert_awaited_once()
    args, kwargs = stub_bot.send_message.await_args
    assert kwargs["chat_id"] == 12345
    assert "Готово: 23 транзакции" in kwargs["text"]
    assert "drive.google.com" in kwargs["text"]


def test_callback_health() -> None:
    app = build_app(AsyncMock())
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
