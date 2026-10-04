"""Blocks from OCR a client performed on its own device.

Tesseract reports its own block and paragraph numbering, and `page_ocr` trusts
it. Apple's Vision framework reports lines and nothing above them, so the
grouping has to be inferred from geometry here. Getting it wrong is not
cosmetic: a paragraph split in two reads as two paragraphs, a heading glued to
the text beneath it stops being a heading, and two columns merged into one
block interleave into nonsense.
"""

from __future__ import annotations

import statistics

from app.core.config import settings
from app.models.client_ocr import ClientOCRLine, ClientOCRPage
from app.pipeline.ocr.blocks import PlacedWord, blocks_from_placed_words
from app.pipeline.ocr.page_ocr import PageOCROutcome

# A new block starts when the vertical gap between two lines exceeds this
# multiple of the page's typical line height. Set from the spacing a book
# actually uses: leading inside a paragraph is roughly 1.15-1.35x the glyph
# height, while the space a typesetter puts above a heading or between
# paragraphs is wider. Below ~1.5 ordinary leading starts splitting paragraphs.
_BLOCK_GAP_RATIO = 1.75
# Two lines belong to one column only if their horizontal ranges genuinely
# overlap. A short last line of a paragraph still overlaps the line above it;
# a second column does not.
_MIN_HORIZONTAL_OVERLAP = 0.25


def _line_box(line: ClientOCRLine) -> tuple[float, float, float, float]:
    xs0 = min(w.bbox[0] for w in line.words)
    ys0 = min(w.bbox[1] for w in line.words)
    xs1 = max(w.bbox[2] for w in line.words)
    ys1 = max(w.bbox[3] for w in line.words)
    return (xs0, ys0, xs1, ys1)


def _horizontal_overlap(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    """Shared width as a fraction of the narrower line."""
    overlap = min(a[2], b[2]) - max(a[0], b[0])
    if overlap <= 0:
        return 0.0
    narrower = min(a[2] - a[0], b[2] - b[0])
    return overlap / narrower if narrower > 0 else 0.0


def _group_lines_into_blocks(lines: list[ClientOCRLine]) -> list[list[ClientOCRLine]]:
    """Collect lines into blocks by vertical proximity within a column."""
    if not lines:
        return []

    boxed = sorted(((_line_box(ln), ln) for ln in lines), key=lambda p: (p[0][1], p[0][0]))
    heights = [box[3] - box[1] for box, _ in boxed if box[3] > box[1]]
    typical = statistics.median(heights) if heights else 0.0
    max_gap = typical * _BLOCK_GAP_RATIO if typical else float("inf")

    groups: list[list[tuple[tuple[float, ...], ClientOCRLine]]] = []
    for box, line in boxed:
        placed = False
        # Search from the most recently extended group backwards: with two
        # columns the previous line is in the *other* column, so comparing
        # only against the last group would start a new block on every line.
        for group in reversed(groups):
            last_box = group[-1][0]
            gap = box[1] - last_box[3]
            if gap <= max_gap and _horizontal_overlap(box, last_box) >= _MIN_HORIZONTAL_OVERLAP:
                group.append((box, line))
                placed = True
                break
        if not placed:
            groups.append([(box, line)])

    return [[line for _, line in group] for group in groups]


def blocks_from_client_page(
    supplied: ClientOCRPage, page_width: float, page_height: float
) -> PageOCROutcome:
    """Convert one page of client OCR into Blocks indistinguishable from ours."""
    lines = [ln for ln in supplied.lines if ln.words]
    if not lines:
        return PageOCROutcome([], 0.0, 0, reliable=False, word_count=0)

    grouped = [
        [[PlacedWord(w.text, tuple(w.bbox), w.confidence) for w in line.words] for line in block]
        for block in _group_lines_into_blocks(lines)
    ]
    blocks = blocks_from_placed_words(
        grouped, supplied.page, page_width, page_height, id_prefix="cocr"
    )

    confidences = [w.confidence for ln in lines for w in ln.words]
    mean_confidence = sum(confidences) / len(confidences) if confidences else 0.0
    word_count = len(confidences)
    return PageOCROutcome(
        blocks=blocks,
        mean_confidence=mean_confidence,
        rotation=0,
        # The same floor Tesseract output is held to. Tesseract reports 0-100
        # and Vision reports 0-1, so the threshold is scaled rather than
        # duplicated: a client that reads a page badly is distrusted exactly
        # as readily as a server that does.
        reliable=mean_confidence >= settings.ocr_min_region_confidence / 100.0 and bool(blocks),
        word_count=word_count,
    )
