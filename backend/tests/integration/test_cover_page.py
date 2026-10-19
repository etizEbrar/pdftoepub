"""A cover is kept whole: the first page, as it prints, is the book's cover.

Reported by a reader converting a free 62-page ebook: its cover -- two people,
with the title set over the artwork -- came out as a close crop of one of
them, and the title as a line of text above it.
"""

from __future__ import annotations

import shutil
import zipfile

import fitz
import pytest
from lxml import etree

from app.jobs import store
from app.models.job import ConversionMode, Job, JobStage
from app.pipeline.orchestrator import _run_pipeline_sync
from app.pipeline.validate import epubcheck_available

pytestmark = pytest.mark.skipif(
    not epubcheck_available(), reason="epubcheck is not installed on this machine"
)

TITLE = "The Garden Path"
_XHTML = {"x": "http://www.w3.org/1999/xhtml"}


def _ebook(path):
    doc = fitz.open()
    cover = doc.new_page(width=432, height=648)
    art = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 432, 648), False)
    art.clear_with(235)
    art.set_rect(fitz.IRect(60, 260, 190, 600), (150, 40, 40))  # one person
    art.set_rect(fitz.IRect(240, 240, 370, 600), (40, 60, 150))  # the other
    cover.insert_image(cover.rect, pixmap=art)
    cover.insert_htmlbox(
        fitz.Rect(40, 60, 392, 160), f"<p style='font-size:34pt;text-align:center;margin:0'>{TITLE}</p>"
    )
    body = " ".join(["The path ran down through the garden to the river, and nobody walked it any more."] * 8)
    for _ in range(3):
        page = doc.new_page(width=432, height=648)
        page.insert_htmlbox(fitz.Rect(54, 72, 378, 580), f"<p style='font-size:11pt'>{body}</p>")
    doc.save(str(path))
    return path


@pytest.fixture(scope="module")
def converted(tmp_path_factory):
    root = tmp_path_factory.mktemp("cover")
    upload = root / "upload.pdf"
    shutil.copy(_ebook(root / "ebook.pdf"), upload)
    job = Job(
        job_id="test-cover-page",
        source_filename="ebook.pdf",
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


def test_the_whole_first_page_is_the_cover(converted):
    _, files = converted
    pictures = [name for name in files if name.startswith("OEBPS/images/")]
    assert len(pictures) == 1, pictures
    opf = files["OEBPS/content.opf"].decode()
    assert 'properties="cover-image"' in opf
    cover = fitz.Pixmap(files[pictures[0]])
    # The page's own proportions, not a crop of one figure on it.
    assert abs(cover.width / cover.height - 432 / 648) < 0.01


def test_the_covers_title_is_not_read_out_as_text(converted):
    _, files = converted
    texts = []
    for name, data in files.items():
        if name.startswith("OEBPS/text/"):
            root = etree.fromstring(data)
            texts += [" ".join("".join(el.itertext()).split()) for el in root.xpath("//x:p | //x:h1 | //x:h2 | //x:h3", namespaces=_XHTML)]
    assert TITLE not in texts


def test_the_book_is_still_named_by_its_cover(converted):
    job, files = converted
    opf = etree.fromstring(files["OEBPS/content.opf"])
    assert opf.findtext(".//dc:title", namespaces={"dc": "http://purl.org/dc/elements/1.1/"}) == TITLE
    assert job.quality_report.epubcheck_passed is True
