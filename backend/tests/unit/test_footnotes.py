from app.models.document import Block, BlockRole, Span, StructuralNode
from app.pipeline.footnotes import (
    MARKER_CLOSE,
    MARKER_OPEN,
    collect_note_numbers_by_page,
    link_references,
    mark_reference_candidates,
)


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


def _page(page: int, body_text: str, note_text: str | None, body_size: float = 8.85):
    """A body block high on the page plus an optional small note block low on it."""
    blocks = [
        Block(
            block_id=f"p{page}_body",
            page=page,
            page_width=396,
            page_height=561,
            bbox=(28, 60, 360, 200),
            kind="text",
            text=body_text,
            spans=[_span(body_text, body_size, line_break_after=True)],
            font_size=body_size,
        )
    ]
    if note_text is not None:
        blocks.append(
            Block(
                block_id=f"p{page}_note",
                page=page,
                page_width=396,
                page_height=561,
                bbox=(28, 500, 360, 512),
                kind="text",
                text=note_text,
                spans=[_span(note_text, 5.4, line_break_after=True)],
                font_size=5.4,
            )
        )
    return blocks


def test_marker_welded_to_a_word_is_recovered_when_a_matching_note_exists():
    """Scanned books lose the superscript flag, leaving the digit stuck to the
    preceding word: "o meshur hareketleri2"."""
    blocks = _page(102, "Bu iddia bir kaynaga dayanmaktadir2", "2 Kaynak aciklamasi burada.")
    numbers = collect_note_numbers_by_page(blocks, 8.85)
    assert numbers == {102: {"2"}}

    mark_reference_candidates(blocks, 8.85, numbers)
    assert f"{MARKER_OPEN}2{MARKER_CLOSE}" in blocks[0].text


def test_a_digit_welded_to_a_word_is_left_alone_when_no_such_note_exists():
    """The evidence gate: without a matching note body, "kitap1966" and
    "No. 8" must stay ordinary text rather than becoming links to nothing."""
    blocks = _page(50, "Yayinlandi 1966 yilinda ve kitap12 satildi", None)
    mark_reference_candidates(blocks, 8.85, {})
    assert MARKER_OPEN not in blocks[0].text


def test_note_body_keeps_its_own_number_for_matching():
    """The note's leading number must not be wrapped as a reference, or the
    note would point at itself and lose the number the linker matches on."""
    blocks = _page(102, "Some claim2", "2 The note text.")
    numbers = collect_note_numbers_by_page(blocks, 8.85)
    mark_reference_candidates(blocks, 8.85, numbers)
    assert MARKER_OPEN not in blocks[1].text
    assert blocks[1].text.startswith("2 ")


def test_years_and_long_numbers_are_never_treated_as_markers():
    blocks = _page(10, "Yayinlandi 1966 ve 2024 yillarinda", "1 A real note.")
    numbers = collect_note_numbers_by_page(blocks, 8.85)
    mark_reference_candidates(blocks, 8.85, numbers)
    assert MARKER_OPEN not in blocks[0].text


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
