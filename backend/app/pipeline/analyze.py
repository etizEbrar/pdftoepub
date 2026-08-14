from __future__ import annotations

import fitz  # PyMuPDF

from app.core.errors import CorruptedPDFError, EncryptedPDFError, UnsupportedPDFError
from app.core.logging import get_logger
from app.models.document import PageTextKind, PDFAnalysis, PDFClassification, TextDirection
from app.pipeline.bidi import detect_direction
from app.pipeline.ocr.classify import classify_document

logger = get_logger(__name__)

# A page counts as "scanned" if its text layer is essentially empty relative to
# its size but it contains a large raster image covering most of the page.
_MIN_CHARS_PER_PAGE_FOR_TEXT = 20


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
    text_chars = 0
    sample_text_parts: list[str] = []

    for page_index in range(page_count):
        page_text = doc[page_index].get_text("text")
        text_chars += len(page_text.strip())
        if len(sample_text_parts) < 5 and page_text.strip():
            sample_text_parts.append(page_text[:2000])

    # Per-page routing decisions live in one place (pipeline/ocr/classify.py) so
    # document-level classification and OCR routing can never disagree.
    page_kinds = classify_document(doc)
    scanned_pages = sum(1 for k in page_kinds.values() if k == PageTextKind.SCANNED)
    mixed_pages = sum(1 for k in page_kinds.values() if k == PageTextKind.MIXED)
    scanned_ratio = scanned_pages / page_count if page_count else 0.0
    has_text_layer = text_chars >= _MIN_CHARS_PER_PAGE_FOR_TEXT * max(1, page_count - scanned_pages)

    if scanned_ratio >= 0.95:
        classification = PDFClassification.SCANNED
    elif scanned_ratio > 0 or mixed_pages > 0:
        classification = PDFClassification.MIXED
    elif has_text_layer:
        classification = PDFClassification.NATIVE_TEXT
    else:
        classification = PDFClassification.UNKNOWN

    meta = doc.metadata or {}
    sample_text = " ".join(sample_text_parts)

    return PDFAnalysis(
        page_count=page_count,
        classification=classification,
        has_text_layer=has_text_layer,
        scanned_page_ratio=scanned_ratio,
        outline=_extract_outline(doc),
        title_guess=(meta.get("title") or "").strip() or None,
        author_guess=(meta.get("author") or "").strip() or None,
        language_guess=_guess_language(sample_text),
        is_encrypted=doc.is_encrypted,
        page_kinds=page_kinds,
        direction=detect_direction(sample_text) if sample_text.strip() else TextDirection.LTR,
    )


def _extract_outline(doc: fitz.Document) -> list[dict]:
    toc = doc.get_toc(simple=True)  # [[level, title, page], ...]
    return [{"level": level, "title": title, "page": page} for level, title, page in toc]
