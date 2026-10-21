from __future__ import annotations

import difflib
import re
from collections import defaultdict
from dataclasses import dataclass

from app.models.document import Block, BlockRole

_DIGITS_RE = re.compile(r"\d+")
# Page numbers, tolerating the spaces OCR inserts between digits: a scanned
# book routinely yields "4 1" for 41 and "1 00" for 100. Requiring \d{1,4} with
# no internal space let 141 page numbers through on one real book, where they
# were then misread as footnote bodies and rendered as notes in the EPUB.
#
# Printers also dress the folio up -- "• 12 •", "- 7 -", ". 9 ." -- and OCR reads
# those ornaments as whatever mark is nearest: "• 12-", "280*", "•2 1 •". On a
# real novel every one of them reached the EPUB, most as a bulleted list item
# glued to the first line of the next page.
_FOLIO_ORNAMENT = r"[\-–—•·∙*.,:;'\"`´^~_|°‹›<>«»()\[\]\s]"
_PAGE_NUMBER_RE = re.compile(rf"^{_FOLIO_ORNAMENT}*\d[\d\s]{{0,5}}{_FOLIO_ORNAMENT}*$")
# A note body opens with its marker and then real prose. Running footers never
# look like this, so the pattern reliably separates the two.
_NOTE_BODY_RE = re.compile(r"^\s*([\d]{1,4}|[*†‡§¶#]{1,3})[.)\]]?\s+\S+")
_MIN_NOTE_BODY_WORDS = 3
_TOP_BAND = 0.12
_TOP_BAND_START = 0.10
_BOTTOM_BAND = 0.90
_MIN_PAGES_FOR_REPETITION = 3
# Books conventionally alternate running heads: author on the verso, title on
# the recto. Each therefore appears on only about half the pages, so a single
# 60%-of-all-pages rule detects neither and both get merged into the body text.
# Repetition is measured within the parity class the block actually appears in.
_REPETITION_RATIO = 0.55
_MIN_PARITY_PAGES = 4
# "7 | Book Title", "Book Title | 8": a running head carrying its folio. The
# shape alone identifies it, so a head that repeats on too few pages to be
# proven by repetition -- a short document, or one page whose head differs --
# no longer stays in the text, where it ended the paragraph crossing it.
_FOLIO_HEAD_RE = re.compile(
    r"^\s*(?:\d{1,4}\s*[|│•·]\s*\S.*|.*\S\s*[|│•·]\s*\d{1,4})\s*$"
)
_MAX_FOLIO_HEAD_WORDS = 14


_MIN_KEY_LETTERS = 4


def _normalize(text: str) -> str:
    # Spaces are dropped, not collapsed. A running head set letter-spaced comes
    # out of OCR with the gaps in a different place on every page -- "ÇEKEN",
    # "ÇEK EN", "Ç E K E N" -- and compared word by word no two pages agreed.
    #
    # So are digits and punctuation, where letters remain to compare: a scan's
    # head reads "83 A STUDY IN SCARLET," on one page and "A STUDY IN
    # SCARLET. 97" on the next, and as three different lines none of them
    # repeated often enough to be recognised.
    letters = "".join(c for c in text.casefold() if c.isalpha())
    if len(letters) >= _MIN_KEY_LETTERS:
        return letters
    return _DIGITS_RE.sub("#", "".join(text.split())).lower()


def _looks_like_note_body(text: str) -> bool:
    """True for "1 Some explanatory sentence." — a note, not page furniture."""
    stripped = text.strip()
    if not _NOTE_BODY_RE.match(stripped):
        return False
    return len(stripped.split()) >= _MIN_NOTE_BODY_WORDS


# The first or last line of a page is the place for a running head or foot,
# wherever the scanner put the page: in one book the head sat at 11-13% of
# the page height, half its pages either side of a fixed band.
_EDGE_MAX_CHARS = 90
_EDGE_MAX_LINES = 2


def _edge_blocks(blocks: list[Block]) -> dict[str, str]:
    text = [b for b in blocks if b.kind == "text" and b.text.strip()]
    if len(text) < 3:
        return {}
    edges: dict[str, str] = {}
    for block, band in ((min(text, key=lambda b: b.bbox[1]), "top"), (max(text, key=lambda b: b.bbox[3]), "bottom")):
        stripped = block.text.strip()
        if len(stripped) <= _EDGE_MAX_CHARS and stripped.count("\n") < _EDGE_MAX_LINES:
            edges[block.block_id] = band
    return edges


def _band(block: Block) -> str | None:
    if block.bbox[3] <= block.page_height * _TOP_BAND:
        return "top"
    # A scan sits a little lower on some pages than others; a head of a line
    # or two that starts in the band is in it.
    if block.bbox[1] <= block.page_height * _TOP_BAND_START and block.text.strip().count("\n") <= 1:
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


# Type a chapter's title is set in. Higher than the display-type mark: a
# scanner's text layer sizes each line to the ink it covers, and a running
# head in capitals came out 1.2-1.4 times the body.
_CHAPTER_TITLE_RATIO = 1.5


def _is_chapter_title_type(block: Block, body_size: float) -> bool:
    return bool(body_size) and bool(block.font_size) and block.font_size >= body_size * _CHAPTER_TITLE_RATIO


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
        edges = _edge_blocks(blocks)
        for b in blocks:
            if b.kind != "text" or not b.text.strip():
                continue
            band = _band(b)
            if band is None:
                edge = edges.get(b.block_id)
                if edge is not None:
                    # Outside the fixed bands but first or last on its page:
                    # furniture only if it repeats like furniture.
                    key = (_normalize(b.text), edge)
                    occurrences[key].add(page_num)
                    candidates[key].append(b)
                continue

            # The display-type guard protects a chapter number above its title;
            # in the bottom margin the large type is an ornament's, not a digit's.
            if _PAGE_NUMBER_RE.match(b.text.strip()) and (
                band == "bottom" or not _is_display_type(b, body_size)
            ):
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

            if (
                _FOLIO_HEAD_RE.match(" ".join(b.text.split()))
                and len(b.text.split()) <= _MAX_FOLIO_HEAD_WORDS
                and "\n" not in b.text.strip()
                and not (body_size and b.font_size and b.font_size > body_size * 1.05)
            ):
                furniture[b.block_id] = BlockRole.HEADER if band == "top" else BlockRole.FOOTER
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
                # A chapter opening set in display type at the top of its page
                # can carry the very words of the running head over the pages
                # after it -- "GİRİŞ" over "Giriş" -- and is the chapter's title.
                if _is_chapter_title_type(b, body_size):
                    continue
                furniture[b.block_id] = role

    _remove_misread_running_heads(candidates, furniture, body_size)
    _remove_mangled_page_numbers(
        blocks_by_page, furniture, confirmed_page_numbers, body_size
    )
    return furniture


# How close a margin line must come to a proven running head to be one of its
# misreadings. "FREDRIGK BACKMAN" against "FREDRICKBACKMAN" scores 0.9; unrelated
# short lines of prose score well under 0.6.
_MISREAD_HEAD_SIMILARITY = 0.8
_MIN_HEAD_KEY_CHARS = 6


def _remove_misread_running_heads(
    candidates: dict[tuple[str, str], list[Block]],
    furniture: dict[str, BlockRole],
    body_size: float,
) -> None:
    """Catch running heads that OCR read differently on a page or two.

    Repetition proves the head on most pages, but a scan misreads it now and
    then -- "FREDRIGK BACKMAN" for "FREDRIK BACKMAN" -- and each misreading is
    unique, so it never repeats and was left in the text as a stray blockquote.
    A single line in the same margin, in type no larger than the body, that
    reads almost exactly like a proven head is that head.
    """
    proven: dict[str, list[str]] = defaultdict(list)
    for (key, band), blocks in candidates.items():
        # Proven by most of its occurrences: one of them may be a title page
        # in display type that was rightly kept.
        marked = sum(1 for b in blocks if b.block_id in furniture)
        if len(key) >= _MIN_HEAD_KEY_CHARS and marked >= max(1, len(blocks) * 0.8):
            proven[band].append(key)
    if not proven:
        return
    for (key, band), blocks in candidates.items():
        if not proven.get(band) or len(key) < _MIN_HEAD_KEY_CHARS:
            continue
        if all(b.block_id in furniture for b in blocks):
            continue
        if not any(
            difflib.SequenceMatcher(None, key, head).ratio() >= _MISREAD_HEAD_SIMILARITY
            for head in proven[band]
        ):
            continue
        for b in blocks:
            # A head and its folio may come as two lines of one block.
            if b.text.strip().count("\n") >= _EDGE_MAX_LINES or len(b.text.strip()) > _EDGE_MAX_CHARS:
                continue
            if _is_chapter_title_type(b, body_size):
                continue
            furniture[b.block_id] = BlockRole.HEADER if band == "top" else BlockRole.FOOTER


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
