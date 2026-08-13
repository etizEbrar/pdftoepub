from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path

from app.core.config import settings
from app.core.errors import ConversionError, EPUBValidationError, UnsupportedDocumentComplexityError
from app.core.logging import get_logger
from app.jobs import store
from app.models.document import Block, DocumentModel, PDFClassification
from app.models.job import Job, JobStage
from app.pipeline import analyze, extract, footnotes, headers_footers, paragraphs, reading_order, structure
from app.pipeline import images as images_pipeline
from app.pipeline.ai.provider import get_provider
from app.pipeline.confidence import run_ai_review
from app.pipeline.epub.builder import build_epub, slugify
from app.pipeline.integrity import compute_integrity
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


def _execute_pipeline(job: Job) -> None:
    _update(job, stage=JobStage.ANALYZING, detail="Opening PDF")
    doc = analyze.open_pdf(job.upload_path)
    try:
        analysis = analyze.analyze_pdf(doc)
        _update(job, detail="Classifying document", total=analysis.page_count)

        if analysis.classification == PDFClassification.SCANNED:
            raise UnsupportedDocumentComplexityError(
                "This PDF looks like a scanned document with no real text layer. "
                "OCR support is planned for a future update — for now we can only "
                "convert PDFs that already have extractable text."
            )

        document = DocumentModel(source_filename=job.source_filename, analysis=analysis)
        document.metadata["title"] = analysis.title_guess or Path(job.source_filename).stem
        if analysis.author_guess:
            document.metadata["author"] = analysis.author_guess

        images_dir = images_dir_for(job.job_id)

        _update(job, stage=JobStage.EXTRACTING, detail="Extracting text and images", page=0)
        blocks_by_page: dict[int, list[Block]] = {}
        for i in range(analysis.page_count):
            page = doc[i]
            text_blocks = extract.extract_page_blocks(page, i)
            extracted_images = extract.extract_images(page, i, images_dir)
            for img in extracted_images:
                document.images[img["ref"]] = img
            image_blocks = images_pipeline.to_image_blocks(extracted_images, page.rect.width, page.rect.height)
            blocks_by_page[i + 1] = text_blocks + image_blocks
            _update(job, page=i + 1)

        all_blocks = [b for page_blocks in blocks_by_page.values() for b in page_blocks]
        document.blocks = all_blocks

        if not any(b.kind == "text" for b in all_blocks):
            raise UnsupportedDocumentComplexityError("No extractable text was found in this PDF.")

        body_size = structure.body_font_size([b for b in all_blocks if b.kind == "text"])
        footnotes.mark_reference_candidates([b for b in all_blocks if b.kind == "text"], body_size)

        _update(job, stage=JobStage.STRUCTURE_ANALYSIS, detail="Reconstructing reading order and structure", page=0)
        ordered_blocks = reading_order.order_document_blocks(blocks_by_page)
        furniture = headers_footers.detect_furniture(blocks_by_page)
        nodes = structure.classify_blocks(ordered_blocks, furniture)
        nodes = paragraphs.reconstruct_paragraphs(nodes)

        _update(job, stage=JobStage.AI_REVIEW, detail="Reviewing low-confidence structure")
        provider = get_provider(settings.ai_provider, anthropic_api_key=settings.anthropic_api_key)
        reviewed_count, _changed_count = run_ai_review(nodes, provider)

        nodes, _footnotes_linked = footnotes.link_references(nodes)
        document.nodes = nodes

        _update(job, stage=JobStage.BUILDING_EPUB, detail="Building EPUB3 package")
        title = document.metadata.get("title") or "Untitled"
        author = document.metadata.get("author")
        language = analysis.language_guess or "en"
        epub_path = epub_path_for(job.job_id, slugify(title, "book"))
        build_result = build_epub(document, epub_path, title, author, language)

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
