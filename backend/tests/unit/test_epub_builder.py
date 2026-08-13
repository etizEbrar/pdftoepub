from pathlib import Path

from app.models.document import BlockRole, DocumentModel, PDFAnalysis, PDFClassification, StructuralNode
from app.pipeline.epub.builder import build_epub, split_into_chapters


def _heading(node_id: str, text: str, level: int) -> StructuralNode:
    return StructuralNode(node_id=node_id, role=BlockRole.HEADING, text=text, level=level, page=1)


def _para(node_id: str, text: str) -> StructuralNode:
    return StructuralNode(node_id=node_id, role=BlockRole.PARAGRAPH, text=text, page=1)


def test_split_into_chapters_uses_level_1_headings_as_boundaries():
    nodes = [
        _para("p0", "Front matter paragraph."),
        _heading("h1", "Chapter One", 1),
        _para("p1", "Body of chapter one."),
        _heading("h2", "A Subheading", 2),
        _para("p2", "More body."),
        _heading("h3", "Chapter Two", 1),
        _para("p3", "Body of chapter two."),
    ]
    chapters = split_into_chapters(nodes)
    assert len(chapters) == 3  # front matter + 2 real chapters
    assert chapters[0].title == "Front Matter"
    assert chapters[1].title == "Chapter One"
    assert chapters[2].title == "Chapter Two"
    assert len({c.filename for c in chapters}) == 3  # all unique filenames


def test_split_into_chapters_single_chapter_when_no_headings():
    nodes = [_para("p0", "Just one long paragraph."), _para("p1", "And another.")]
    chapters = split_into_chapters(nodes)
    assert len(chapters) == 1
    assert len(chapters[0].nodes) == 2


def test_build_epub_produces_valid_zip_with_required_epub_files(tmp_path: Path):
    analysis = PDFAnalysis(
        page_count=1,
        classification=PDFClassification.NATIVE_TEXT,
        has_text_layer=True,
        scanned_page_ratio=0.0,
    )
    document = DocumentModel(source_filename="test.pdf", analysis=analysis)
    document.nodes = [
        _heading("h1", "Chapter One", 1),
        _para("p1", "Some body text for the chapter."),
    ]
    output = tmp_path / "out.epub"
    result = build_epub(document, output, title="Test Book", author="Author", language="en")

    assert output.exists()
    import zipfile

    with zipfile.ZipFile(output) as zf:
        names = zf.namelist()
        assert names[0] == "mimetype"
        assert "META-INF/container.xml" in names
        assert "OEBPS/content.opf" in names
        assert "OEBPS/nav.xhtml" in names
        # mimetype must be the first entry and stored uncompressed
        info = zf.getinfo("mimetype")
        assert info.compress_type == zipfile.ZIP_STORED
        assert zf.read("mimetype") == b"application/epub+zip"

    assert result.chapter_count == 1
    assert result.heading_count == 1
