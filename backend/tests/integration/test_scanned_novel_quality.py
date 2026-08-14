"""Regression tests for a scanned novel that carries its own OCR text layer.

Every assertion here corresponds to a defect found by converting a real
348-page paperback. The fixture reproduces that book's *structure* with
invented prose — no copyrighted content is stored in the repository.
"""

from __future__ import annotations

import re
import shutil
import zipfile
from pathlib import Path

import pytest

from app.core.config import settings
from app.jobs import store
from app.models.job import ConversionMode, Job, JobStage, QualityReport
from app.pipeline.validate import epubcheck_available
from tests.fixtures.corpus import build_scanned_novel_with_text_layer

pytestmark = pytest.mark.skipif(not epubcheck_available(), reason="epubcheck is not installed")

SOFT_HYPHEN = "­"


@pytest.fixture(scope="module")
def converted(tmp_path_factory) -> tuple[QualityReport, str]:
    pdf = build_scanned_novel_with_text_layer(tmp_path_factory.mktemp("novel") / "novel.pdf")
    job_id = "scanned-novel-quality"
    shutil.rmtree(settings.jobs_dir / job_id, ignore_errors=True)
    job = Job(
        job_id=job_id,
        source_filename="novel.pdf",
        mode=ConversionMode.MAXIMUM_ACCURACY,
        upload_path=str(pdf),
    )
    store.save_job(job)
    try:
        from app.pipeline.orchestrator import _run_pipeline_sync

        _run_pipeline_sync(job)
        assert job.stage == JobStage.COMPLETED, f"{job.error_code}: {job.error_message}"
        assert job.epub_path
        with zipfile.ZipFile(job.epub_path) as zf:
            xhtml = "\n".join(
                zf.read(n).decode("utf-8") for n in zf.namelist() if n.endswith(".xhtml")
            )
        yield job.quality_report, xhtml
    finally:
        store.delete_job(job_id)
        shutil.rmtree(settings.jobs_dir / job_id, ignore_errors=True)


def _plain_text(xhtml: str) -> str:
    import html

    return html.unescape(re.sub(r"<[^>]+>", " ", xhtml))


# --- OCR must not run on a book that already has a text layer -------------

def test_no_ocr_on_a_scanned_book_that_already_has_text(converted):
    report, _ = converted
    assert report.ocr_page_count == 0, (
        "a full-page scan image must not trigger OCR when the text layer is complete"
    )


def test_conversion_is_valid_and_fully_local(converted):
    report, _ = converted
    assert report.epubcheck_passed is True
    assert report.epubcheck_errors == []
    assert report.ai_provider_used == "none"


# --- text quality ---------------------------------------------------------

def test_soft_hyphens_are_repaired_not_left_in_the_text(converted):
    _, xhtml = converted
    assert SOFT_HYPHEN not in xhtml, "soft hyphens must be resolved when lines are joined"
    text = _plain_text(xhtml)
    # The fixture breaks this word across a line with a soft hyphen.
    assert "curtains" in text


def test_running_heads_do_not_leak_into_body_prose(converted):
    _, xhtml = converted
    text = _plain_text(xhtml)
    # Verso/recto alternation means each head appears on only ~half the pages,
    # which a whole-book repetition threshold misses entirely.
    assert "Seyir In the first hours" not in text
    assert "Author Name In the first hours" not in text


def test_split_page_numbers_do_not_become_footnotes(converted):
    report, xhtml = converted
    # "4 1" for page 41 must be recognised as furniture, not a note body.
    assert report.footnote_count <= 4, (
        f"page numbers appear to have been misread as notes ({report.footnote_count})"
    )
    assert "<aside" not in xhtml or 'epub:type="footnote"' in xhtml


# --- structure ------------------------------------------------------------

def test_chapters_are_detected_with_their_numbers(converted):
    report, xhtml = converted
    assert report.chapter_count >= 3, f"expected the three chapters, got {report.chapter_count}"
    text = _plain_text(xhtml)
    for number, title in ((1, "Kurban"), (2, "Ben"), (3, "Bir")):
        assert f"{number}. {title}" in text, f"chapter number not joined to {title!r}"


def test_chapter_headings_are_top_level_and_reachable_from_the_toc(converted):
    report, _ = converted
    assert report.navigation_entry_count >= 3


def test_every_navigation_link_points_at_something_real(converted):
    """No nav entry may reference a missing file or a missing anchor."""
    job_dir = settings.jobs_dir / "scanned-novel-quality"
    epubs = list(job_dir.glob("output/*.epub")) if job_dir.exists() else []
    if not epubs:
        pytest.skip("epub already cleaned up")
    with zipfile.ZipFile(epubs[0]) as zf:
        nav = zf.read("OEBPS/nav.xhtml").decode("utf-8")
        names = set(zf.namelist())
        contents = {n: zf.read(n).decode("utf-8") for n in names if n.endswith(".xhtml")}

    for href in re.findall(r'href="([^"]+)"', nav):
        if href.startswith("http"):
            continue
        path, _, fragment = href.partition("#")
        target = f"OEBPS/{path}" if path else None
        if target:
            assert target in names, f"nav points at missing file {path}"
        if fragment:
            body = contents[target] if target else nav
            assert f'id="{fragment}"' in body, f"nav points at missing anchor #{fragment}"


# --- footnotes ------------------------------------------------------------

def test_welded_footnote_markers_are_recovered_and_linked(converted):
    report, xhtml = converted
    # The fixture welds the marker to the preceding word, as OCR does, and the
    # PDF carries no superscript flag at all.
    assert report.footnotes_linked >= 1, "no welded footnote marker was recovered"
    assert 'epub:type="noteref"' in xhtml
    assert 'epub:type="footnote"' in xhtml


def test_note_bodies_keep_their_text(converted):
    _, xhtml = converted
    assert "The source note appears here" in _plain_text(xhtml)


# --- honest reporting -----------------------------------------------------

def test_report_states_structure_quality_separately_from_validity(converted):
    report, _ = converted
    assert 0.0 <= report.structure_score <= 100.0
    # A valid EPUB is not automatically a good one; the two are reported apart.
    assert isinstance(report.needs_review, bool)
    if report.needs_review:
        assert report.review_reasons, "needs_review must always explain itself"


def test_content_integrity_stays_high(converted):
    report, _ = converted
    assert report.content_integrity_ratio > 0.90
    assert report.word_count_epub > 0
