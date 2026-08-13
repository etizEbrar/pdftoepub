from app.models.document import Block, BlockRole
from app.pipeline.headers_footers import detect_furniture


def _page_blocks(page: int, header_text: str, footer_page_num: int) -> list[Block]:
    page_h = 792.0
    return [
        Block(
            block_id=f"p{page}_header",
            page=page,
            page_width=612.0,
            page_height=page_h,
            bbox=(72, 20, 400, 35),
            kind="text",
            text=header_text,
        ),
        Block(
            block_id=f"p{page}_body",
            page=page,
            page_width=612.0,
            page_height=page_h,
            bbox=(72, 200, 400, 220),
            kind="text",
            text=f"Body content unique to page {page}.",
        ),
        Block(
            block_id=f"p{page}_footer",
            page=page,
            page_width=612.0,
            page_height=page_h,
            bbox=(280, 760, 320, 775),
            kind="text",
            text=str(footer_page_num),
        ),
    ]


def test_repeated_header_detected_across_pages():
    blocks_by_page = {p: _page_blocks(p, "The Sample Chronicle", p) for p in range(1, 6)}
    furniture = detect_furniture(blocks_by_page)
    for p in range(1, 6):
        assert furniture[f"p{p}_header"] == BlockRole.HEADER
        assert furniture[f"p{p}_footer"] == BlockRole.PAGE_NUMBER
        assert f"p{p}_body" not in furniture


def test_non_repeated_text_in_margin_band_is_not_furniture():
    # Genuinely distinct headers (not just a changing page number within an
    # otherwise-identical running header) must never be treated as furniture.
    distinct_titles = ["Preface", "Introduction", "Methods", "Results", "Conclusion"]
    blocks_by_page = {p: _page_blocks(p, distinct_titles[p - 1], p) for p in range(1, 6)}
    furniture = detect_furniture(blocks_by_page)
    for p in range(1, 6):
        assert f"p{p}_header" not in furniture
        # page numbers are still detected purely by pattern, independent of repetition
        assert furniture[f"p{p}_footer"] == BlockRole.PAGE_NUMBER


def test_body_content_never_flagged_as_furniture():
    blocks_by_page = {p: _page_blocks(p, "Running Title", p) for p in range(1, 4)}
    furniture = detect_furniture(blocks_by_page)
    assert not any(k.endswith("_body") for k in furniture)
