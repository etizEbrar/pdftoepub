from pathlib import Path

import pytest

from app.core.errors import ConversionError
from app.jobs import store
from app.models.job import ConversionMode, Job, JobStage
from app.pipeline.orchestrator import _run_pipeline_sync
from tests.fixtures.make_test_pdf import build_corrupted_pdf, build_encrypted_pdf, build_scanned_pdf


def _run_job(job_id: str, pdf_path: Path) -> Job:
    job = Job(
        job_id=job_id,
        source_filename=pdf_path.name,
        mode=ConversionMode.MAXIMUM_ACCURACY,
        upload_path=str(pdf_path),
    )
    store.save_job(job)
    try:
        _run_pipeline_sync(job)
    finally:
        store.delete_job(job_id)
    return job


def test_encrypted_pdf_fails_cleanly_without_modifying_anything(tmp_path: Path):
    pdf_path = build_encrypted_pdf(tmp_path / "encrypted.pdf")
    job = _run_job("test-encrypted", pdf_path)
    assert job.stage == JobStage.FAILED
    assert job.error_code == "encrypted_pdf"
    assert pdf_path.exists()  # original PDF untouched


def test_corrupted_pdf_fails_cleanly(tmp_path: Path):
    pdf_path = build_corrupted_pdf(tmp_path / "corrupted.pdf")
    job = _run_job("test-corrupted", pdf_path)
    assert job.stage == JobStage.FAILED
    assert job.error_code in ("corrupted_pdf", "unsupported_pdf")


def test_scanned_pdf_is_declined_not_silently_converted(tmp_path: Path):
    pdf_path = build_scanned_pdf(tmp_path / "scanned.pdf")
    job = _run_job("test-scanned", pdf_path)
    assert job.stage == JobStage.FAILED
    assert job.error_code == "unsupported_complexity"
    # never a silently-empty "success"
    assert job.quality_report is None


def test_conversion_errors_carry_a_stable_code_and_safe_message():
    # every ConversionError subclass must define both, so the iOS app can
    # switch on `code` for illustration/copy without parsing prose.
    for cls in ConversionError.__subclasses__():
        instance = cls()
        assert instance.code
        assert instance.user_message
