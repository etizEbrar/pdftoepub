import shutil
from pathlib import Path

import pytest

from app.core.config import settings
from app.jobs import store
from app.models.job import ConversionMode, Job, JobStage
from app.pipeline.orchestrator import _run_pipeline_sync
from app.pipeline.validate import epubcheck_available

pytestmark = pytest.mark.skipif(not epubcheck_available(), reason="epubcheck is not installed on this machine")


def test_full_pipeline_produces_a_valid_epub_with_no_ai(simple_book_pdf: Path, tmp_path: Path):
    assert settings.ai_provider == "none", "the default config must never require AI for a normal conversion"

    job_id = "test-job-e2e"
    upload_path = tmp_path / "upload.pdf"
    shutil.copy(simple_book_pdf, upload_path)

    job = Job(
        job_id=job_id,
        source_filename="simple_book.pdf",
        mode=ConversionMode.MAXIMUM_ACCURACY,
        upload_path=str(upload_path),
    )
    store.save_job(job)
    try:
        _run_pipeline_sync(job)

        assert job.stage == JobStage.COMPLETED, f"pipeline failed: {job.error_code} {job.error_message}"
        assert job.quality_report is not None
        assert job.quality_report.ai_provider_used == "none"
        assert job.quality_report.epubcheck_passed is True
        assert job.quality_report.epubcheck_errors == []
        assert job.quality_report.chapter_count >= 2  # title page + at least one real chapter
        assert job.quality_report.heading_count >= 2
        assert job.quality_report.footnote_count >= 1
        assert job.quality_report.content_integrity_ratio > 0.85

        assert job.epub_path is not None
        epub_path = Path(job.epub_path)
        assert epub_path.exists()
        assert epub_path.stat().st_size > 0
    finally:
        store.delete_job(job_id)
