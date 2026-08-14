from __future__ import annotations

import statistics

import fitz

from app.core.config import settings
from app.models.document import PageTextKind

# A raster covering at least this fraction of the page, on a page whose text
# layer is thin, is the signature of a scanned page image.
_SCANNED_IMAGE_COVERAGE = 0.55
# On a page that *does* have text, an additional large image this big may still
# hide un-extracted text (a scanned figure, a photographed table).
_MIXED_IMAGE_COVERAGE = 0.25
# A page holding at least this share of the document's typical page is treated
# as having a complete text layer, however much imagery sits behind it.
_COMPLETE_TEXT_DENSITY_RATIO = 0.35


def image_coverage_ratio(page: fitz.Page) -> float:
    page_area = page.rect.width * page.rect.height
    if page_area <= 0:
        return 0.0
    covered = 0.0
    for img in page.get_images(full=True):
        try:
            rects = page.get_image_rects(img[0])
        except Exception:
            continue
        for r in rects:
            covered += max(0.0, r.width) * max(0.0, r.height)
    return min(covered / page_area, 1.0)


def typical_page_text_length(doc: fitz.Document, sample_limit: int = 400) -> int:
    """Median characters on a page that has any text at all.

    This is the yardstick for "does this page's text layer look complete?".
    Scanned books are routinely distributed with a full-page background image
    *and* a complete embedded OCR text layer; judged only by image coverage
    every such page looks like it needs OCR, when in fact none of them do.
    """
    step = max(1, doc.page_count // sample_limit)
    lengths = [
        len(doc[i].get_text("text").strip())
        for i in range(0, doc.page_count, step)
    ]
    non_empty = [n for n in lengths if n > 0]
    return int(statistics.median(non_empty)) if non_empty else 0


def classify_page(page: fitz.Page, typical_text_length: int = 0) -> PageTextKind:
    """Decide how a single page's text should be obtained.

    This is the gate that keeps OCR cheap: a 500-page native-text book answers
    NATIVE on every page and never invokes Tesseract at all.

    `typical_text_length` is the document's median page length. When supplied, a
    page carrying a comparable amount of text counts as fully covered by its
    text layer and is never re-OCR'd, no matter how much imagery is behind it.
    """
    native_chars = len(page.get_text("text").strip())

    # A text layer as substantial as the rest of the book needs no OCR. Checked
    # before image coverage, because a scanned-with-text-layer book has a
    # full-page image on every page and would otherwise all be re-read.
    if typical_text_length and native_chars >= typical_text_length * _COMPLETE_TEXT_DENSITY_RATIO:
        return PageTextKind.NATIVE

    coverage = image_coverage_ratio(page)

    if native_chars >= settings.ocr_min_native_chars_per_page:
        if coverage >= _MIXED_IMAGE_COVERAGE:
            return PageTextKind.MIXED
        return PageTextKind.NATIVE

    if coverage >= _SCANNED_IMAGE_COVERAGE:
        return PageTextKind.SCANNED

    if native_chars > 0:
        # Some text, no meaningful imagery: a sparse page (a part title, a
        # colophon) rather than something OCR could improve.
        return PageTextKind.NATIVE

    return PageTextKind.EMPTY


def classify_document(doc: fitz.Document) -> dict[int, PageTextKind]:
    typical = typical_page_text_length(doc)
    return {i + 1: classify_page(doc[i], typical) for i in range(doc.page_count)}


def pages_needing_ocr(page_kinds: dict[int, PageTextKind]) -> list[int]:
    return [
        page
        for page, kind in sorted(page_kinds.items())
        if kind in (PageTextKind.SCANNED, PageTextKind.MIXED)
    ]
