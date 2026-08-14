from __future__ import annotations

from app.models.document import BlockRole, DocumentModel
from app.models.job import QualityReport
from app.pipeline.epub.builder import BuildResult
from app.pipeline.integrity import IntegrityResult
from app.pipeline.validate import ValidationResult


# A book longer than this with no detected divisions has navigation a reader
# will struggle with, however valid the EPUB is.
_LONG_BOOK_PAGES = 40
_MIN_NAV_ENTRIES = 2
# Below this share of notes linked back to a reference, the note apparatus is
# present but not usable.
_ACCEPTABLE_NOTE_LINK_RATIO = 0.5


def assess_structure(
    document: DocumentModel,
    build: BuildResult,
    integrity: IntegrityResult,
    validation: ValidationResult,
) -> tuple[float, list[str]]:
    """Judge how *usable* the ebook is, separately from whether it is valid.

    EPUBCheck answers "is this a well-formed EPUB", which a book with one
    chapter and no working notes can pass comfortably. This answers the
    different question a reader cares about, and any shortfall is surfaced
    rather than averaged away into a single flattering score.
    """
    reasons: list[str] = []
    components: list[float] = []

    if document.analysis.page_count >= _LONG_BOOK_PAGES:
        if build.chapter_count < _MIN_NAV_ENTRIES:
            reasons.append(
                f"only {build.chapter_count} chapter(s) detected across "
                f"{document.analysis.page_count} pages — navigation will be limited"
            )
            components.append(0.25)
        elif build.chapter_count < document.analysis.page_count / 120:
            reasons.append("chapter divisions are sparse for a book this long")
            components.append(0.6)
        else:
            components.append(1.0)
    else:
        components.append(1.0)

    total_notes = build.footnote_count + build.endnote_count
    linked_notes = build.footnote_linked_count + build.endnote_linked_count
    if total_notes:
        ratio = linked_notes / total_notes
        components.append(min(ratio, 1.0))
        if ratio < _ACCEPTABLE_NOTE_LINK_RATIO:
            reasons.append(
                f"{linked_notes} of {total_notes} notes could be linked to a "
                "reference in the text; the rest are readable but not clickable"
            )
    else:
        components.append(1.0)

    if build.unmatched_marker_count:
        reasons.append(
            f"{build.unmatched_marker_count} reference marker(s) had no matching note "
            "and are shown as plain superscripts"
        )

    if integrity.suspicious:
        reasons.extend(integrity.notes[:3])
        components.append(0.4)
    else:
        components.append(1.0)

    if not validation.passed:
        reasons.append("EPUB failed validation")
        components.append(0.0)
    else:
        components.append(1.0)

    if document.analysis.ocr_pages and (document.analysis.mean_ocr_confidence or 0) < 80:
        reasons.append(
            f"OCR confidence averaged {document.analysis.mean_ocr_confidence:.0f}% on "
            f"{len(document.analysis.ocr_pages)} page(s)"
        )

    score = round(100 * (sum(components) / len(components)), 1) if components else 0.0
    return score, reasons


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

    # Weight used inside the blended quality score, distinct from the separate
    # structure assessment computed below.
    structure_weight = 1.0
    if document.analysis.page_count > 5 and build.heading_count == 0:
        structure_weight = 0.5  # a book this long with no structure is suspicious

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
                + 0.13 * structure_weight
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
                + 0.15 * structure_weight
            ),
            1,
        )

    # Unaccounted content is a correctness problem, not a cosmetic one.
    if integrity.suspicious:
        quality_score = round(min(quality_score, 85.0), 1)

    structure_score, review_reasons = assess_structure(document, build, integrity, validation)

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
        footnotes_linked=build.footnote_linked_count,
        endnotes_linked=build.endnote_linked_count,
        unmatched_marker_count=build.unmatched_marker_count,
        navigation_entry_count=build.chapter_count + build.heading_count,
        structure_score=structure_score,
        needs_review=bool(review_reasons),
        review_reasons=review_reasons,
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
