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


# --------------------------------------------------------------------------
# Reconstruction quality has to hold at book length, not just on a short
# fixture. The earlier long-book fixture put 28 self-contained lines on every
# page, so paragraph merging, hyphenation repair and furniture stripping were
# never exercised at scale — there was not one paragraph boundary in 520 pages.
# --------------------------------------------------------------------------


@pytest.mark.skipif(not epubcheck_available(), reason="epubcheck is not installed")
def test_long_book_reconstruction_holds_at_scale(large_book: Path):
    import zipfile

    job_id = "perf-quality-large"
    job = Job(
        job_id=job_id,
        source_filename=large_book.name,
        mode=ConversionMode.MAXIMUM_ACCURACY,
        upload_path=str(large_book),
    )
    store.save_job(job)
    try:
        from app.pipeline.orchestrator import _run_pipeline_sync

        _run_pipeline_sync(job)
        finished = store.get_job(job_id)
        assert finished is not None and finished.stage == JobStage.COMPLETED
        report = finished.quality_report
        assert report is not None

        with zipfile.ZipFile(finished.epub_path) as zf:
            body = "\n".join(
                zf.read(n).decode("utf-8")
                for n in zf.namelist()
                if n.endswith(".xhtml")
            )

        # Every hyphenated line break has a lowercase continuation, so all of
        # them are safe to rejoin. One left behind is a word split in half in
        # the middle of the reader's page.
        assert "morn-" not in body, "line-end hyphenation survived into the EPUB"
        assert "morning" in body, "the rejoined word is missing entirely"

        # Alternating running heads must not become body text.
        assert "A. Novelist" not in body, "the verso running head leaked into the text"
        assert "The Long Book" not in body, "the recto running head leaked into the text"

        # A 520-page novel is not one paragraph, nor one per line.
        assert report.paragraph_count > LARGE_BOOK_PAGES, (
            f"only {report.paragraph_count} paragraphs in {LARGE_BOOK_PAGES} pages"
        )
        assert report.chapter_count >= 10, f"only {report.chapter_count} chapters"
        assert report.ocr_page_count == 0, "a native-text book paid for OCR"
        assert report.epubcheck_passed
        assert report.ai_provider_used == "none"
    finally:
        store.delete_job(job_id)
