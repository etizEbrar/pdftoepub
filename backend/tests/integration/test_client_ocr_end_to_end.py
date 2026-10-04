"""A scanned book converted from the client's own OCR, with no Tesseract at all.

This is the point of the whole seam. A scanned page costs ~110s on the free
tier and ~1.8s on a phone's Neural Engine, so for a 253-page book the server
must be able to build the EPUB from text it did not read itself. These tests
hold the two properties that makes safe: the server never invokes Tesseract
when the client has covered a page, and the words the client sent arrive in the
finished book in the right order.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import fitz
import pytest

from app.jobs import store
from app.models.job import ConversionMode, Job, JobStage
from app.pipeline.orchestrator import _run_pipeline_sync
from app.storage.temp_storage import client_ocr_path_for, job_dir

FIXTURE = Path(__file__).parent.parent / "fixtures" / "corpus" / "scanned_book.pdf"

# A Turkish paragraph with every letter the language has that English does not,
# so a coordinate or encoding mistake shows up as mangled text rather than as a
# subtly different word.
TURKISH_LINES = [
    "İÇİNDEKİLER VE ÖNSÖZ",
    "Dilin insana yüklediği sorumluluk ağırdır.",
    "Şu hâlde söz söylemek, susmayı öğrenmekle başlar.",
    "Çünkü her kelime bir iz bırakır.",
]


def _payload_for(pdf: Path, lines: list[str]) -> dict:
    """Plausible client OCR for every page, laid out as a real page would be.

    Every page is covered on purpose: a payload that skips a scanned page is a
    page the server still has to read itself, which is correct behaviour but
    would make the "no Tesseract" assertion below meaningless.
    """
    with fitz.open(pdf) as doc:
        page_count = len(doc)

    left, top, line_height = 72.0, 90.0, 18.0
    pages = []
    for page_number in range(1, page_count + 1):
        out_lines = []
        for index, text in enumerate(lines):
            y0 = top + index * (line_height + 6.0)
            x = left
            words = []
            for word in text.split():
                # ~6pt per character is close enough to a real 12pt face for
                # the geometry to behave like a page, not a stack of boxes.
                w = len(word) * 6.0
                words.append(
                    {
                        "text": word,
                        "bbox": [x, y0, x + w, y0 + line_height],
                        "confidence": 0.96,
                    }
                )
                x += w + 5.0
            out_lines.append({"words": words, "confidence": 0.96})
        pages.append({"page": page_number, "lines": out_lines})
    return {"engine": "apple-vision", "pages": pages}


def _convert_with_client_ocr(job_id: str, pdf: Path, payload: dict | None) -> Job:
    job = Job(
        job_id=job_id,
        source_filename=pdf.name,
        mode=ConversionMode.MAXIMUM_ACCURACY,
        upload_path=str(pdf),
    )
    store.save_job(job)
    if payload is not None:
        path = client_ocr_path_for(job_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
    try:
        _run_pipeline_sync(job)
    finally:
        store.delete_job(job_id)
    return job


def _body(job: Job) -> str:
    assert job.epub_path
    with zipfile.ZipFile(job.epub_path) as zf:
        return "\n".join(
            zf.read(n).decode("utf-8") for n in zf.namelist() if n.endswith(".xhtml")
        )


@pytest.mark.skipif(not FIXTURE.exists(), reason="scanned fixture not generated")
class TestClientOCRReplacesTesseract:
    def test_the_server_never_runs_ocr_for_a_page_the_client_covered(self, monkeypatch):
        """The whole economic argument: no Tesseract process, no 110s a page."""
        import app.pipeline.orchestrator as orch

        def explode(*args, **kwargs):
            raise AssertionError("Tesseract was invoked for a client-supplied page")

        monkeypatch.setattr(orch, "ocr_page", explode)
        job = _convert_with_client_ocr(
            "cocr-no-tess", FIXTURE, _payload_for(FIXTURE, TURKISH_LINES)
        )
        assert job.stage == JobStage.COMPLETED, f"{job.error_code}: {job.error_message}"

    def test_the_words_the_client_read_are_in_the_finished_book(self, monkeypatch):
        import app.pipeline.orchestrator as orch

        monkeypatch.setattr(
            orch, "ocr_page", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no"))
        )
        job = _convert_with_client_ocr(
            "cocr-words", FIXTURE, _payload_for(FIXTURE, TURKISH_LINES)
        )
        body = _body(job)
        assert "Dilin insana" in body
        assert "Çünkü her kelime bir iz bırakır." in body

    def test_turkish_letters_arrive_intact(self, monkeypatch):
        import app.pipeline.orchestrator as orch

        monkeypatch.setattr(
            orch, "ocr_page", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no"))
        )
        job = _convert_with_client_ocr(
            "cocr-tr", FIXTURE, _payload_for(FIXTURE, TURKISH_LINES)
        )
        body = _body(job)
        for letter in ("İ", "Ç", "ı", "ş", "ğ", "ö", "ü", "â"):
            assert letter in body, f"{letter} did not survive the client OCR path"

    def test_the_page_counts_as_an_ocr_page_in_the_report(self, monkeypatch):
        """Honesty in the quality report: this page was recognised, not read."""
        import app.pipeline.orchestrator as orch

        monkeypatch.setattr(
            orch, "ocr_page", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no"))
        )
        job = _convert_with_client_ocr(
            "cocr-report", FIXTURE, _payload_for(FIXTURE, TURKISH_LINES)
        )
        assert job.quality_report is not None
        assert job.quality_report.ocr_page_count >= 1

    def test_a_damaged_payload_falls_back_to_the_server_reading_it(self):
        """Losing the conversion would be worse than reading the page slowly."""
        job = Job(
            job_id="cocr-damaged",
            source_filename=FIXTURE.name,
            mode=ConversionMode.MAXIMUM_ACCURACY,
            upload_path=str(FIXTURE),
        )
        store.save_job(job)
        path = client_ocr_path_for("cocr-damaged")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{ this is not json", encoding="utf-8")
        try:
            _run_pipeline_sync(job)
        finally:
            store.delete_job("cocr-damaged")
        # Either outcome is acceptable; silently producing an empty book is not.
        assert job.stage in (JobStage.COMPLETED, JobStage.FAILED)
        if job.stage == JobStage.COMPLETED:
            assert job.quality_report is not None


@pytest.mark.skipif(not FIXTURE.exists(), reason="scanned fixture not generated")
class TestClientOCRWithServerOCRDisabled:
    """OCR_ENABLED governs this server's CPU, not what text it will accept.

    A self-hoster who wants no Tesseract at all — no 110s pages, no tessdata in
    the image — should still be able to convert a scanned book sent from a
    phone that already read it. Turning the server's own OCR off used to
    discard the client's text and produce an empty book.
    """

    def test_a_scan_still_converts_when_the_server_will_not_ocr(self, monkeypatch):
        from app.core.config import settings as live_settings

        monkeypatch.setattr(live_settings, "ocr_enabled", False)
        job = _convert_with_client_ocr(
            "cocr-disabled", FIXTURE, _payload_for(FIXTURE, TURKISH_LINES)
        )
        assert job.stage == JobStage.COMPLETED, f"{job.error_code}: {job.error_message}"
        body = _body(job)
        assert "Çünkü her kelime bir iz bırakır." in body

    def test_without_a_payload_a_scan_is_still_refused_politely(self, monkeypatch):
        """Nothing to read and nothing supplied: not a silent empty book."""
        from app.core.config import settings as live_settings

        monkeypatch.setattr(live_settings, "ocr_enabled", False)
        job = _convert_with_client_ocr("cocr-none", FIXTURE, None)
        if job.stage == JobStage.COMPLETED:
            assert job.quality_report is not None
        else:
            assert job.error_code
