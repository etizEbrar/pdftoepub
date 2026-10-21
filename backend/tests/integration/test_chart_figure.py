"""A chart drawn in vectors is kept as one figure, its numbers inside it.

Found by the corpus audit on a Turkish engineering article: a Word bar chart
came out as its axis values in a column of paragraphs -- "14", "12", "10" --
because the walk up from its caption stopped at the first label read as a
footnote, and the axis title read as a heading.
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

_XHTML = {"x": "http://www.w3.org/1999/xhtml"}
ABOVE = "sonuçları Şekil 4’de verilmiştir."


def _article(path):
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    css = "p{font-size:12pt;text-align:justify;margin:0 0 6pt 0}"
    body = " ".join(["Kiriş numuneler için üç nokta eğilme deneyi uygulanmış ve sonuçlar ölçülmüştür."] * 4)
    page.insert_htmlbox(fitz.Rect(71, 70, 527, 300), f"<p>{body} Eğilme dayanımı {ABOVE}</p>", css=css)
    # The chart: a frame, axes, bars, and its labels as text.
    page.draw_rect(fitz.Rect(116, 340, 478, 592), color=(0.8, 0.8, 0.8), width=0.5)
    page.draw_line(fitz.Point(166, 367), fitz.Point(166, 549), color=(0, 0, 0), width=0.7)
    page.draw_line(fitz.Point(166, 549), fitz.Point(436, 549), color=(0, 0, 0), width=0.7)
    for i, height in enumerate((120, 130, 140, 150)):
        x = 185 + i * 62
        page.draw_rect(fitz.Rect(x, 549 - height, x + 20, 549), color=None, fill=(0.3, 0.5, 0.8))
        page.draw_rect(fitz.Rect(x + 20, 549 - height - 15, x + 40, 549), color=None, fill=(0.9, 0.5, 0.2))
    for i, label in enumerate(("14", "12", "10", "8", "6", "4", "2", "0")):
        page.insert_text(fitz.Point(146, 380 + i * 24), label, fontsize=10)
    for i, label in enumerate(("0", "0.5", "1", "1.5")):
        page.insert_text(fitz.Point(197 + i * 62, 566), label, fontsize=10)
    page.insert_text(fitz.Point(263, 582), "Lif katki orani (%)", fontsize=9)
    page.insert_text(fitz.Point(455, 460), "NU", fontsize=9)
    page.insert_text(fitz.Point(455, 478), "N", fontsize=9)
    page.insert_htmlbox(
        fitz.Rect(150, 598, 470, 616),
        "<p style='font-size:11pt;text-align:center;margin:0'><b>Şekil 4.</b> Eğilme dayanımı test sonuçları</p>",
    )
    page.insert_htmlbox(fitz.Rect(71, 640, 527, 790), f"<p>{body}</p>", css=css)
    doc.save(str(path))
    return path


def test_a_vector_chart_is_one_figure_and_its_numbers_are_not_text(tmp_path):
    upload = tmp_path / "upload.pdf"
    shutil.copy(_article(tmp_path / "article.pdf"), upload)
    job = Job(job_id="test-chart", source_filename="article.pdf", mode=ConversionMode.MAXIMUM_ACCURACY, upload_path=str(upload))
    store.save_job(job)
    try:
        _run_pipeline_sync(job)
        assert job.stage == JobStage.COMPLETED, f"{job.error_code}: {job.error_message}"
        with zipfile.ZipFile(job.epub_path) as epub:
            roots = [etree.fromstring(epub.read(n)) for n in epub.namelist() if n.startswith("OEBPS/text/")]
    finally:
        store.delete_job(job.job_id)

    def texts(xpath):
        return [" ".join("".join(e.itertext()).split()) for r in roots for e in r.xpath(xpath, namespaces=_XHTML)]

    captions = texts("//x:figcaption")
    assert captions == ["Şekil 4. Eğilme dayanımı test sonuçları"]
    paragraphs = texts("//x:p | //x:li | //x:blockquote | //x:h1 | //x:h2 | //x:h3 | //x:aside")
    for label in ("14", "12", "0.5", "1.5", "NU", "Lif katki orani (%)"):
        assert label not in paragraphs, f"chart label {label!r} came out as text"
    # The text above the chart stays text: it is not cut into the picture.
    assert any(p.endswith(ABOVE) for p in paragraphs)
