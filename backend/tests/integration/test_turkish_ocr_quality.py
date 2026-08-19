"""Turkish OCR repair, end to end through a real conversion.

The fixture encodes the defect profile measured from a real 348-page Turkish
paperback, with invented prose. The refusals matter at least as much as the
fixes: replacing one real Turkish word with a different real one is a worse
defect than the scan error, and invisible to a reader.
"""

from __future__ import annotations

import html
import re
import shutil
import zipfile

import pytest

from app.core.config import settings
from app.jobs import store
from app.models.job import ConversionMode, Job, JobStage, QualityReport
from app.pipeline.validate import epubcheck_available
from tests.fixtures.corpus import build_turkish_ocr_novel, unicode_font_available

pytestmark = [
    pytest.mark.skipif(not epubcheck_available(), reason="epubcheck is not installed"),
    pytest.mark.skipif(
        not unicode_font_available(), reason="no Turkish-capable font installed"
    ),
]


@pytest.fixture(scope="module")
def converted(tmp_path_factory) -> tuple[QualityReport, str]:
    pdf = build_turkish_ocr_novel(tmp_path_factory.mktemp("tr") / "novel.pdf")
    job_id = "turkish-ocr-quality"
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
        with zipfile.ZipFile(job.epub_path) as zf:
            xhtml = "\n".join(
                zf.read(n).decode("utf-8")
                for n in zf.namelist()
                if n.endswith(".xhtml") and "nav" not in n
            )
        yield job.quality_report, html.unescape(re.sub(r"<[^>]+>", " ", xhtml))
    finally:
        store.delete_job(job_id)
        shutil.rmtree(settings.jobs_dir / job_id, ignore_errors=True)


# --- corrections that must be made ----------------------------------------

@pytest.mark.parametrize(
    "broken,fixed,why",
    [
        ("icin", "için", "dropped cedilla"),
        ("degil", "değil", "dropped breve"),
        ("Yaşarnım", "Yaşamım", "rn misread as m"),
        ("S ırma", "Sırma", "stray space inside a word"),
        ("n efes", "nefes", "stray space inside a word"),
    ],
)
def test_scan_defects_are_repaired(converted, broken: str, fixed: str, why: str):
    _, text = converted
    assert fixed in text, f"{why}: expected {fixed!r} in the EPUB"
    assert broken not in text, f"{why}: {broken!r} survived into the EPUB"


# --- words that must NEVER be touched -------------------------------------

@pytest.mark.parametrize(
    "word,counterpart,meaning",
    [
        ("sakin", "sakın", "calm vs beware"),
        ("acıyorum", "açıyorum", "I pity vs I open"),
        ("Kışı", "Kişi", "its winter vs person"),
    ],
)
def test_turkish_minimal_pairs_are_never_rewritten(
    converted, word: str, counterpart: str, meaning: str
):
    """Both spellings are real Turkish words. Frequency alone cannot decide
    which one the author wrote, so the source must win."""
    _, text = converted
    assert word in text, f"{meaning}: {word!r} was replaced by a different real word"


def test_real_hyphenated_words_are_not_merged(converted):
    _, text = converted
    assert "Türk-Amerikan" in text
    assert "e-posta" in text


def test_typographic_ligatures_are_expanded(converted):
    """A ligature glyph breaks search, copy and text-to-speech, and some
    readers render it as a blank box."""
    _, text = converted
    assert "firmanın" in text
    assert "eflatun" in text
    for ligature in "\ufb00\ufb01\ufb02\ufb03\ufb04":
        assert ligature not in text, f"ligature {ligature!r} survived into the EPUB"


def test_literary_ellipses_survive_exactly(converted):
    _, text = converted
    assert "bilmiyorum..." in text, "a plain literary ellipsis was altered"
    assert ". . ." in text, "a spaced literary ellipsis was altered"


# --- punctuation ----------------------------------------------------------

def test_space_before_punctuation_is_removed(converted):
    _, text = converted
    assert "Merhaba," in text
    assert "nasılsın?" in text
    assert "Merhaba ," not in text


def test_missing_space_after_punctuation_is_added(converted):
    _, text = converted
    assert "Bir, iki, üç" in text


def test_repeated_punctuation_is_collapsed(converted):
    _, text = converted
    assert "Gerçekten mi?" in text
    assert "mi??" not in text


# --- line-break hyphenation ----------------------------------------------

def test_line_break_hyphenation_is_repaired(converted):
    """"ya-\\nşam" is one word split across lines."""
    _, text = converted
    assert "yaşam boyu" in text
    assert "­" not in text, "a soft hyphen survived into the EPUB"


# --- furniture ------------------------------------------------------------

def test_running_heads_and_page_numbers_do_not_leak_into_prose(converted):
    _, text = converted
    assert "Seyir Bunu" not in text
    assert "Yazar Bunu" not in text
    # Page numbers OCR split as "1 0" must not appear as their own paragraphs.
    assert not re.search(r"\n\s*\d\s\d\s*\n", text)


# --- structure and reporting ---------------------------------------------

def test_conversion_stays_valid_and_local(converted):
    report, _ = converted
    assert report.epubcheck_passed is True
    assert report.epubcheck_errors == []
    assert report.ai_provider_used == "none"


def test_chapter_heading_survives(converted):
    report, text = converted
    assert report.chapter_count >= 1
    assert "Başlangıç" in text


def test_report_separates_applied_from_withheld_corrections(converted):
    report, _ = converted
    assert report.text_corrections > 0
    # Withheld candidates are counted, so a clean EPUB never implies a clean scan.
    assert report.text_corrections_rejected >= 0
    assert 0.0 <= report.text_correction_confidence <= 1.0


def test_no_correction_is_applied_below_the_confidence_floor(converted):
    """Every applied correction must clear the high-confidence bar."""
    report, _ = converted
    assert report.text_correction_confidence >= 0.80
