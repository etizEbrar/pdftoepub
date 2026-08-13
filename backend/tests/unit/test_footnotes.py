from app.models.document import Block, BlockRole, Span, StructuralNode
from app.pipeline.footnotes import MARKER_CLOSE, MARKER_OPEN, link_references, mark_reference_candidates


def _span(text: str, font_size: float, is_superscript: bool = False, line_break_after: bool = False) -> Span:
    return Span(
        text=text,
        bbox=(0, 0, 10, 10),
        font="Helvetica",
        font_size=font_size,
        bold=False,
        italic=False,
        baseline=0.0,
        is_superscript=is_superscript,
        line_break_after=line_break_after,
    )


def test_mark_reference_candidates_wraps_small_numeric_span():
    block = Block(
        block_id="p1_b0",
        page=1,
        page_width=612,
        page_height=792,
        bbox=(0, 0, 100, 20),
        kind="text",
        spans=[
            _span("A claim", 10.0),
            _span("1", 7.0, line_break_after=True),  # small size relative to body -> candidate
        ],
    )
    mark_reference_candidates([block], body_size=10.0)
    assert f"{MARKER_OPEN}1{MARKER_CLOSE}" in block.text


def test_mark_reference_candidates_leaves_normal_text_alone():
    block = Block(
        block_id="p1_b1",
        page=1,
        page_width=612,
        page_height=792,
        bbox=(0, 0, 100, 20),
        kind="text",
        spans=[_span("Ordinary sentence with a 12 in it.", 10.0, line_break_after=True)],
    )
    mark_reference_candidates([block], body_size=10.0)
    assert MARKER_OPEN not in block.text


def test_link_references_connects_marker_to_matching_footnote_on_same_page():
    ref_node = StructuralNode(
        node_id="n_p1_b0",
        role=BlockRole.PARAGRAPH,
        text=f"A claim{MARKER_OPEN}1{MARKER_CLOSE} needing support.",
        source_block_ids=["p1_b0"],
        page=1,
    )
    footnote_node = StructuralNode(
        node_id="n_p1_b9",
        role=BlockRole.FOOTNOTE,
        text="1 This is the supporting footnote.",
        source_block_ids=["p1_b9"],
        page=1,
    )
    nodes, linked = link_references([ref_node, footnote_node])
    assert linked == 1
    assert "{{NOTEREF:n_p1_b9:" in ref_node.text
    assert footnote_node.footnote_number == "1"
    assert footnote_node.text == "This is the supporting footnote."
    assert len(footnote_node.footnote_backrefs) == 1


def test_footnote_spanning_to_next_page_still_links():
    ref_node = StructuralNode(
        node_id="n_p1_b0",
        role=BlockRole.PARAGRAPH,
        text=f"A claim{MARKER_OPEN}1{MARKER_CLOSE} needing support.",
        source_block_ids=["p1_b0"],
        page=1,
    )
    footnote_node = StructuralNode(
        node_id="n_p2_b0",
        role=BlockRole.FOOTNOTE,
        text="1 Footnote that overflowed onto the next page.",
        source_block_ids=["p2_b0"],
        page=2,
    )
    nodes, linked = link_references([ref_node, footnote_node])
    assert linked == 1


def test_unmatched_marker_falls_back_to_plain_superscript_not_a_broken_link():
    ref_node = StructuralNode(
        node_id="n_p1_b0",
        role=BlockRole.PARAGRAPH,
        text=f"A claim{MARKER_OPEN}5{MARKER_CLOSE} with no matching note.",
        source_block_ids=["p1_b0"],
        page=1,
    )
    nodes, linked = link_references([ref_node])
    assert linked == 0
    assert "{{SUP:5}}" in ref_node.text
    assert MARKER_OPEN not in ref_node.text
