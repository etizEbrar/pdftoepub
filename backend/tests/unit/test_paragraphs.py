from app.models.document import BlockRole, StructuralNode
from app.pipeline.paragraphs import reconstruct_paragraphs


def _para(node_id: str, text: str) -> StructuralNode:
    return StructuralNode(node_id=node_id, role=BlockRole.PARAGRAPH, text=text, source_block_ids=[node_id])


def test_merges_paragraph_split_across_blocks_without_terminal_punctuation():
    nodes = [
        _para("a", "This sentence continues"),
        _para("b", "onto the next block without a break."),
    ]
    result = reconstruct_paragraphs(nodes)
    assert len(result) == 1
    assert result[0].text == "This sentence continues onto the next block without a break."
    assert result[0].source_block_ids == ["a", "b"]


def test_does_not_merge_when_previous_ends_with_terminal_punctuation():
    nodes = [
        _para("a", "This is a complete sentence."),
        _para("b", "This is a new paragraph."),
    ]
    result = reconstruct_paragraphs(nodes)
    assert len(result) == 2
    assert result[0].text == "This is a complete sentence."
    assert result[1].text == "This is a new paragraph."


def test_heading_breaks_a_merge_run():
    nodes = [
        _para("a", "Continues without punctuation"),
        StructuralNode(node_id="h", role=BlockRole.HEADING, text="A Heading", source_block_ids=["h"]),
        _para("b", "A fresh paragraph after the heading."),
    ]
    result = reconstruct_paragraphs(nodes)
    assert len(result) == 3
    assert result[0].role == BlockRole.PARAGRAPH
    assert result[1].role == BlockRole.HEADING
    assert result[2].text == "A fresh paragraph after the heading."


def test_repairs_hyphenation_across_the_merge_join():
    nodes = [
        _para("a", "This word wraps mid-"),
        _para("b", "way through a sentence and keeps going."),
    ]
    result = reconstruct_paragraphs(nodes)
    assert len(result) == 1
    assert "midway" in result[0].text
