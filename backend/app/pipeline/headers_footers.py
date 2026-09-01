from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

from app.models.document import Block, BlockRole

_DIGITS_RE = re.compile(r"\d+")
# Page numbers, tolerating the spaces OCR inserts between digits: a scanned
# book routinely yields "4 1" for 41 and "1 00" for 100. Requiring \d{1,4} with
# no internal space let 141 page numbers through on one real book, where they
# were then misread as footnote bodies and rendered as notes in the EPUB.
_PAGE_NUMBER_RE = re.compile(r"^[\-–—\s]*\d[\d\s]{0,5}[\-–—\s]*$")
# A note body opens with its marker and then real prose. Running footers never
# look like this, so the pattern reliably separates the two.
_NOTE_BODY_RE = re.compile(r"^\s*([\d]{1,4}|[*†‡§¶#]{1,3})[.)\]]?\s+\S+")
_MIN_NOTE_BODY_WORDS = 3
_TOP_BAND = 0.12
_BOTTOM_BAND = 0.90
_MIN_PAGES_FOR_REPETITION = 3
# Books conventionally alternate running heads: author on the verso, title on
# the recto. Each therefore appears on only about half the pages, so a single
# 60%-of-all-pages rule detects neither and both get merged into the body text.
# Repetition is measured within the parity class the block actually appears in.
_REPETITION_RATIO = 0.55
_MIN_PARITY_PAGES = 6


def _normalize(text: str) -> str:
    return _DIGITS_RE.sub("#", " ".join(text.split())).strip().lower()


def _looks_like_note_body(text: str) -> bool:
    """True for "1 Some explanatory sentence." — a note, not page furniture."""
    stripped = text.strip()
    if not _NOTE_BODY_RE.match(stripped):
        return False
    return len(stripped.split()) >= _MIN_NOTE_BODY_WORDS


def _band(block: Block) -> str | None:
    if block.bbox[3] <= block.page_height * _TOP_BAND:
        return "top"
    if block.bbox[1] >= block.page_height * _BOTTOM_BAND:
        return "bottom"
    return None


# Page numbers are set at or below body size. A digit standing alone in display
# type is a chapter number ("1" above "Kurban"), and removing it as furniture
# both loses the number and orphans the chapter title from it.
_DISPLAY_TYPE_RATIO = 1.35


def _is_display_type(block: Block, body_size: float) -> bool:
    return bool(body_size) and bool(block.font_size) and block.font_size >= body_size * _DISPLAY_TYPE_RATIO


def _median_font_size(blocks_by_page: dict[int, list[Block]]) -> float:
    sizes: list[float] = []
    for blocks in blocks_by_page.values():
        for b in blocks:
            if b.kind == "text" and b.font_size and b.text.strip():
                sizes.extend([b.font_size] * min(len(b.text), 400))
    if not sizes:
        return 0.0
    sizes.sort()
    return sizes[len(sizes) // 2]


# A page number sits at the same place on every page and is set in the same
# small type. Once several are confirmed by their digits, that position and
# size identify the rest — including ones OCR mangled into letters ("51" -> "s ı").
_MIN_CONFIRMED_FOR_PROFILE = 5
_PROFILE_Y_TOLERANCE = 0.02  # fraction of page height
_PROFILE_SIZE_TOLERANCE = 0.18  # relative
_PROFILE_MAX_CHARS = 8
# Never applied to text set at body size: a short line of dialogue can sit at
# the very bottom of a page, and deleting it would destroy real content.
_PROFILE_MAX_BODY_RATIO = 0.85


@dataclass
class _PageNumberProfile:
    y_fraction: float
    font_size: float

    def matches(self, block: Block, body_size: float) -> bool:
        text = block.text.strip()
        if not text or len(text) > _PROFILE_MAX_CHARS:
            return False
        if not block.font_size or not block.page_height:
            return False
        if body_size and block.font_size > body_size * _PROFILE_MAX_BODY_RATIO:
            return False
        if abs(block.font_size - self.font_size) > self.font_size * _PROFILE_SIZE_TOLERANCE:
            return False
        y_fraction = block.bbox[1] / block.page_height
        return abs(y_fraction - self.y_fraction) <= _PROFILE_Y_TOLERANCE


def _build_page_number_profile(confirmed: list[Block]) -> _PageNumberProfile | None:
    """Learn where and how page numbers are set, from the ones we could read."""
    usable = [b for b in confirmed if b.font_size and b.page_height]
    if len(usable) < _MIN_CONFIRMED_FOR_PROFILE:
        return None
    y_fractions = sorted(b.bbox[1] / b.page_height for b in usable)
    sizes = sorted(b.font_size for b in usable)
    return _PageNumberProfile(
        y_fraction=y_fractions[len(y_fractions) // 2],
        font_size=sizes[len(sizes) // 2],
    )


def _is_repeating_furniture(
    pages: set[int], total_pages: int, odd_pages: int, even_pages: int
) -> bool:
    """Decide whether a margin block repeats often enough to be page furniture.

    Checked against the whole book *and* against each parity class on its own.
    A verso/recto alternating running head appears on only ~50% of all pages, so
    a single whole-book ratio recognises neither half and lets both bleed into
    the body text.
    """
    if len(pages) < _MIN_PAGES_FOR_REPETITION:
        return False
    if len(pages) >= max(_MIN_PAGES_FOR_REPETITION, int(total_pages * _REPETITION_RATIO)):
        return True

    odd_hits = sum(1 for p in pages if p % 2)
    even_hits = len(pages) - odd_hits
    for hits, available in ((odd_hits, odd_pages), (even_hits, even_pages)):
        if available >= _MIN_PARITY_PAGES and hits >= max(
            _MIN_PAGES_FOR_REPETITION, int(available * _REPETITION_RATIO)
        ):
            return True
    return False


def detect_furniture(blocks_by_page: dict[int, list[Block]]) -> dict[str, BlockRole]:
    """Identify running headers/footers and standalone page numbers so they can be
    excluded from the reconstructed EPUB text (spec section 15), by looking for
    text that repeats across most pages in the same margin band and position.
    """
    furniture: dict[str, BlockRole] = {}
    total_pages = len(blocks_by_page)
    if total_pages == 0:
        return furniture
    body_size = _median_font_size(blocks_by_page)

    # normalized_text -> band -> set of pages it appeared on
    occurrences: dict[tuple[str, str], set[int]] = defaultdict(set)
    candidates: dict[tuple[str, str], list[Block]] = defaultdict(list)
    confirmed_page_numbers: list[Block] = []

    for page_num, blocks in blocks_by_page.items():
        for b in blocks:
            if b.kind != "text" or not b.text.strip():
                continue
            band = _band(b)
            if band is None:
                continue

            if _PAGE_NUMBER_RE.match(b.text.strip()) and not _is_display_type(b, body_size):
                furniture[b.block_id] = BlockRole.PAGE_NUMBER
                confirmed_page_numbers.append(b)
                continue

            if band == "bottom" and _looks_like_note_body(b.text):
                # Footnote bodies live in the bottom margin band and can repeat
                # across pages ("Ibid.", a recurring source). Stripping them as
                # a running footer would silently delete real content, so they
                # are never eligible for furniture removal.
                #
                # Restricted to that band deliberately. A verso running head
                # that opens with its page number — "25 | Book Title" — matches
                # the note-body shape exactly, and protecting it here let the
                # title bleed into the body text on all eighty-one verso pages
                # while the recto form, "Book Title | 103", was stripped
                # correctly. A footnote at the top of a page is not a thing.
                continue

            key = (_normalize(b.text), band)
            occurrences[key].add(page_num)
            candidates[key].append(b)

    odd_pages = sum(1 for p in blocks_by_page if p % 2)
    even_pages = total_pages - odd_pages

    for key, pages in occurrences.items():
        if _is_repeating_furniture(pages, total_pages, odd_pages, even_pages):
            band = key[1]
            role = BlockRole.HEADER if band == "top" else BlockRole.FOOTER
            for b in candidates[key]:
                furniture[b.block_id] = role

    _remove_mangled_page_numbers(
        blocks_by_page, furniture, confirmed_page_numbers, body_size
    )
    return furniture


def _remove_mangled_page_numbers(
    blocks_by_page: dict[int, list[Block]],
    furniture: dict[str, BlockRole],
    confirmed: list[Block],
    body_size: float,
) -> None:
    """Catch page numbers whose digits OCR turned into letters.

    A scan yields "51" as "s ı" and "17" as "IR"; no digit pattern can match
    those, so they reached the EPUB as stray one-word paragraphs. They are
    identified here by *position and type size* instead — the page number sits
    in the same spot on every page — which is evidence text matching cannot
    provide and which cannot touch body-size text.
    """
    profile = _build_page_number_profile(confirmed)
    if profile is None:
        return

    for blocks in blocks_by_page.values():
        for block in blocks:
            if block.kind != "text" or block.block_id in furniture:
                continue
            if profile.matches(block, body_size):
                furniture[block.block_id] = BlockRole.PAGE_NUMBER
