from __future__ import annotations

import re
from collections import defaultdict

from app.models.document import Block, BlockRole

_DIGITS_RE = re.compile(r"\d+")
_PAGE_NUMBER_RE = re.compile(r"^[\-–—\s]*\d{1,4}[\-–—\s]*$")
_TOP_BAND = 0.12
_BOTTOM_BAND = 0.90
_MIN_PAGES_FOR_REPETITION = 3
_REPETITION_RATIO = 0.6


def _normalize(text: str) -> str:
    return _DIGITS_RE.sub("#", " ".join(text.split())).strip().lower()


def _band(block: Block) -> str | None:
    if block.bbox[3] <= block.page_height * _TOP_BAND:
        return "top"
    if block.bbox[1] >= block.page_height * _BOTTOM_BAND:
        return "bottom"
    return None


def detect_furniture(blocks_by_page: dict[int, list[Block]]) -> dict[str, BlockRole]:
    """Identify running headers/footers and standalone page numbers so they can be
    excluded from the reconstructed EPUB text (spec section 15), by looking for
    text that repeats across most pages in the same margin band and position.
    """
    furniture: dict[str, BlockRole] = {}
    total_pages = len(blocks_by_page)
    if total_pages == 0:
        return furniture

    # normalized_text -> band -> set of pages it appeared on
    occurrences: dict[tuple[str, str], set[int]] = defaultdict(set)
    candidates: dict[tuple[str, str], list[Block]] = defaultdict(list)

    for page_num, blocks in blocks_by_page.items():
        for b in blocks:
            if b.kind != "text" or not b.text.strip():
                continue
            band = _band(b)
            if band is None:
                continue

            if _PAGE_NUMBER_RE.match(b.text.strip()):
                furniture[b.block_id] = BlockRole.PAGE_NUMBER
                continue

            key = (_normalize(b.text), band)
            occurrences[key].add(page_num)
            candidates[key].append(b)

    min_pages = max(_MIN_PAGES_FOR_REPETITION, int(total_pages * _REPETITION_RATIO))
    for key, pages in occurrences.items():
        if len(pages) >= min_pages:
            band = key[1]
            role = BlockRole.HEADER if band == "top" else BlockRole.FOOTER
            for b in candidates[key]:
                furniture[b.block_id] = role

    return furniture
