"""PDF metadata + model-tier routing.

Two pure responsibilities:
- count_pages: open a PDF on disk, return the page count via pypdf.
- decide_model_tier: map a page-count to one of the Claude tiers
  ("haiku" / "sonnet" / "opus") or None when the file is over the
  hard cap (project_specs.md §11.3).

Tiers are calibrated for Claude 4.x context windows (Haiku 200K,
Sonnet/Opus 1M) and rough cost vs. quality trade-offs:
- haiku  for ≤50 pages  (cheapest path; ~$0.04-0.20 / statement)
- sonnet for 51-120     (1M context unlocks long statements; ~$0.50-1.50)
- opus   for 121-200    (frontier quality on dense scans; ~$5-15)
- None   for >200       (caller rejects with a split suggestion)
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pypdf import PdfReader

ModelTier = Literal["haiku", "sonnet", "opus"]

HAIKU_MAX_PAGES = 50
SONNET_MAX_PAGES = 120
OPUS_MAX_PAGES = 200


def count_pages(path: Path) -> int:
    """Return the number of pages in the PDF at `path`.

    Raises whatever pypdf raises on a corrupted file — caller decides
    whether to retry, reject, or surface to the user.
    """
    with open(path, "rb") as fh:
        reader = PdfReader(fh)
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
