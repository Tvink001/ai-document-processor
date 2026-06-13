"""PDF metadata + model-tier routing.

Two pure responsibilities:
- count_pages: open a PDF on disk, return the page count via pypdf.
- decide_model_tier: map a page-count to one of the Claude tiers
  ("haiku" / "sonnet" / "opus") or None when the file is over the
  hard cap (project_specs.md §11.3).

Tiers are calibrated for the practical OUTPUT budget on dense bank
statements, not the input context window. Haiku 4.5 has the 200K context
to *read* a long statement, but on a dense multi-page Privat24 export it
runs out of output tokens before finishing the JSON — observed on a real
25-page statement: Haiku hit its 32K output cap with stop_reason=max_tokens
and truncated, while Sonnet completed the same extraction cleanly in ~20K
tokens. So heavy statements route straight to Sonnet instead of burning a
doomed Haiku pass first:
- haiku  for ≤15 pages  (cheapest path; ~$0.04-0.20 / statement)
- sonnet for 16-120     (dense/long statements, one clean pass; ~$0.50-1.50)
- opus   for 121-200    (frontier quality on dense scans; ~$5-15)
- None   for >200       (caller rejects with a split suggestion)
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Literal

from pypdf import PdfReader

ModelTier = Literal["haiku", "sonnet", "opus"]

HAIKU_MAX_PAGES = 15
SONNET_MAX_PAGES = 120
OPUS_MAX_PAGES = 200


def _unwrap_pdf_bytes(raw: bytes) -> bytes:
    """Return the inner PDF from a КЕП / PKCS#7-signed container.

    Privat24 and other Ukrainian banks deliver КЕП-signed statements as
    DER-encoded PKCS#7 SignedData wrapping the real PDF: the file starts
    with an ASN.1 header (0x30 0x83 ...), not "%PDF", so pypdf rejects it
    as an invalid header and the page count comes out wrong — which then
    mis-routes the model tier. Slice from the first "%PDF" to the last
    "%%EOF" to recover the embedded document. Plain PDFs pass through.
    """
    if raw[:4] == b"%PDF":
        return raw
    start = raw.find(b"%PDF")
    if start < 0:
        return raw  # not a wrapper we recognize; let pypdf raise downstream
    eof = raw.rfind(b"%%EOF")
    end = eof + 5 if eof > start else len(raw)
    return raw[start:end]


def count_pages(path: Path) -> int:
    """Return the number of pages in the PDF at `path`.

    КЕП / PKCS#7-signed statements are unwrapped to their inner PDF first —
    pypdf cannot parse the signed container directly. Raises whatever pypdf
    raises on a genuinely corrupted file — caller decides whether to retry,
    reject, or surface to the user.
    """
    reader = PdfReader(io.BytesIO(_unwrap_pdf_bytes(path.read_bytes())))
    return len(reader.pages)


def decide_model_tier(total_page_count: int) -> ModelTier | None:
    """Pick a Claude tier for a batch whose PDFs sum to `total_page_count` pages.

    Anthropic receives ALL PDFs in a single Messages API request, so the
    SUM of pages drives the context budget — not the max. A 6×30-page
    session is 180 pages of context, well beyond Haiku's 200K window
    even though no individual file is large.
    """
    if total_page_count <= 0:
        return "haiku"
    if total_page_count <= HAIKU_MAX_PAGES:
        return "haiku"
    if total_page_count <= SONNET_MAX_PAGES:
        return "sonnet"
    if total_page_count <= OPUS_MAX_PAGES:
        return "opus"
    return None
