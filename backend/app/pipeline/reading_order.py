from __future__ import annotations

from app.models.document import Block

_FULL_WIDTH_RATIO = 0.75
_MIN_COLUMN_BLOCKS = 2
_ROW_SNAP = 4.0  # px tolerance for "same visual row" in single-column mode


def _content_bounds(blocks: list[Block]) -> tuple[float, float]:
    x0 = min(b.bbox[0] for b in blocks)
    x1 = max(b.bbox[2] for b in blocks)
    return x0, x1


def _find_gutter(blocks: list[Block], content_x0: float, content_x1: float) -> float | None:
    """Look for a vertical strip near the horizontal middle third that no block's
    bbox crosses — the classic signature of a two-column layout's gutter."""
    content_width = content_x1 - content_x0
    if content_width <= 0:
        return None
    narrow = [b for b in blocks if (b.bbox[2] - b.bbox[0]) < _FULL_WIDTH_RATIO * content_width]
    if len(narrow) < _MIN_COLUMN_BLOCKS * 2:
        return None

    mid_lo = content_x0 + content_width * 0.35
    mid_hi = content_x0 + content_width * 0.65
    # candidate gutter x-positions: midpoints between blocks sorted by x0
    candidates = sorted({round(b.bbox[0], 1) for b in narrow} | {round(b.bbox[2], 1) for b in narrow})
    best_gutter = None
    for x in candidates:
        if not (mid_lo <= x <= mid_hi):
            continue
        crossed = [b for b in narrow if b.bbox[0] < x < b.bbox[2]]
        if crossed:
            continue
        left = [b for b in narrow if b.bbox[2] <= x]
        right = [b for b in narrow if b.bbox[0] >= x]
        if len(left) >= _MIN_COLUMN_BLOCKS and len(right) >= _MIN_COLUMN_BLOCKS:
            best_gutter = x
            break
    return best_gutter


def order_blocks_on_page(blocks: list[Block]) -> list[Block]:
    """Return blocks in natural reading order, handling single- and two-column
    layouts. Full-width blocks (titles, section headings spanning both columns)
    act as row breaks between column segments, per spec section 12."""
    if not blocks:
        return []

    content_x0, content_x1 = _content_bounds(blocks)
    content_width = content_x1 - content_x0
    gutter = _find_gutter(blocks, content_x0, content_x1) if content_width > 0 else None

    if gutter is None:
        ordered = sorted(blocks, key=lambda b: (round(b.bbox[1] / _ROW_SNAP), b.bbox[0]))
        for i, b in enumerate(ordered):
            b.column = 0
            b.order_key = float(i)
        return ordered

    full_width = [b for b in blocks if (b.bbox[2] - b.bbox[0]) >= _FULL_WIDTH_RATIO * content_width]
    left_col = [b for b in blocks if b not in full_width and b.bbox[2] <= gutter + 1]
    right_col = [b for b in blocks if b not in full_width and b.bbox[0] >= gutter - 1]
    # Anything left over (crosses the gutter but isn't "full width") — treat as full-width.
    accounted = set(id(b) for b in full_width + left_col + right_col)
    leftover = [b for b in blocks if id(b) not in accounted]
    full_width = sorted(full_width + leftover, key=lambda b: b.bbox[1])
    left_col.sort(key=lambda b: b.bbox[1])
    right_col.sort(key=lambda b: b.bbox[1])

    ordered: list[Block] = []
    li = ri = 0
    breakpoints = [b.bbox[1] for b in full_width] + [float("inf")]
    for bp_index, bp_y in enumerate(breakpoints):
        while li < len(left_col) and left_col[li].bbox[1] < bp_y:
            left_col[li].column = 0
            ordered.append(left_col[li])
            li += 1
        while ri < len(right_col) and right_col[ri].bbox[1] < bp_y:
            right_col[ri].column = 1
            ordered.append(right_col[ri])
            ri += 1
        if bp_index < len(full_width):
            full_width[bp_index].column = -1
            ordered.append(full_width[bp_index])

    for i, b in enumerate(ordered):
        b.order_key = float(i)
    return ordered


def order_document_blocks(blocks_by_page: dict[int, list[Block]]) -> list[Block]:
    result: list[Block] = []
    for page_num in sorted(blocks_by_page.keys()):
        result.extend(order_blocks_on_page(blocks_by_page[page_num]))
    return result
