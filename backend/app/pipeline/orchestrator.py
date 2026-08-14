from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path

from app.core.config import settings
from app.core.errors import ConversionError, EPUBValidationError, UnsupportedDocumentComplexityError
from app.core.logging import get_logger
from app.jobs import store
from app.models.document import Block, DocumentModel, PageTextKind, StructuralNode
from app.models.job import Job, JobStage
from app.pipeline import (
    analyze,
    bidi,
    endnotes as endnotes_module,
    enrich,
    extract,
    footnotes,
    headers_footers,
    headings as headings_module,
    paragraphs,
    reading_order,
    structure,
    tables as tables_module,
    verse as verse_module,
)
from app.pipeline import images as images_pipeline
from app.pipeline.ai.provider import get_provider
from app.pipeline.confidence import run_ai_review
from app.pipeline.epub.builder import build_epub, slugify
from app.pipeline.integrity import compute_integrity
from app.pipeline.ocr.page_ocr import ocr_page
from app.pipeline.quality import compute_quality_report
from app.pipeline.validate import validate_epub
from app.storage.temp_storage import epub_path_for, images_dir_for

logger = get_logger(__name__)


def _update(
    job: Job,
    *,
    stage: JobStage | None = None,
    detail: str = "",
    page: int | None = None,
    total: int | None = None,
) -> None:
    if stage is not None:
        job.stage = stage
    if detail:
        job.stage_detail = detail
    if page is not None:
        job.current_page = page
    if total is not None:
        job.total_pages = total
    job.updated_at = datetime.now()
    store.save_job(job)


async def run_pipeline(job_id: str) -> None:
    job = store.get_job(job_id)
    if job is None:
        logger.error("job %s vanished before processing could start", job_id)
        return
    await asyncio.to_thread(_run_pipeline_sync, job)


def _run_pipeline_sync(job: Job) -> None:
    """Synchronous entry point used both by the async job queue (via
    asyncio.to_thread) and directly by tests. Any conversion failure is
    translated into job.stage == FAILED here so both callers see identical
    behavior — nothing about error handling is queue-specific."""
    try:
        _execute_pipeline(job)
    except ConversionError as exc:
        job.stage = JobStage.FAILED
        job.error_code = exc.code
        job.error_message = exc.user_message
        _update(job)
        logger.warning("job %s failed: %s", job.job_id, exc.code)
    except Exception:
        job.stage = JobStage.FAILED
        job.error_code = "internal_error"
        job.error_message = "Something went wrong while converting this document. Your original PDF was not modified."
        _update(job)
        logger.exception("job %s failed with an unexpected error", job.job_id)


def _extract_page_blocks(
    page,
    page_index: int,
    kind: PageTextKind,
    document: DocumentModel,
    images_dir: Path,
    ocr_languages: str | None,
) -> tuple[list[Block], StructuralNode | None]:
    """Get one page's blocks using the cheapest reliable source for that page.

    NATIVE pages never touch Tesseract, which is what keeps a 500-page text
    book fully deterministic. Only SCANNED/MIXED pages pay for OCR, and a page
    OCR can't read confidently is preserved as an image rather than guessed at.
    """
    page_num = page_index + 1
    native_blocks = extract.extract_page_blocks(page, page_index)

    extracted_images = extract.extract_images(page, page_index, images_dir)
    for img in extracted_images:
        document.images[img["ref"]] = img
    image_blocks = images_pipeline.to_image_blocks(
        extracted_images, page.rect.width, page.rect.height
    )

    if kind == PageTextKind.NATIVE or kind == PageTextKind.EMPTY:
        return native_blocks + image_blocks, None

    if not settings.ocr_enabled:
        return native_blocks + image_blocks, None

    outcome = ocr_page(page, page_index, languages=ocr_languages)
    document.analysis.ocr_pages.append(page_num)

    if not outcome.reliable:
        if kind == PageTextKind.MIXED and native_blocks:
            # Keep the trustworthy native text; just don't add unreliable OCR.
            document.warnings.append(
                f"page {page_num}: OCR confidence {outcome.mean_confidence:.0f} too low; "
                "kept native text only"
            )
            return native_blocks + image_blocks, None
        fallback = enrich.preserve_page_as_image(
            document,
            page,
            page_num,
            images_dir,
            f"OCR confidence {outcome.mean_confidence:.0f} below "
            f"{settings.ocr_min_region_confidence:.0f}",
        )
        document.warnings.append(
            f"page {page_num}: preserved as an image (OCR confidence {outcome.mean_confidence:.0f})"
        )
        return native_blocks, fallback

    if kind == PageTextKind.SCANNED:
        # No trustworthy text layer: OCR is the only source.
        return outcome.blocks + image_blocks, None

    # MIXED: native text is authoritative; add OCR only for regions the native
    # layer doesn't already cover, so nothing gets duplicated.
    merged = native_blocks + _ocr_blocks_outside_native(outcome.blocks, native_blocks)
    return merged + image_blocks, None


def _ocr_blocks_outside_native(
    ocr_blocks: list[Block], native_blocks: list[Block]
) -> list[Block]:
    """Drop OCR blocks that overlap existing native text, keeping only OCR for
    parts of the page the text layer never covered."""
    kept: list[Block] = []
    for ocr_block in ocr_blocks:
        if any(_overlaps(ocr_block.bbox, native.bbox) for native in native_blocks):
            continue
        kept.append(ocr_block)
    return kept


def _overlaps(a: tuple[float, ...], b: tuple[float, ...], min_ratio: float = 0.35) -> bool:
    ix0, iy0 = max(a[0], b[0]), max(a[1], b[1])
    ix1, iy1 = min(a[2], b[2]), min(a[3], b[3])
    if ix1 <= ix0 or iy1 <= iy0:
        return False
    intersection = (ix1 - ix0) * (iy1 - iy0)
    area_a = max((a[2] - a[0]) * (a[3] - a[1]), 1e-6)
    return (intersection / area_a) >= min_ratio


def _merge_page_fallbacks(
    nodes: list[StructuralNode], fallbacks: list[StructuralNode]
) -> list[StructuralNode]:
    """Splice whole-page image fallbacks into reading order by page number, so a
    page we couldn't read still appears in the right place in the book."""
    by_page: dict[int, list[StructuralNode]] = {}
    for node in fallbacks:
        by_page.setdefault(node.page or 0, []).append(node)

    merged: list[StructuralNode] = []
    emitted: set[int] = set()
    for node in nodes:
        page = node.page or 0
        for pending_page in sorted(p for p in by_page if p < page and p not in emitted):
            merged.extend(by_page[pending_page])
            emitted.add(pending_page)
        merged.append(node)
    for remaining in sorted(p for p in by_page if p not in emitted):
        merged.extend(by_page[remaining])
    return merged


def _execute_pipeline(job: Job) -> None:
    _update(job, stage=JobStage.ANALYZING, detail="Opening PDF")
    doc = analyze.open_pdf(job.upload_path)
    try:
        analysis = analyze.analyze_pdf(doc)
        _update(job, detail="Classifying document", total=analysis.page_count)

        document = DocumentModel(source_filename=job.source_filename, analysis=analysis)
        document.metadata["title"] = analysis.title_guess or Path(job.source_filename).stem
        if analysis.author_guess:
            document.metadata["author"] = analysis.author_guess

        images_dir = images_dir_for(job.job_id)
        ocr_languages = bidi.ocr_languages_for_direction(analysis.language_guess)
        needs_ocr = [
            p for p, k in analysis.page_kinds.items() if k in (PageTextKind.SCANNED, PageTextKind.MIXED)
        ]
        if needs_ocr:
            logger.info(
                "job %s: %d of %d pages need OCR", job.job_id, len(needs_ocr), analysis.page_count
            )

        _update(job, stage=JobStage.EXTRACTING, detail="Extracting text and images", page=0)
        blocks_by_page: dict[int, list[Block]] = {}
        page_fallback_nodes: list[StructuralNode] = []
        pages: dict[int, object] = {}
        for i in range(analysis.page_count):
            page = doc[i]
            pages[i + 1] = page
            kind = analysis.page_kinds.get(i + 1, PageTextKind.NATIVE)
            if kind in (PageTextKind.SCANNED, PageTextKind.MIXED):
                _update(job, detail=f"Reading scanned page {i + 1} with OCR")
            page_blocks, fallback_node = _extract_page_blocks(
                page, i, kind, document, images_dir, ocr_languages
            )
            blocks_by_page[i + 1] = page_blocks
            if fallback_node is not None:
                page_fallback_nodes.append(fallback_node)
            _update(job, page=i + 1)

        all_blocks = [b for page_blocks in blocks_by_page.values() for b in page_blocks]
        document.blocks = all_blocks
        if document.analysis.ocr_pages:
            confidences = [b.ocr_confidence for b in all_blocks if b.ocr_confidence is not None]
            document.analysis.mean_ocr_confidence = (
                sum(confidences) / len(confidences) if confidences else 0.0
            )

        if not any(b.kind == "text" for b in all_blocks) and not page_fallback_nodes:
            raise UnsupportedDocumentComplexityError("No extractable text was found in this PDF.")

        text_blocks = [b for b in all_blocks if b.kind == "text"]
        bidi.annotate_block_directions(text_blocks)
        document.analysis.direction = bidi.document_direction(text_blocks)

        _update(job, stage=JobStage.STRUCTURE_ANALYSIS, detail="Reconstructing reading order and structure", page=0)
        ordered_blocks = reading_order.order_document_blocks(blocks_by_page)

        # Furniture detection must see pristine text: marking reference
        # candidates rewrites block text with sentinel characters, which would
        # stop a bare page number from matching the page-number pattern and get
        # it misread as a footnote marker.
        furniture = headers_footers.detect_furniture(blocks_by_page)

        body_size = structure.body_font_size(text_blocks)
        content_blocks = [b for b in text_blocks if b.block_id not in furniture]
        # Two passes: find which note numbers actually exist on each page, then
        # use that as the evidence gate when recovering reference markers that
        # OCR welded onto the preceding word.
        note_numbers = footnotes.collect_note_numbers_by_page(content_blocks, body_size)
        footnotes.mark_reference_candidates(content_blocks, body_size, note_numbers)

        nodes = structure.classify_blocks(ordered_blocks, furniture)

        blocks_by_id = {b.block_id: b for b in all_blocks}
        # "1" set above "Kurban" is one chapter heading, not two.
        headings_module.merge_division_numbers(nodes)
        headings_module.assign_heading_levels(nodes)

        # Tables first: their cells are short, ragged-right lines that would
        # otherwise look exactly like verse. Consuming them here means verse
        # detection only ever sees genuine running content.
        _update(job, detail="Detecting tables")
        detected_tables: list[tables_module.DetectedTable] = []
        for page_num, page in pages.items():
            detected_tables.extend(
                tables_module.detect_tables_on_page(page, blocks_by_page.get(page_num, []))
            )
        tables_module.mark_continuations(detected_tables)
        semantic_tables, table_fallbacks = enrich.apply_tables(
            document, nodes, detected_tables, pages, images_dir
        )

        # Verse before paragraph merging: its lines end without terminal
        # punctuation, so the merger would otherwise fuse a poem into a single
        # prose paragraph and destroy the line breaks.
        verse_count = verse_module.detect_verse(nodes, blocks_by_id)
        nodes = paragraphs.reconstruct_paragraphs(nodes)

        _update(job, detail="Detecting formulas")
        mathml_count, formula_fallbacks = enrich.apply_formulas(
            document, nodes, blocks_by_id, pages, images_dir
        )

        _update(job, stage=JobStage.AI_REVIEW, detail="Reviewing low-confidence structure")
        provider = get_provider(settings.ai_provider, anthropic_api_key=settings.anthropic_api_key)
        reviewed_count, _changed_count = run_ai_review(nodes, provider)

        # Footnotes first (page-local), then endnotes (collected sections), then
        # anything still unmatched degrades to a plain superscript.
        nodes, footnotes_linked = footnotes.link_references(nodes, leave_unmatched=True)
        endnote_count = endnotes_module.classify_endnote_sections(nodes)
        endnotes_linked = endnotes_module.link_endnote_references(nodes)
        unmatched_markers = footnotes.finalize_unmatched_markers(nodes)

        if page_fallback_nodes:
            nodes = _merge_page_fallbacks(nodes, page_fallback_nodes)

        bidi.annotate_node_directions(nodes)
        document.nodes = nodes

        _update(job, stage=JobStage.BUILDING_EPUB, detail="Building EPUB3 package")
        title = document.metadata.get("title") or "Untitled"
        author = document.metadata.get("author")
        language = analysis.language_guess or "en"
        epub_path = epub_path_for(job.job_id, slugify(title, "book"))
        build_result = build_epub(
            document, epub_path, title, author, language, direction=document.analysis.direction
        )
        build_result.verse_count = verse_count
        build_result.endnote_count = endnote_count
        build_result.endnote_linked_count = endnotes_linked
        build_result.table_count = semantic_tables
        build_result.image_fallback_count = table_fallbacks + formula_fallbacks + len(page_fallback_nodes)
        build_result.formula_count = mathml_count
        build_result.formula_fallback_count = formula_fallbacks
        build_result.unmatched_marker_count = unmatched_markers
        build_result.footnote_linked_count = footnotes_linked

        _update(job, stage=JobStage.VALIDATING, detail="Validating EPUB3 with EPUBCheck")
        validation = validate_epub(epub_path)
        if not validation.passed:
            raise EPUBValidationError(
                "The generated EPUB failed validation: " + "; ".join(validation.errors[:3] or ["unknown error"])
            )

        _update(job, stage=JobStage.QUALITY_CHECK, detail="Computing quality report")
        integrity = compute_integrity(document, build_result.word_count)
        quality = compute_quality_report(
            document, build_result, integrity, validation, provider.name, reviewed_count
        )

        job.epub_path = str(epub_path)
        job.quality_report = quality
        _update(job, stage=JobStage.COMPLETED, detail="Done")
    finally:
        doc.close()
