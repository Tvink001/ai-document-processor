"""Smoke tests for the n8n client payload shape — no live HTTP."""

from __future__ import annotations

import pytest

from bot.services.n8n import FileRef, SubmitFilesRequest


def test_submit_files_request_round_trip() -> None:
    req = SubmitFilesRequest(
        chat_id=1410989113,
        session_id="1410989113_1733000000000",
        files=[
            FileRef(
                file_id="ABCxyz",
                file_name="privat24.pdf",
                file_size=120_000,
                mime_type="application/pdf",
                page_count=12,
            ),
        ],
        target_folder_id="1OvuG8ZTHlvF375Oj0GscdtH0nH8iadRU",
        target_folder_name="Candidate 1",
        model_tier="haiku",
        callback_url="https://example.ngrok-free.app/n8n-callback",
    )
    body = req.model_dump(mode="json")
    assert body["model_tier"] == "haiku"
    assert body["files"][0]["page_count"] == 12
    assert body["target_folder_id"]
    assert body["callback_url"].startswith("https://")
    assert body["user_id"] == 0  # default; overridden by handler in real flow
    assert body["username"] == ""


def test_submit_files_rejects_bad_tier() -> None:
    with pytest.raises(ValueError):
        SubmitFilesRequest(
            chat_id=1,
            session_id="x",
            files=[],
            model_tier="foobar",  # type: ignore[arg-type]
            callback_url="https://x",
        )
