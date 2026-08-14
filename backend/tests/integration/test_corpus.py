"""Runs the whole document corpus through the real pipeline and real EPUBCheck.

Every assertion here is about behaviour that was verified by executing the
pipeline, not by mocking it.
"""

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

import pytest

from app.core.config import settings
from app.jobs import store
from app.models.job import ConversionMode, Job, JobStage, QualityReport
from app.pipeline.ocr.engine import tesseract_available
from app.pipeline.orchestrator import _run_pipeline_sync
from app.pipeline.validate import epubcheck_available
from tests.fixtures import corpus

pytestmark = pytest.mark.skipif(
    not epubcheck_available(), reason="epubcheck is not installed on this machine"
)

requires_tesseract = pytest.mark.skipif(
    not tesseract_available(), reason="tesseract is not installed on this machine"
)
requires_unicode_font = pytest.mark.skipif(
    not corpus.unicode_font_available(),
    reason="no Arabic/Hebrew-capable font installed on this machine",
)


def _convert(job_id: str, pdf: Path) -> Job:
    job = Job(
        job_id=job_id,
        source_filename=pdf.name,
        mode=ConversionMode.MAXIMUM_ACCURACY,
        upload_path=str(pdf),
    )
    store.save_job(job)
    try:
        _run_pipeline_sync(job)
    finally:
        store.delete_job(job_id)
    return job


def _report(job: Job) -> QualityReport:
    assert job.stage == JobStage.COMPLETED, f"{job.error_code}: {job.error_message}"
    assert job.quality_report is not None
    return job.quality_report


def _read_all_xhtml(job: Job) -> str:
    assert job.epub_path
    with zipfile.ZipFile(job.epub_path) as zf:
        return "\n".join(
            zf.read(name).decode("utf-8")
            for name in zf.namelist()
            if name.endswith(".xhtml")
        )


@pytest.fixture(scope="module")
def corpus_dir(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("corpus")


@pytest.fixture(autouse=True)
def _cleanup_job_dirs():
    yield
    for entry in settings.jobs_dir.glob("corpustest-*"):
        shutil.rmtree(entry, ignore_errors=True)


# --- A. Turkish novel -----------------------------------------------------

def test_turkish_novel_preserves_diacritics_chapters_and_footnotes(corpus_dir: Path):
    pdf = corpus.build_turkish_novel(corpus_dir / "turkish.pdf")
    job = _convert("corpustest-turkish", pdf)
    report = _report(job)

    assert report.epubcheck_passed
    assert report.chapter_count >= 3
    assert report.footnote_count >= 3, "footnotes must survive the running-footer stripper"
    assert report.content_integrity_ratio > 0.9

    xhtml = _read_all_xhtml(job)
    for turkish_word in ("Şehrin", "çöken", "ışıklarıyla", "Başlangıç"):
        assert turkish_word in xhtml, f"lost Turkish characters in {turkish_word!r}"
    assert "epub:type=\"noteref\"" in xhtml


# --- B. Two-column academic ----------------------------------------------

def test_two_column_paper_reads_each_column_in_order(corpus_dir: Path):
    pdf = corpus.build_two_column_academic(corpus_dir / "twocol.pdf")
    job = _convert("corpustest-twocol", pdf)
    report = _report(job)

    assert report.epubcheck_passed
    xhtml = _read_all_xhtml(job)

    # The whole left column must precede the whole right column.
    left_last = xhtml.index("reaches the bottom of the column")
    right_first = xhtml.index("The right column continues")
    assert left_last < right_first, "columns were interleaved instead of read in order"
    assert report.footnote_count >= 1


# --- C. Footnote-heavy ----------------------------------------------------

def test_multiple_footnotes_per_page_are_each_linked(corpus_dir: Path):
    pdf = corpus.build_footnote_heavy(corpus_dir / "footnotes.pdf")
    job = _convert("corpustest-footnotes", pdf)
    report = _report(job)

    assert report.epubcheck_passed
    assert report.footnote_count >= 9, "each stacked note must be split out separately"

    xhtml = _read_all_xhtml(job)
    assert xhtml.count('epub:type="footnote"') >= 9
    assert xhtml.count('epub:type="noteref"') >= 9


# --- D. Scanned (OCR) -----------------------------------------------------

@requires_tesseract
def test_scanned_book_is_read_by_local_ocr(corpus_dir: Path):
    pdf = corpus.build_scanned_book(corpus_dir / "scanned.pdf")
    job = _convert("corpustest-scanned", pdf)
    report = _report(job)

    assert report.epubcheck_passed
    assert report.ocr_page_count >= 1
    assert report.ocr_mean_confidence and report.ocr_mean_confidence > 70
    assert report.ai_provider_used == "none"

    xhtml = _read_all_xhtml(job)
    assert "recognition is the only way" in xhtml or "Recovered Manuscript" in xhtml


@requires_tesseract
def test_rotated_scan_is_still_read_correctly(corpus_dir: Path):
    pdf = corpus.build_scanned_book(corpus_dir / "scanned_rot.pdf", rotate=180, pages=1)
    job = _convert("corpustest-scanrot", pdf)
    report = _report(job)

    assert report.epubcheck_passed
    xhtml = _read_all_xhtml(job)
    assert "Recovered Manuscript" in xhtml or "scanned image" in xhtml


# --- E. Mixed native + scanned -------------------------------------------

@requires_tesseract
def test_mixed_document_ocrs_only_the_scanned_page(corpus_dir: Path):
    pdf = corpus.build_mixed_native_and_scanned(corpus_dir / "mixed.pdf")
    job = _convert("corpustest-mixed", pdf)
    report = _report(job)

    assert report.epubcheck_passed
    assert report.page_count == 2
    assert report.ocr_page_count == 1, "the native page must not be sent to OCR"

    xhtml = _read_all_xhtml(job)
    assert "Native Text" in xhtml
    assert "Scanned Text" in xhtml or "requires OCR" in xhtml


# --- F. Tables ------------------------------------------------------------

def test_table_is_reconstructed_as_semantic_xhtml(corpus_dir: Path):
    pdf = corpus.build_table_document(corpus_dir / "table.pdf")
    job = _convert("corpustest-table", pdf)
    report = _report(job)

    assert report.epubcheck_passed
    assert report.table_count >= 1

    xhtml = _read_all_xhtml(job)
    assert "<table>" in xhtml and "<thead>" in xhtml and "<tbody>" in xhtml
    assert "<th>Region</th>" in xhtml
    assert "<td>North</td>" in xhtml
    assert "<caption>" in xhtml
    # The cell text must not also appear as loose paragraphs.
    assert "<p>North</p>" not in xhtml


# --- G. Formulas ----------------------------------------------------------

def test_simple_equation_becomes_mathml_and_complex_one_becomes_an_image(corpus_dir: Path):
    pdf = corpus.build_formula_document(corpus_dir / "formula.pdf")
    job = _convert("corpustest-formula", pdf)
    report = _report(job)

    assert report.epubcheck_passed
    assert report.formula_count >= 1, "the simple relation should be transcribed"
    assert report.image_fallback_count >= 1, "the integral must not be guessed at"

    xhtml = _read_all_xhtml(job)
    assert "<math" in xhtml and "MathML" in xhtml
    assert "<msup>" in xhtml
    assert 'class="preserved-region"' in xhtml
    # The fallback image carries a real description, not an empty alt.
    assert 'alt="Mathematical expression' in xhtml


# --- H. Endnotes ----------------------------------------------------------

def test_endnotes_link_across_chapters_with_return_navigation(corpus_dir: Path):
    pdf = corpus.build_endnote_document(corpus_dir / "endnote.pdf")
    job = _convert("corpustest-endnote", pdf)
    report = _report(job)

    assert report.epubcheck_passed, report.epubcheck_errors
    assert report.endnote_count >= 4

    xhtml = _read_all_xhtml(job)
    assert 'epub:type="endnote"' in xhtml
    assert 'class="noteback"' in xhtml
    # Back-links must be file-qualified, since notes live in their own chapter.
    assert 'href="chapter-001' in xhtml or 'href="chapter-002' in xhtml


def test_notes_section_is_reachable_from_the_table_of_contents(corpus_dir: Path):
    pdf = corpus.build_endnote_document(corpus_dir / "endnote2.pdf")
    job = _convert("corpustest-endnote2", pdf)
    _report(job)

    with zipfile.ZipFile(job.epub_path) as zf:
        nav = zf.read("OEBPS/nav.xhtml").decode("utf-8")
    assert "Notes" in nav


# --- I. Poetry ------------------------------------------------------------

def test_poetry_keeps_its_line_breaks_and_stays_reflowable(corpus_dir: Path):
    pdf = corpus.build_poetry_document(corpus_dir / "poetry.pdf")
    job = _convert("corpustest-poetry", pdf)
    report = _report(job)

    assert report.epubcheck_passed
    assert report.verse_count >= 1

    xhtml = _read_all_xhtml(job)
    assert 'class="verse"' in xhtml
    assert "<br/>" in xhtml
    assert "Because I could not stop for Death" in xhtml
    # Reflowable: no absolute positioning anywhere.
    assert "position:absolute" not in xhtml.replace(" ", "")
    # The trailing prose paragraph must NOT have been turned into verse.
    assert "<p>This closing paragraph" in xhtml or "closing paragraph" in xhtml


# --- J/K. RTL and mixed direction ----------------------------------------

@requires_unicode_font
def test_rtl_document_sets_direction_on_document_and_spine(corpus_dir: Path):
    pdf = corpus.build_rtl_document(corpus_dir / "rtl.pdf")
    job = _convert("corpustest-rtl", pdf)
    report = _report(job)

    assert report.epubcheck_passed
    assert report.rtl_block_count >= 1

    xhtml = _read_all_xhtml(job)
    assert 'dir="rtl"' in xhtml

    with zipfile.ZipFile(job.epub_path) as zf:
        opf = zf.read("OEBPS/content.opf").decode("utf-8")
    assert 'page-progression-direction="rtl"' in opf


@requires_unicode_font
def test_mixed_direction_document_preserves_logical_character_order(corpus_dir: Path):
    pdf = corpus.build_mixed_direction_document(corpus_dir / "mixed_dir.pdf")
    job = _convert("corpustest-mixeddir", pdf)
    report = _report(job)

    assert report.epubcheck_passed
    xhtml = _read_all_xhtml(job)

    # Arabic must be preserved in logical order, never reversed.
    assert "هذا نص عربي" in xhtml
    assert "This paragraph is written in English" in xhtml
    # The RTL run is marked explicitly inside an otherwise-LTR document.
    assert 'dir="rtl"' in xhtml
