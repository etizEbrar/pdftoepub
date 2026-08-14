"""Performance guarantees for large books.

The pipeline must stay predominantly deterministic on ordinary text books: a
500-page novel should never pay for OCR or page rasterization.
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

import pytest

from app.core.config import settings
from app.jobs import store
from app.models.document import PageTextKind
from app.models.job import ConversionMode, Job, JobStage
from app.pipeline.ocr.classify import classify_document, pages_needing_ocr
from app.pipeline.validate import epubcheck_available
from tests.fixtures.corpus import build_large_book

LARGE_BOOK_PAGES = 520


@pytest.fixture(scope="module")
def large_book(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("large") / "large_book.pdf"
    return build_large_book(path, pages=LARGE_BOOK_PAGES)


def test_large_native_book_classifies_every_page_as_native(large_book: Path):
    import fitz

    doc = fitz.open(str(large_book))
    kinds = classify_document(doc)
    doc.close()

    assert len(kinds) == LARGE_BOOK_PAGES
    assert all(kind == PageTextKind.NATIVE for kind in kinds.values())
    assert pages_needing_ocr(kinds) == [], "a native-text book must never be routed to OCR"


def test_page_classification_of_a_500_page_book_is_fast(large_book: Path):
    """Classification runs on every page, so it must stay cheap."""
    import fitz

    doc = fitz.open(str(large_book))
    start = time.time()
    classify_document(doc)
    elapsed = time.time() - start
    doc.close()

    assert elapsed < 20.0, f"classifying {LARGE_BOOK_PAGES} pages took {elapsed:.1f}s"


@pytest.mark.skipif(not epubcheck_available(), reason="epubcheck is not installed")
def test_large_book_converts_without_ocr_or_rasterization(large_book: Path):
    """The end-to-end guarantee: a long text book stays fully deterministic."""
    job_id = "perf-large-book"
    job = Job(
        job_id=job_id,
        source_filename=large_book.name,
        mode=ConversionMode.MAXIMUM_ACCURACY,
        upload_path=str(large_book),
    )
    store.save_job(job)
    start = time.time()
    try:
        from app.pipeline.orchestrator import _run_pipeline_sync

        _run_pipeline_sync(job)
    finally:
        store.delete_job(job_id)

    elapsed = time.time() - start
    try:
        assert job.stage == JobStage.COMPLETED, f"{job.error_code}: {job.error_message}"
        report = job.quality_report
        assert report is not None

        assert report.page_count == LARGE_BOOK_PAGES
        assert report.ocr_page_count == 0, "OCR must not run on a native-text book"
        assert report.image_fallback_count == 0, "nothing should need rasterizing"
        assert report.ai_provider_used == "none"
        assert report.epubcheck_passed is True
        assert report.chapter_count >= 10

        # Generous, but catches an accidental per-page OCR or render regression,
        # which would push this into many minutes.
        assert elapsed < 240, f"conversion of {LARGE_BOOK_PAGES} pages took {elapsed:.0f}s"
    finally:
        shutil.rmtree(settings.jobs_dir / job_id, ignore_errors=True)
