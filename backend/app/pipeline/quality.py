from __future__ import annotations

from app.models.document import DocumentModel
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
    footnote_ratio = (
        build.footnote_linked_count / build.footnote_count if build.footnote_count else 1.0
    )
    structure_score = 1.0
    if document.analysis.page_count > 5 and build.heading_count == 0:
        structure_score = 0.5  # a book this long with no detected structure is suspicious, not a false 100%

    epubcheck_score = 1.0 if validation.passed else 0.0

    quality_score = round(
        100
        * (
            0.40 * integrity.ratio
            + 0.30 * epubcheck_score
            + 0.15 * footnote_ratio
            + 0.15 * structure_score
        ),
        1,
    )

    return QualityReport(
        title=document.metadata.get("title"),
        author=document.metadata.get("author"),
        page_count=document.analysis.page_count,
        chapter_count=build.chapter_count,
        heading_count=build.heading_count,
        paragraph_count=sum(1 for n in document.nodes if n.role.value == "paragraph"),
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
    )
