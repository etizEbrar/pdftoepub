from app.models.document import Block
from app.pipeline.reading_order import order_blocks_on_page


def _block(block_id: str, x0: float, y0: float, x1: float, y1: float) -> Block:
    return Block(
        block_id=block_id,
        page=1,
        page_width=612.0,
        page_height=792.0,
        bbox=(x0, y0, x1, y1),
        kind="text",
        text=block_id,
    )


def test_single_column_orders_top_to_bottom():
    blocks = [
        _block("c", 72, 300, 500, 320),
        _block("a", 72, 100, 500, 120),
        _block("b", 72, 200, 500, 220),
    ]
    ordered = order_blocks_on_page(blocks)
    assert [b.block_id for b in ordered] == ["a", "b", "c"]


def test_two_column_layout_reads_full_column_then_next():
    # Left column: x 72-280, right column: x 320-540, clear gutter 280-320.
    blocks = [
        _block("title", 72, 50, 540, 80),  # full-width, spans both columns
        _block("l1", 72, 120, 280, 140),
        _block("l2", 72, 160, 280, 180),
        _block("r1", 320, 120, 540, 140),
        _block("r2", 320, 160, 540, 180),
    ]
    ordered = order_blocks_on_page(blocks)
    ids = [b.block_id for b in ordered]
    assert ids == ["title", "l1", "l2", "r1", "r2"]


def test_full_width_heading_breaks_columns_into_segments():
    blocks = [
        _block("l1", 72, 100, 280, 120),
        _block("r1", 320, 100, 540, 120),
        _block("mid_heading", 72, 200, 540, 220),  # full width, sits between the two rows
        _block("l2", 72, 260, 280, 280),
        _block("r2", 320, 260, 540, 280),
    ]
    ordered = order_blocks_on_page(blocks)
    ids = [b.block_id for b in ordered]
    assert ids == ["l1", "r1", "mid_heading", "l2", "r2"]
