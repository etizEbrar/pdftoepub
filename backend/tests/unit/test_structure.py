from app.models.document import Block, BlockRole
from app.pipeline.structure import classify_blocks


def _block(
    block_id: str,
    y0: float,
    y1: float,
    text: str,
    font_size: float = 10.0,
    bold: bool = False,
    italic: bool = False,
    x0: float = 72.0,
    x1: float = 300.0,
    page: int = 1,
) -> Block:
    return Block(
        block_id=block_id,
        page=page,
        page_width=612.0,
        page_height=792.0,
        bbox=(x0, y0, x1, y1),
        kind="text",
        text=text,
        font="Helvetica",
        font_size=font_size,
        bold=bold,
        italic=italic,
        baseline=y1,
        line_id=f"{block_id}_l0",
    )


def _body_paragraphs(n: int, start_y: float = 100.0):
    blocks = []
    y = start_y
    for i in range(n):
        blocks.append(_block(f"p{i}", y, y + 14, f"This is a normal body paragraph number {i}."))
        y += 30
    return blocks, y


def test_detects_isolated_bold_larger_text_as_heading():
    body, y = _body_paragraphs(2)
    heading = _block("h1", y + 20, y + 45, "Chapter One", font_size=20.0, bold=True)
    more_body, _ = _body_paragraphs(2, start_y=y + 80)
    blocks = body + [heading] + more_body
    nodes = classify_blocks(blocks)
    heading_nodes = [n for n in nodes if n.role == BlockRole.HEADING]
    assert len(heading_nodes) == 1
    assert heading_nodes[0].text == "Chapter One"
    assert heading_nodes[0].level == 1


def test_plain_paragraph_is_not_a_heading():
    body, _ = _body_paragraphs(3)
    nodes = classify_blocks(body)
    assert all(n.role == BlockRole.PARAGRAPH for n in nodes)


def test_splits_multiline_bulleted_block_into_separate_list_items():
    body, y = _body_paragraphs(1)
    bullets = _block("b1", y, y + 40, "• First item\n• Second item\n• Third item")
    nodes = classify_blocks(body + [bullets])
    list_nodes = [n for n in nodes if n.role == BlockRole.LIST_ITEM]
    assert len(list_nodes) == 3
    assert [n.text for n in list_nodes] == ["• First item", "• Second item", "• Third item"]
    assert all(n.source_block_ids == ["b1"] for n in list_nodes)


def test_numbered_list_detected_as_ordered_candidate():
    body, y = _body_paragraphs(1)
    numbered = _block("n1", y, y + 40, "1. First\n2. Second")
    nodes = classify_blocks(body + [numbered])
    list_nodes = [n for n in nodes if n.role == BlockRole.LIST_ITEM]
    assert len(list_nodes) == 2


def test_furniture_blocks_bypass_heuristics():
    body, y = _body_paragraphs(1)
    header_block = _block("hdr", 10, 20, "Running Title", font_size=9.0)
    nodes = classify_blocks(body + [header_block], furniture={"hdr": BlockRole.HEADER})
    furniture_nodes = [n for n in nodes if n.role == BlockRole.HEADER]
    assert len(furniture_nodes) == 1
    assert furniture_nodes[0].text == "Running Title"
