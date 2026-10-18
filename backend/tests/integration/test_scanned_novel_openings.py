"""A scanned novel reads as a book, not as a transcript of its scanner's OCR.

Each assertion is a defect a real 327-page Turkish novel shipped with: see
tests/fixtures/scanned_novel.py for the layout this exercises.
"""

from __future__ import annotations

import re
import shutil
import zipfile

import pytest
from lxml import etree

from app.jobs import store
from app.models.job import ConversionMode, Job, JobStage
from app.pipeline.orchestrator import _run_pipeline_sync
from app.pipeline.validate import epubcheck_available
from tests.fixtures.scanned_novel import BOOK_TITLE, CHAPTERS, FIRST_WORDS, RUNNING_HEADS, build_scanned_novel

pytestmark = pytest.mark.skipif(
    not epubcheck_available(), reason="epubcheck is not installed on this machine"
)

_XHTML = {"x": "http://www.w3.org/1999/xhtml"}


@pytest.fixture(scope="module")
def converted(tmp_path_factory):
    root = tmp_path_factory.mktemp("scanned_novel")
    upload = root / "upload.pdf"
    shutil.copy(build_scanned_novel(root / "novel.pdf"), upload)
    job = Job(
        job_id="test-scanned-novel",
        source_filename="novel.pdf",
        mode=ConversionMode.MAXIMUM_ACCURACY,
        upload_path=str(upload),
    )
    store.save_job(job)
    _run_pipeline_sync(job)
    assert job.stage == JobStage.COMPLETED, f"{job.error_code}: {job.error_message}"
    with zipfile.ZipFile(job.epub_path) as epub:
        files = {name: epub.read(name) for name in epub.namelist()}
    yield job, files
    store.delete_job(job.job_id)


def _chapters(files):
    return {
        name: etree.fromstring(data)
        for name, data in sorted(files.items())
        if name.startswith("OEBPS/text/")
    }


def _text(element) -> str:
    return " ".join("".join(element.itertext()).split())


def _all(files, xpath: str) -> list:
    return [el for root in _chapters(files).values() for el in root.xpath(xpath, namespaces=_XHTML)]


def test_the_book_is_valid(converted):
    job, _ = converted
    assert job.quality_report.epubcheck_passed is True


def test_the_scan_behind_the_text_is_not_in_the_book(converted):
    _, files = converted
    pictures = [name for name in files if name.startswith("OEBPS/images/")]
    # The cover, and nothing else: no page of the book as a picture of itself.
    assert len(pictures) == 1, pictures
    assert 'properties="cover-image"' in files["OEBPS/content.opf"].decode()


def test_each_chapter_opens_with_its_number_and_its_title_as_printed(converted):
    _, files = converted
    openers = [_text(root.xpath("//x:body/*[1]", namespaces=_XHTML)[0]) for root in _chapters(files).values()]
    h1s = [_text(h) for h in _all(files, "//x:h1")]
    for number, (_, printed) in enumerate(CHAPTERS, start=1):
        assert f"{number} {printed}" in h1s, h1s
        assert f"{number} {printed}" in openers


def test_the_drop_cap_is_part_of_its_word(converted):
    _, files = converted
    paragraphs = [_text(p) for p in _all(files, "//x:p")]
    assert sum(1 for p in paragraphs if p.startswith(FIRST_WORDS)) == len(CHAPTERS)
    assert "O" not in paragraphs


def test_no_ornament_or_page_number_reaches_the_text(converted):
    _, files = converted
    assert not _all(files, "//x:li"), "a decorated page number became a list item"
    texts = [_text(el) for el in _all(files, "//x:p | //x:h1 | //x:h2 | //x:h3 | //x:blockquote")]
    assert "a" not in texts
    assert not any(re.fullmatch(r"[•*.\-\s\d]+", t) for t in texts)


def test_the_running_head_never_reaches_the_text(converted):
    _, files = converted
    body = " ".join(_text(p) for p in _all(files, "//x:p | //x:blockquote"))
    for head in RUNNING_HEADS:
        assert head not in body


def test_the_title_is_the_books(converted):
    _, files = converted
    opf = etree.fromstring(files["OEBPS/content.opf"])
    assert opf.findtext(".//dc:title", namespaces={"dc": "http://purl.org/dc/elements/1.1/"}) == BOOK_TITLE
