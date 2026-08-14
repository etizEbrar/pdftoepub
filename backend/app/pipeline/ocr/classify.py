from __future__ import annotations

import fitz

from app.core.config import settings
from app.models.document import PageTextKind

# A raster covering at least this fraction of the page, on a page whose text
# layer is thin, is the signature of a scanned page image.
_SCANNED_IMAGE_COVERAGE = 0.55
# On a page that *does* have real text, an additional large image this big may
# still hide un-extracted text (a scanned figure, a photographed table).
_MIXED_IMAGE_COVERAGE = 0.25


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


def classify_page(page: fitz.Page) -> PageTextKind:
    """Decide how a single page's text should be obtained.

    This is the gate that keeps OCR cheap: a 500-page native-text book answers
    NATIVE on every page and never invokes Tesseract at all.
    """
    native_chars = len(page.get_text("text").strip())
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
    return {i + 1: classify_page(doc[i]) for i in range(doc.page_count)}


def pages_needing_ocr(page_kinds: dict[int, PageTextKind]) -> list[int]:
    return [
        page
        for page, kind in sorted(page_kinds.items())
        if kind in (PageTextKind.SCANNED, PageTextKind.MIXED)
    ]
