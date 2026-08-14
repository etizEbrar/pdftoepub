from app.models.document import (
    Block,
    BlockRole,
    DocumentModel,
    PDFAnalysis,
    PDFClassification,
    StructuralNode,
)
from app.pipeline.integrity import compute_integrity


def _document(blocks: list[Block], nodes: list[StructuralNode]) -> DocumentModel:
    doc = DocumentModel(
        source_filename="test.pdf",
        analysis=PDFAnalysis(
            page_count=1,
            classification=PDFClassification.NATIVE_TEXT,
            has_text_layer=True,
            scanned_page_ratio=0.0,
        ),
    )
    doc.blocks = blocks
    doc.nodes = nodes
    return doc


def _block(block_id: str, text: str, source: str = "native") -> Block:
    return Block(
        block_id=block_id,
        page=1,
        page_width=612,
        page_height=792,
        bbox=(0, 0, 100, 20),
        kind="text",
        text=text,
        source=source,
    )


def _node(node_id: str, role: BlockRole, text: str, blocks: list[str]) -> StructuralNode:
    return StructuralNode(node_id=node_id, role=role, text=text, source_block_ids=blocks)


def test_clean_conversion_reports_full_integrity():
    blocks = [_block("b1", "one two three four five")]
    nodes = [_node("n1", BlockRole.PARAGRAPH, "one two three four five", ["b1"])]
    result = compute_integrity(_document(blocks, nodes), epub_word_count=5)

    assert result.ratio == 1.0
    assert result.suspicious is False
    assert result.unaccounted_block_ids == []


def test_page_furniture_removal_does_not_count_as_content_loss():
    blocks = [_block("b1", "real body text here"), _block("b2", "Running Header")]
    nodes = [
        _node("n1", BlockRole.PARAGRAPH, "real body text here", ["b1"]),
        _node("n2", BlockRole.HEADER, "Running Header", ["b2"]),
    ]
    result = compute_integrity(_document(blocks, nodes), epub_word_count=4)

    assert result.ratio == 1.0
    assert result.furniture_word_count == 2
    assert result.suspicious is False


def test_content_preserved_as_an_image_is_accounted_for_not_counted_as_loss():
    blocks = [_block("b1", "body text"), _block("b2", "complicated table content here")]
    nodes = [
        _node("n1", BlockRole.PARAGRAPH, "body text", ["b1"]),
        _node("n2", BlockRole.IMAGE_FALLBACK, "", ["b2"]),
    ]
    result = compute_integrity(_document(blocks, nodes), epub_word_count=2)

    assert result.preserved_as_image_word_count == 4
    assert result.ratio == 1.0
    assert result.suspicious is False


def test_a_source_block_that_reaches_nothing_is_flagged_not_ignored():
    """The core guarantee: content must never silently disappear."""
    blocks = [_block("b1", "body text"), _block("b2", "this text vanished entirely")]
    nodes = [_node("n1", BlockRole.PARAGRAPH, "body text", ["b1"])]
    result = compute_integrity(_document(blocks, nodes), epub_word_count=2)

    assert "b2" in result.unaccounted_block_ids
    assert result.suspicious is True
    assert any("did not reach the EPUB" in note for note in result.notes)


def test_large_word_loss_is_flagged_even_when_every_block_is_accounted_for():
    blocks = [_block("b1", " ".join(f"word{i}" for i in range(100)))]
    nodes = [_node("n1", BlockRole.PARAGRAPH, "only a few words survived", ["b1"])]
    result = compute_integrity(_document(blocks, nodes), epub_word_count=5)

    assert result.ratio < 0.9
    assert result.suspicious is True


def test_native_and_ocr_words_are_tracked_separately():
    blocks = [
        _block("b1", "three native words", source="native"),
        _block("b2", "two ocr", source="ocr"),
    ]
    nodes = [
        _node("n1", BlockRole.PARAGRAPH, "three native words", ["b1"]),
        _node("n2", BlockRole.PARAGRAPH, "two ocr", ["b2"]),
    ]
    result = compute_integrity(_document(blocks, nodes), epub_word_count=5)

    assert result.native_word_count == 3
    assert result.ocr_word_count == 2


def test_counts_are_reported_per_role_for_every_new_block_type():
    blocks = [_block(f"b{i}", "text here") for i in range(6)]
    nodes = [
        _node("n1", BlockRole.PARAGRAPH, "text here", ["b0"]),
        _node("n2", BlockRole.VERSE, "text here", ["b1"]),
        _node("n3", BlockRole.ENDNOTE, "text here", ["b2"]),
        _node("n4", BlockRole.TABLE, "text here", ["b3"]),
        _node("n5", BlockRole.FORMULA, "text here", ["b4"]),
        _node("n6", BlockRole.IMAGE_FALLBACK, "", ["b5"]),
    ]
    result = compute_integrity(_document(blocks, nodes), epub_word_count=8)

    for role in ("paragraph", "verse", "endnote", "table", "formula", "image_fallback"):
        assert result.counts_by_role.get(role) == 1, role
