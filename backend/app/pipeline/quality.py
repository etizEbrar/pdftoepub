from __future__ import annotations

from app.models.document import BlockRole, DocumentModel
from app.models.job import QualityReport
from app.pipeline.epub.builder import BuildResult
from app.pipeline.integrity import IntegrityResult
from app.pipeline.validate import ValidationResult


def compute_quality_report(
    document: DocumentModel,
    build: BuildResult,
    integrity: IntegrityResult,
    validation: ValidationResult,
    ai_provider_used: str,
    ai_blocks_reviewed: int,
) -> QualityReport:
    """A real score from real metrics — never an invented number (spec section 38)."""
    total_notes = build.footnote_count + build.endnote_count
    linked_notes = build.footnote_linked_count + build.endnote_linked_count
    note_ratio = (linked_notes / total_notes) if total_notes else 1.0
    note_ratio = min(note_ratio, 1.0)

    structure_score = 1.0
    if document.analysis.page_count > 5 and build.heading_count == 0:
        structure_score = 0.5  # a book this long with no detected structure is suspicious

    epubcheck_score = 1.0 if validation.passed else 0.0

    # OCR quality only participates when OCR was actually used.
    ocr_confidence = document.analysis.mean_ocr_confidence
    if ocr_confidence is not None:
        ocr_score = max(0.0, min(ocr_confidence / 100.0, 1.0))
        quality_score = round(
            100
            * (
                0.32 * integrity.ratio
                + 0.26 * epubcheck_score
                + 0.14 * note_ratio
                + 0.13 * structure_score
                + 0.15 * ocr_score
            ),
            1,
        )
    else:
        quality_score = round(
            100
            * (
                0.40 * integrity.ratio
                + 0.30 * epubcheck_score
                + 0.15 * note_ratio
                + 0.15 * structure_score
            ),
            1,
        )

    # Unaccounted content is a correctness problem, not a cosmetic one.
    if integrity.suspicious:
        quality_score = round(min(quality_score, 85.0), 1)

    return QualityReport(
        title=document.metadata.get("title"),
        author=document.metadata.get("author"),
        page_count=document.analysis.page_count,
        chapter_count=build.chapter_count,
        heading_count=build.heading_count,
        paragraph_count=sum(1 for n in document.nodes if n.role == BlockRole.PARAGRAPH),
        footnote_count=build.footnote_count,
        image_count=build.image_count,
        table_count=build.table_count,
        word_count_source=integrity.source_word_count,
        word_count_epub=integrity.epub_word_count,
        content_integrity_ratio=round(integrity.ratio, 4),
        epubcheck_passed=validation.passed,
        epubcheck_errors=validation.errors,
        epubcheck_warnings=validation.warnings,
        ai_provider_used=ai_provider_used,
        ai_blocks_reviewed=ai_blocks_reviewed,
        quality_score=quality_score,
        endnote_count=build.endnote_count,
        verse_count=build.verse_count,
        formula_count=build.formula_count,
        image_fallback_count=build.image_fallback_count,
        rtl_block_count=build.rtl_block_count,
        ocr_page_count=len(document.analysis.ocr_pages),
        ocr_mean_confidence=(round(ocr_confidence, 1) if ocr_confidence is not None else None),
        content_integrity_suspicious=integrity.suspicious,
        content_integrity_notes=integrity.notes,
    )
