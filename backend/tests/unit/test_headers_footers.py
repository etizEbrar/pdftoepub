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


def _page_with_head(page: int, head: str, page_label: str, head_size: float = 9.0) -> list[Block]:
    return [
        Block(
            block_id=f"p{page}_header",
            page=page,
            page_width=612.0,
            page_height=792.0,
            bbox=(72, 20, 400, 35),
            kind="text",
            text=head,
            font_size=head_size,
        ),
        Block(
            block_id=f"p{page}_body",
            page=page,
            page_width=612.0,
            page_height=792.0,
            bbox=(72, 200, 500, 400),
            kind="text",
            text=f"Body content unique to page {page}. " * 12,
            font_size=10.0,
        ),
        Block(
            block_id=f"p{page}_footer",
            page=page,
            page_width=612.0,
            page_height=792.0,
            bbox=(280, 760, 320, 775),
            kind="text",
            text=page_label,
            font_size=9.0,
        ),
    ]


def test_alternating_verso_recto_running_heads_are_both_detected():
    """Books put the author on the verso and the title on the recto, so each
    appears on only ~half the pages. A whole-book repetition threshold detects
    neither, and both then bleed into the body prose."""
    blocks_by_page = {
        p: _page_with_head(p, "The Book Title" if p % 2 == 0 else "Author Name", str(p))
        for p in range(1, 21)
    }
    furniture = detect_furniture(blocks_by_page)
    for p in range(1, 21):
        assert furniture.get(f"p{p}_header") == BlockRole.HEADER, f"page {p} head not detected"


def test_page_numbers_split_by_ocr_are_still_recognised():
    """A scanner routinely emits "4 1" for 41 and "1 00" for 100; a strict
    ^\\d{1,4}$ pattern misses these, and they end up read as footnote bodies."""
    blocks_by_page = {
        41: _page_with_head(41, "Title", "4 1"),
        100: _page_with_head(100, "Title", "1 00"),
        7: _page_with_head(7, "Title", "7"),
    }
    furniture = detect_furniture(blocks_by_page)
    for page in (41, 100, 7):
        assert furniture.get(f"p{page}_footer") == BlockRole.PAGE_NUMBER, page


def test_a_display_size_number_is_a_chapter_number_not_a_page_number():
    """"1" set at 28.9pt above a chapter title is a division number. Removing it
    as furniture loses the number and orphans the title from it."""
    blocks_by_page = {
        p: _page_with_head(p, "Title", str(p)) for p in range(1, 12)
    }
    blocks_by_page[6].append(
        Block(
            block_id="p6_chapnum",
            page=6,
            page_width=612.0,
            page_height=792.0,
            bbox=(280, 40, 320, 80),
            kind="text",
            text="1",
            font_size=28.9,
        )
    )
    furniture = detect_furniture(blocks_by_page)
    assert "p6_chapnum" not in furniture
    assert furniture.get("p6_footer") == BlockRole.PAGE_NUMBER
