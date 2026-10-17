"""An edited academic volume reads as a book, not as a transcript of its pages.

Each assertion is a defect a real 168-page Turkish volume shipped with: see
tests/fixtures/edited_volume.py for the layout this exercises.
"""

from __future__ import annotations

import re
import shutil
import zipfile
from pathlib import Path

import fitz
import pytest
from lxml import etree

from app.jobs import store
from app.models.job import ConversionMode, Job, JobStage
from app.pipeline.orchestrator import _run_pipeline_sync
from app.pipeline.validate import epubcheck_available
from tests.fixtures.edited_volume import (
    CHAPTERS,
    LONG_SECTION,
    REFERENCES,
    RUNNING_HEAD,
    TITLE,
    build_edited_volume,
    paragraph_count,
)

pytestmark = pytest.mark.skipif(
    not epubcheck_available(), reason="epubcheck is not installed on this machine"
)

_XHTML = {"x": "http://www.w3.org/1999/xhtml"}


@pytest.fixture(scope="module")
def converted(tmp_path_factory):
    root = tmp_path_factory.mktemp("edited_volume")
    pdf = build_edited_volume(root / "volume.pdf")
    upload = root / "upload.pdf"
    shutil.copy(pdf, upload)
    job = Job(
        job_id="test-edited-volume",
        source_filename="volume.pdf",
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


def _chapters(files: dict[str, bytes]) -> dict[str, etree._Element]:
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


def test_no_paragraph_is_cut_at_a_page_break_or_merged_with_the_next(converted):
    _, files = converted
    paragraphs = [_text(p) for p in _all(files, "//x:p")]
    for number in range(1, paragraph_count() + 1):
        holding = [p for p in paragraphs if re.search(rf"\balfa{number}\b", p)]
        assert len(holding) == 1, f"paragraph {number} starts in {len(holding)} places"
        assert re.search(rf"\bomega{number}\.$", holding[0]), (
            f"paragraph {number} does not end where it should: …{holding[0][-80:]}"
        )


def test_running_heads_never_reach_the_text(converted):
    _, files = converted
    body = " ".join(_text(p) for p in _all(files, "//x:p | //x:li | //x:h1 | //x:h2 | //x:h3"))
    assert RUNNING_HEAD not in body


def test_section_headings_are_headings_inside_their_chapter(converted):
    _, files = converted
    headings = [_text(h) for h in _all(files, "//x:h2 | //x:h3 | //x:h4")]
    assert "GİRİŞ" in headings
    assert LONG_SECTION in headings, "a numbered heading past 40 characters was read as prose"
    paragraphs = [_text(p) for p in _all(files, "//x:p")]
    assert not any(p.startswith(("GİRİŞ", "KAYNAKÇA", "SONUÇ")) for p in paragraphs)
    # An introduction is a section of its chapter, never a chapter of its own.
    titles = [_text(root.find(".//x:title", _XHTML)) for root in _chapters(files).values()]
    assert "GİRİŞ" not in titles and "KAYNAKÇA" not in titles
    for division, title, _ in CHAPTERS:
        assert f"{division} {title}" in titles


def test_each_reference_is_its_own_entry(converted):
    _, files = converted
    entries = [_text(p) for p in _all(files, "//x:p[@class='bib-entry']")]
    assert len(entries) == len(REFERENCES) * len(CHAPTERS)
    for reference in REFERENCES:
        assert entries.count(" ".join(reference.split())) == len(CHAPTERS)


def test_printed_contents_link_to_chapters_without_leader_dots(converted):
    _, files = converted
    entries = _all(files, "//x:p[@class='toc-entry']")
    assert entries
    assert not any(re.search(r"\.{4,}|…", _text(e)) for e in entries)
    linked = {_text(a) for e in entries for a in e.xpath(".//x:a", namespaces=_XHTML)}
    for division, title, _ in CHAPTERS:
        assert f"{division} {title}" in linked


def test_stacked_author_notes_are_separate_and_linked(converted):
    _, files = converted
    notes = _all(files, "//x:aside")
    texts = [_text(n) for n in notes]
    assert len(notes) == 2, texts
    assert texts[0].startswith("1 Örnek Üniversitesi, Mühendislik")
    assert texts[1].startswith("2 Örnek Üniversitesi, Fen")


def test_title_and_language_come_from_the_book_not_stale_metadata(converted):
    job, files = converted
    opf = etree.fromstring(files["OEBPS/content.opf"])
    ns = {"dc": "http://purl.org/dc/elements/1.1/"}
    assert opf.findtext(".//dc:title", namespaces=ns) == TITLE
    assert opf.findtext(".//dc:language", namespaces=ns) == "tr"
    assert Path(job.epub_path).name == "muhendislikte-yeni-yaklasimlar.epub"


def _flowchart_pdf(path: Path) -> Path:
    doc = fitz.open()
    page = doc.new_page(width=396, height=612)
    css = "p{font-size:11pt;text-align:justify;text-indent:28pt;margin:0 0 3pt 0}"
    body = " ".join(["Motor arızalarının tespitinde kullanılan izleme şeması aşağıda verilmiştir."] * 5)
    page.insert_htmlbox(fitz.Rect(51, 60, 345, 200), f"<p>{body}</p>", css=css)
    labels = ("Örnekleyici", "Notch Filtresi", "Teşhis")
    for index, label in enumerate(labels):
        top = 230 + index * 60
        box = fitz.Rect(130, top, 270, top + 34)
        page.draw_rect(box, color=(0, 0, 0), width=0.8)
        page.insert_htmlbox(box + (6, 9, -6, -4), f'<p style="font-size:10pt;text-align:center">{label}</p>')
        if index:
            page.draw_line(fitz.Point(200, top - 26), fitz.Point(200, top), color=(0, 0, 0), width=0.8)
    page.insert_htmlbox(
        fitz.Rect(51, 420, 345, 440),
        '<p style="font-size:10pt;text-align:center"><b>Şekil 1:</b> İzleme şeması</p>',
    )
    page.insert_htmlbox(fitz.Rect(51, 450, 345, 560), f"<p>{body}</p>", css=css)
    doc.save(str(path))
    return path


def test_a_diagram_built_from_boxes_and_labels_is_kept_as_one_figure(tmp_path):
    upload = _flowchart_pdf(tmp_path / "flow.pdf")
    job = Job(
        job_id="test-flowchart",
        source_filename="flow.pdf",
        mode=ConversionMode.MAXIMUM_ACCURACY,
        upload_path=str(upload),
    )
    store.save_job(job)
    try:
        _run_pipeline_sync(job)
        assert job.stage == JobStage.COMPLETED, f"{job.error_code}: {job.error_message}"
        with zipfile.ZipFile(job.epub_path) as epub:
            files = {name: epub.read(name) for name in epub.namelist()}
        figures = _all(files, "//x:figure")
        assert len(figures) == 1
        assert _text(figures[0].find(".//x:figcaption", _XHTML)) == "Şekil 1: İzleme şeması"
        paragraphs = " ".join(_text(p) for p in _all(files, "//x:p"))
        for label in ("Örnekleyici", "Notch Filtresi", "Teşhis"):
            assert label not in paragraphs, f"diagram label {label!r} came out as text"
    finally:
        store.delete_job(job.job_id)
