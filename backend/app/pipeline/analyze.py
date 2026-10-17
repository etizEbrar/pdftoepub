from __future__ import annotations

import re
import unicodedata

import fitz  # PyMuPDF

from app.core.config import settings
from app.core.errors import (
    CorruptedPDFError,
    EncryptedPDFError,
    UnsupportedDocumentComplexityError,
    UnsupportedPDFError,
)
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

    # A PDF can declare far more pages than anyone would convert, and each page
    # costs real work. Refuse before that occupies a worker for hours.
    if doc.page_count > settings.max_page_count:
        page_count = doc.page_count
        doc.close()
        raise UnsupportedDocumentComplexityError(
            f"This PDF has {page_count:,} pages, more than the "
            f"{settings.max_page_count:,}-page limit."
        )

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


# Pages sampled for the language, spread through the book. The opening pages
# alone are the wrong place to look: a Turkish volume's copyright page is in
# English, and the whole book was declared English because of it.
_LANGUAGE_SAMPLE_PAGES = 8
# Pages searched for the title when the PDF's own metadata cannot be trusted.
_TITLE_SEARCH_PAGES = 3
_MAX_TITLE_CHARS = 200
# Metadata a word processor or scanner fills in on its own.
_BOILERPLATE_TITLE_RE = re.compile(
    r"^(untitled|document\d*|microsoft (word|powerpoint)\b.*|.*\.(docx?|pdf|indd|tex|odt))$",
    re.IGNORECASE,
)


def _folded(text: str) -> str:
    """Text reduced for comparison: no case, no accents, single spaces."""
    decomposed = unicodedata.normalize("NFKD", text.casefold().replace("ı", "i"))
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(re.findall(r"\w+", stripped))


def _metadata_title_is_plausible(title: str, opening_text: str) -> bool:
    """Whether the title in the PDF's metadata names this book.

    Metadata is whatever the authoring tool left there. This book's said
    "ÖNK" -- the first letters of its preface, saved from a draft -- and that
    became the book's name in every reader's library. A real title is printed
    on the book's opening pages.
    """
    if len(title) < 4 or _BOILERPLATE_TITLE_RE.match(title):
        return False
    words = _folded(title).split()
    if not words:
        return False
    page_words = set(_folded(opening_text).split())
    present = sum(1 for w in words if w in page_words)
    return present / len(words) >= 0.6


def _title_from_pages(doc: fitz.Document) -> str | None:
    """The largest type on the first pages that carry text: the title page."""
    for page_index in range(min(_TITLE_SEARCH_PAGES, doc.page_count)):
        spans = []
        for block in doc[page_index].get_text("dict").get("blocks", []):
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = span.get("text", "").strip()
                    if sum(c.isalpha() for c in text) >= 2:
                        spans.append((float(span.get("size", 0.0)), span.get("bbox", (0, 0, 0, 0)), text))
        if not spans:
            continue
        largest = max(size for size, _, _ in spans)
        sizes = sorted(size for size, _, _ in spans)
        median = sizes[len(sizes) // 2]
        if largest < median * 1.3 and len(spans) > 3:
            # Nothing on the page is set as a title.
            continue
        title_spans = sorted(
            (bbox[1], bbox[0], text) for size, bbox, text in spans if size >= largest * 0.9
        )
        title = " ".join(" ".join(text for _, _, text in title_spans).split())
        if 3 <= len(title) <= _MAX_TITLE_CHARS:
            return title
    return None


def _language_sample(doc: fitz.Document) -> str:
    count = doc.page_count
    if count <= _LANGUAGE_SAMPLE_PAGES:
        indices = range(count)
    else:
        step = count / (_LANGUAGE_SAMPLE_PAGES + 1)
        indices = sorted({int(step * (i + 1)) for i in range(_LANGUAGE_SAMPLE_PAGES)})
    return " ".join(doc[i].get_text("text")[:2000] for i in indices)


def analyze_pdf(doc: fitz.Document) -> PDFAnalysis:
    page_count = doc.page_count
    text_chars = 0
    sample_text_parts: list[str] = []
    opening_parts: list[str] = []

    for page_index in range(page_count):
        page_text = doc[page_index].get_text("text")
        text_chars += len(page_text.strip())
        if len(sample_text_parts) < 5 and page_text.strip():
            sample_text_parts.append(page_text[:2000])
        if page_index < _TITLE_SEARCH_PAGES + 2:
            opening_parts.append(page_text)

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
    metadata_title = " ".join((meta.get("title") or "").split())
    if metadata_title and _metadata_title_is_plausible(metadata_title, " ".join(opening_parts)):
        title_guess = metadata_title
    else:
        title_guess = _title_from_pages(doc)
    language_sample = _language_sample(doc) if has_text_layer else sample_text

    return PDFAnalysis(
        page_count=page_count,
        classification=classification,
        has_text_layer=has_text_layer,
        scanned_page_ratio=scanned_ratio,
        outline=_extract_outline(doc),
        title_guess=title_guess,
        author_guess=(meta.get("author") or "").strip() or None,
        language_guess=_guess_language(language_sample) or _guess_language(sample_text),
        is_encrypted=doc.is_encrypted,
        page_kinds=page_kinds,
        direction=detect_direction(sample_text) if sample_text.strip() else TextDirection.LTR,
    )


def _extract_outline(doc: fitz.Document) -> list[dict]:
    toc = doc.get_toc(simple=True)  # [[level, title, page], ...]
    return [{"level": level, "title": title, "page": page} for level, title, page in toc]
