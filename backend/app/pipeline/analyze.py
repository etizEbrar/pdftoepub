from __future__ import annotations

import fitz  # PyMuPDF

from app.core.errors import CorruptedPDFError, EncryptedPDFError, UnsupportedPDFError
from app.core.logging import get_logger
from app.models.document import PDFAnalysis, PDFClassification

logger = get_logger(__name__)

# A page counts as "scanned" if its text layer is essentially empty relative to
# its size but it contains a large raster image covering most of the page.
_MIN_CHARS_PER_PAGE_FOR_TEXT = 20
_SCANNED_IMAGE_COVERAGE_RATIO = 0.85


def open_pdf(path: str) -> fitz.Document:
    try:
        doc = fitz.open(path)
    except fitz.FileDataError as exc:
        raise CorruptedPDFError() from exc
    except Exception as exc:  # pragma: no cover - fitz raises many concrete subtypes
        raise UnsupportedPDFError() from exc

    if doc.page_count == 0:
        doc.close()
        raise CorruptedPDFError("This PDF has no pages.")

    if doc.needs_pass:
        doc.close()
        raise EncryptedPDFError()

    return doc


def _page_image_coverage_ratio(page: fitz.Page) -> float:
    page_area = page.rect.width * page.rect.height
    if page_area <= 0:
        return 0.0
    covered = 0.0
    for img in page.get_images(full=True):
        xref = img[0]
        try:
            rects = page.get_image_rects(xref)
        except Exception:
            continue
        for r in rects:
            covered += max(0.0, r.width) * max(0.0, r.height)
    return min(covered / page_area, 1.0)


def _guess_language(sample_text: str) -> str | None:
    if len(sample_text.strip()) < 40:
        return None
    try:
        from langdetect import DetectorFactory, detect

        DetectorFactory.seed = 0  # deterministic results
        return detect(sample_text)
    except Exception:
        return None


def analyze_pdf(doc: fitz.Document) -> PDFAnalysis:
    page_count = doc.page_count
    scanned_pages = 0
    text_chars = 0
    sample_text_parts: list[str] = []

    for page_index in range(page_count):
        page = doc[page_index]
        page_text = page.get_text("text")
        text_chars += len(page_text.strip())
        if len(sample_text_parts) < 5 and page_text.strip():
            sample_text_parts.append(page_text[:2000])

        looks_empty_of_text = len(page_text.strip()) < _MIN_CHARS_PER_PAGE_FOR_TEXT
        if looks_empty_of_text and _page_image_coverage_ratio(page) >= _SCANNED_IMAGE_COVERAGE_RATIO:
            scanned_pages += 1

    scanned_ratio = scanned_pages / page_count if page_count else 0.0
    has_text_layer = text_chars >= _MIN_CHARS_PER_PAGE_FOR_TEXT * max(1, page_count - scanned_pages)

    if scanned_ratio >= 0.95:
        classification = PDFClassification.SCANNED
    elif scanned_ratio >= 0.15:
        classification = PDFClassification.MIXED
    elif has_text_layer:
        classification = PDFClassification.NATIVE_TEXT
    else:
        classification = PDFClassification.UNKNOWN

    outline = _extract_outline(doc)
    meta = doc.metadata or {}

    return PDFAnalysis(
        page_count=page_count,
        classification=classification,
        has_text_layer=has_text_layer,
        scanned_page_ratio=scanned_ratio,
        outline=outline,
        title_guess=(meta.get("title") or "").strip() or None,
        author_guess=(meta.get("author") or "").strip() or None,
        language_guess=_guess_language(" ".join(sample_text_parts)),
        is_encrypted=doc.is_encrypted,
    )


def _extract_outline(doc: fitz.Document) -> list[dict]:
    toc = doc.get_toc(simple=True)  # [[level, title, page], ...]
    return [{"level": level, "title": title, "page": page} for level, title, page in toc]
