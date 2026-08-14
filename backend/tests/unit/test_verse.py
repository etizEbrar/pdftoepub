from app.models.document import Block, BlockRole, Span, StructuralNode
from app.pipeline.verse import detect_verse


def _line_block(block_id: str, text: str, x0: float, y0: float, width: float, size: float = 12.0) -> Block:
    """One single-line block, the way poetry is typeset in a PDF."""
    bbox = (x0, y0, x0 + width, y0 + size + 4)
    span = Span(
        text=text,
        bbox=bbox,
        font="Helvetica",
        font_size=size,
        bold=False,
        italic=False,
        baseline=y0 + size,
        line_break_after=True,
    )
    return Block(
        block_id=block_id,
        page=1,
        page_width=612,
        page_height=792,
        bbox=bbox,
        kind="text",
        text=text,
        spans=[span],
        font="Helvetica",
        font_size=size,
    )


def _wrapped_block(block_id: str, lines: list[str], x0: float, y0: float, widths: list[float], size: float = 12.0) -> Block:
    """A multi-line prose block: wrapped text whose last line is short."""
    spans = []
    y = y0
    for text, width in zip(lines, widths):
        spans.append(
            Span(
                text=text,
                bbox=(x0, y, x0 + width, y + size + 4),
                font="Helvetica",
                font_size=size,
                bold=False,
                italic=False,
                baseline=y + size,
                line_break_after=True,
            )
        )
        y += size + 6
    return Block(
        block_id=block_id,
        page=1,
        page_width=612,
        page_height=792,
        bbox=(x0, y0, x0 + max(widths), y),
        kind="text",
        text="\n".join(lines),
        spans=spans,
        font="Helvetica",
        font_size=size,
    )


def _nodes_for(blocks: list[Block]) -> list[StructuralNode]:
    return [
        StructuralNode(
            node_id=f"n_{b.block_id}",
            role=BlockRole.PARAGRAPH,
            text=b.text,
            source_block_ids=[b.block_id],
            page=b.page,
        )
        for b in blocks
    ]


def _poem_blocks() -> list[Block]:
    return [
        _line_block("v1", "Because I could not stop for Death", 72, 130, 184),
        _line_block("v2", "He kindly stopped for me", 92, 148, 132),
        _line_block("v3", "The Carriage held but just Ourselves", 72, 166, 195),
        _line_block("v4", "And Immortality", 92, 184, 83),
    ]


def _prose_block() -> Block:
    return _wrapped_block(
        "p1",
        [
            "This closing paragraph is ordinary prose that runs to the margin",
            "of the page and must never be mistaken for verse by the engine.",
        ],
        72,
        320,
        [349, 345],
    )


def test_detects_poetry_from_consecutive_short_ragged_lines():
    blocks = _poem_blocks() + [_prose_block()]
    nodes = _nodes_for(blocks)
    count = detect_verse(nodes, {b.block_id: b for b in blocks})

    assert count == 1
    verse_nodes = [n for n in nodes if n.role == BlockRole.VERSE]
    assert len(verse_nodes) == 1
    assert verse_nodes[0].verse_lines[0] == "Because I could not stop for Death"
    assert len(verse_nodes[0].verse_lines) == 4


def test_preserves_relative_indentation_as_steps_not_coordinates():
    blocks = _poem_blocks() + [_prose_block()]
    nodes = _nodes_for(blocks)
    detect_verse(nodes, {b.block_id: b for b in blocks})
    verse = next(n for n in nodes if n.role == BlockRole.VERSE)

    # Indents are small integer steps so the EPUB stays reflowable.
    assert verse.verse_indents[0] == 0
    assert verse.verse_indents[1] > 0
    assert all(isinstance(i, int) and i < 10 for i in verse.verse_indents)


def test_prose_paragraph_is_never_converted_to_verse():
    blocks = [_prose_block()]
    nodes = _nodes_for(blocks)
    assert detect_verse(nodes, {b.block_id: b for b in blocks}) == 0
    assert all(n.role == BlockRole.PARAGRAPH for n in nodes)


def test_wrapped_prose_run_with_short_last_lines_is_not_verse():
    """The regression that made footnote bodies look like poetry: several
    two-line prose blocks whose second line is short."""
    blocks = [
        _wrapped_block("a", ["Claim number one on this page requires support", "1 and continues."], 72, 100, [267, 100]),
        _wrapped_block("b", ["Claim number two on this page requires support", "2 and continues."], 72, 140, [267, 100]),
        _wrapped_block("c", ["Claim number three on this page requires support", "3 and continues."], 72, 180, [267, 100]),
    ]
    nodes = _nodes_for(blocks)
    assert detect_verse(nodes, {b.block_id: b for b in blocks}) == 0


def test_two_lines_is_too_few_to_be_verse():
    blocks = [
        _line_block("v1", "A short line here", 72, 130, 120),
        _line_block("v2", "Another short line", 72, 148, 130),
        _prose_block(),
    ]
    nodes = _nodes_for(blocks)
    assert detect_verse(nodes, {b.block_id: b for b in blocks}) == 0


def test_verse_node_keeps_every_source_block_for_integrity_accounting():
    blocks = _poem_blocks() + [_prose_block()]
    nodes = _nodes_for(blocks)
    detect_verse(nodes, {b.block_id: b for b in blocks})
    verse = next(n for n in nodes if n.role == BlockRole.VERSE)
    assert set(verse.source_block_ids) == {"v1", "v2", "v3", "v4"}
