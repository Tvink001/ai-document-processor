"""Unit tests for the pure-function routing logic in bot.services.pdf.

`count_pages` is exercised by a synthesized one-page PDF fixture written
out at test-run time (no committed binary needed)."""

from __future__ import annotations

from pathlib import Path

import pytest

from bot.services.pdf import (
    HAIKU_MAX_PAGES,
    OPUS_MAX_PAGES,
    SONNET_MAX_PAGES,
    count_pages,
    decide_model_tier,
)


@pytest.mark.parametrize(
    ("pages", "expected"),
    [
        (0, "haiku"),
        (1, "haiku"),
        (HAIKU_MAX_PAGES, "haiku"),
        (HAIKU_MAX_PAGES + 1, "sonnet"),
        (90, "sonnet"),
        (SONNET_MAX_PAGES, "sonnet"),
        (SONNET_MAX_PAGES + 1, "opus"),
        (180, "opus"),
        (OPUS_MAX_PAGES, "opus"),
        (OPUS_MAX_PAGES + 1, None),
        (500, None),
    ],
)
def test_decide_model_tier_boundaries(pages: int, expected: str | None) -> None:
    assert decide_model_tier(pages) == expected


def test_count_pages_one_page_pdf(tmp_path: Path) -> None:
    """Tiniest legal PDF — one page, no content. Constructed inline so
    no binary is committed to the repo."""
    pdf_path = tmp_path / "one_page.pdf"
    # Minimal viable PDF 1.4 file (Adobe spec, hand-rolled).
    pdf_bytes = (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj\n"
        b"xref\n0 4\n"
        b"0000000000 65535 f \n"
        b"0000000009 00000 n \n"
        b"0000000053 00000 n \n"
        b"0000000098 00000 n \n"
        b"trailer<</Size 4/Root 1 0 R>>\n"
        b"startxref\n149\n%%EOF\n"
    )
    pdf_path.write_bytes(pdf_bytes)
    assert count_pages(pdf_path) == 1
