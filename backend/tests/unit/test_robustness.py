"""Defects the corpus audit found, none of them specific to one book.

Each was found by converting real books in scripts/corpus/: a conversion that
failed outright, or one that completed and read badly.
"""

from __future__ import annotations

import fitz
from lxml import etree

from app.models.document import Block, BlockRole, Span, StructuralNode
from app.pipeline.epub.builder import Chapter, render_chapter_body
from app.pipeline.epub.xmltext import xml_escape, xml_text
from app.pipeline.formulas import detect_formula
from app.pipeline.images import is_blank_page


# --- nothing in the PDF can make the EPUB invalid ---------------------------


def test_escaped_text_is_safe_inside_a_double_quoted_attribute():
    alt = xml_escape('attention "Scaled Dot-Product Attention" <a> & b')
    element = etree.fromstring(f'<img src="x.png" alt="{alt}"/>')
    assert element.get("alt") == 'attention "Scaled Dot-Product Attention" <a> & b'


def test_characters_xml_forbids_are_removed():
    # A math font's bracket pieces come out of the PDF as control characters.
    assert xml_text("\x14 3×3, 64 \x15") == " 3×3, 64 "
    assert xml_escape("a\x00b\x1fc") == "abc"


def test_a_chapter_holding_quotes_and_control_characters_is_well_formed_xml():
    nodes = [
        StructuralNode(node_id="n1", role=BlockRole.PARAGRAPH, text='He said "stop".\x14'),
        StructuralNode(
            node_id="n2",
            role=BlockRole.IMAGE_FALLBACK,
            image_ref="img1",
            alt_text='call it "Scaled Dot-Product Attention"',
        ),
    ]
    images = {"img1": {"ref": "img1", "path": "img1.png", "ext": "png", "page": 1, "bbox": [0, 0, 1, 1]}}
    body = render_chapter_body(Chapter(filename="c.xhtml", title="C", nodes=nodes), "c.xhtml", {}, images)
    etree.fromstring(f'<body xmlns="http://www.w3.org/1999/xhtml">{body}</body>')


# --- prose is never a picture of an equation ---------------------------------


def _formula_block(spans: list[tuple[str, str, bool]]) -> Block:
    built, x = [], 72.0
    for text, font, superscript in spans:
        built.append(
            Span(
                text=text,
                bbox=(x, 100, x + 6 * len(text), 112),
                font=font,
                font_size=10.0,
                bold=False,
                italic=False,
                baseline=110,
                is_superscript=superscript,
            )
        )
        x += 6 * len(text)
    built[-1].line_break_after = True
    return Block(
        block_id="b1",
        page=1,
        page_width=612,
        page_height=792,
        bbox=(72, 100, x, 112),
        kind="text",
        text="".join(t for t, _, _ in spans),
        spans=built,
    )


def test_an_authors_name_with_a_footnote_star_is_not_an_equation():
    block = _formula_block([("Ashish Vaswani", "NimbusRomNo9L-Regu", False), ("∗", "CMSY7", True)])
    assert detect_formula(block) is None


def test_a_paragraph_with_some_mathematics_in_it_stays_text():
    text = (
        "We used the Adam optimizer with β1 = 0.9, β2 = 0.98 and ϵ = 10−9. We varied the learning "
        "rate over the course of training, according to the formula given below."
    )
    block = _formula_block([(text, "CMMI10", False)])
    assert detect_formula(block) is None


def test_a_display_equation_is_still_an_equation():
    block = _formula_block([("∑ xᵢ² ≤ ∫ f(x) dx", "CMMI10", False)])
    assert detect_formula(block) is not None


# --- a blank leaf is not a page of the book -----------------------------------


def _scan_page(ink: bool) -> fitz.Page:
    doc = fitz.open()
    page = doc.new_page(width=432, height=648)
    paper = fitz.Pixmap(fitz.csGRAY, fitz.IRect(0, 0, 864, 1296), False)
    paper.clear_with(205)  # aged paper, not white
    if ink:
        for row in range(30):
            paper.set_rect(fitz.IRect(100, 120 + row * 36, 760, 132 + row * 36), (60,))
    else:
        paper.set_rect(fitz.IRect(600, 80, 640, 90), (120,))  # a pencilled shelf mark
    page.insert_image(page.rect, pixmap=paper)
    return page


def test_an_endpaper_with_a_shelf_mark_is_blank():
    assert is_blank_page(_scan_page(ink=False))


def test_a_scanned_page_of_text_is_not_blank():
    assert not is_blank_page(_scan_page(ink=True))


# --- no link points at nothing --------------------------------------------------


def test_links_to_anchors_the_book_lacks_are_unlinked():
    from app.pipeline.epub.builder import _drop_dangling_links

    bodies = {
        "a.xhtml": (
            '<p>See<a epub:type="noteref" class="noteref" href="b.xhtml#fn1" id="r1">1</a> and'
            '<a class="noteref" href="b.xhtml#gone" id="r2">2</a>.</p>'
        ),
        "b.xhtml": (
            '<aside id="fn1"><p>Note. <a class="noteback" href="a.xhtml#r1">↩</a>'
            '<a class="noteback" href="a.xhtml#swallowed">↩2</a></p></aside>'
        ),
    }
    fixed = _drop_dangling_links(bodies)
    assert 'href="b.xhtml#fn1"' in fixed["a.xhtml"]
    assert 'href="b.xhtml#gone"' not in fixed["a.xhtml"] and "and2." in fixed["a.xhtml"]
    assert 'href="a.xhtml#r1"' in fixed["b.xhtml"]
    assert "swallowed" not in fixed["b.xhtml"]


# --- tables set out by alignment under their caption -------------------------


def _row_block(block_id: str, y: float, cells: list[tuple[float, str]], page: int = 3) -> Block:
    spans = [
        Span(
            text=text,
            bbox=(x, y, x + 6 * len(text), y + 11),
            font="TimesNewRoman",
            font_size=11.0,
            bold=False,
            italic=False,
            baseline=y + 9,
            line_break_after=(i == len(cells) - 1),
        )
        for i, (x, text) in enumerate(cells)
    ]
    return Block(
        block_id=block_id,
        page=page,
        page_width=595,
        page_height=842,
        bbox=(spans[0].bbox[0], y, spans[-1].bbox[2], y + 11),
        kind="text",
        text="\n".join(t for _, t in cells),
        spans=spans,
        font_size=11.0,
    )


def test_a_table_ruled_only_across_is_found_under_its_caption():
    from app.pipeline.tables import _aligned_tables

    blocks = [
        _row_block("cap", 380, [(124, "Çizelge 1. Kullanılan çimentonun bileşimi")]),
        _row_block("head", 403, [(169, "Bileşenler"), (245, "CEM I 42,5 R (%)   Uçucu Kül")]),
        _row_block("r1", 426, [(169, "SiO2"), (268, "19,10"), (360, "18,20")]),
        _row_block("r2", 450, [(169, "Fe2O3"), (270, "2,65"), (362, "2,00")]),
        _row_block("r3", 472, [(169, "CaO"), (268, "63,40"), (362, "67,0")]),
        _row_block("after", 520, [(71, "Numunelerin hazırlanmasında hidrolik bağlayıcı olarak TS EN 197-1 standardına uygun olarak üretilmiş çimento kullanılmıştır.")]),
    ]
    tables = _aligned_tables(3, blocks, [])
    assert len(tables) == 1
    table = tables[0].data
    rows: dict[int, list[str]] = {}
    for cell in table.cells:
        rows.setdefault(cell.row, []).append(cell.text)
    assert rows[0] == ["Bileşenler", "CEM I 42,5 R (%)", "Uçucu Kül"]
    assert rows[1] == ["SiO2", "19,10", "18,20"]
    assert table.has_header_row
    assert set(tables[0].covered_block_ids) == {"head", "r1", "r2", "r3"}


def test_lines_of_prose_under_a_caption_are_not_a_table():
    from app.pipeline.tables import _aligned_tables

    blocks = [
        _row_block("cap", 380, [(124, "Tablo 2 aşağıda verilmiştir.")]),
        _row_block("p1", 403, [(71, "Bu çalışmada farklı yöntemler karşılaştırılmış ve elde edilen sonuçlar ayrıntılı olarak değerlendirilmiştir.")]),
        _row_block("p2", 426, [(71, "Sonuçlar tartışılmış ve öneriler sunulmuştur.")]),
    ]
    assert _aligned_tables(3, blocks, []) == []


# --- a running head wherever the scan put it -----------------------------------


def test_a_running_head_low_on_the_page_with_its_folio_on_either_side_is_furniture():
    from app.pipeline.headers_footers import detect_furniture

    def page(number: int) -> list[Block]:
        head = f"{number}\nA STUDY IN SCARLET," if number % 2 == 0 else f"A STUDY IN SCARLET.\n{number}"
        top = 53 + (number % 3) * 3  # the scan sits a little differently on every leaf
        blocks = [
            Block(block_id=f"p{number}_head", page=number, page_width=320, page_height=480,
                  bbox=(71, top, 236, top + 8), kind="text", text=head, font_size=8.8),
        ]
        for i in range(4):
            blocks.append(
                Block(block_id=f"p{number}_b{i}", page=number, page_width=320, page_height=480,
                      bbox=(71, 70 + i * 90, 298, 150 + i * 90), kind="text",
                      text=f"Body text {number} {i} that is long enough to be prose.\nAnd wraps.\nAgain.",
                      font_size=8.5)
            )
        return blocks

    furniture = detect_furniture({n: page(n) for n in range(10, 30)})
    assert all(furniture.get(f"p{n}_head") is BlockRole.HEADER for n in range(10, 30))
    assert not any(k.endswith(("_b0", "_b1", "_b2", "_b3")) for k in furniture)


# --- a scan's own margins ------------------------------------------------------


def test_a_right_hand_scanned_page_is_not_read_as_quotations():
    from app.pipeline.structure import classify_blocks

    def page(number: int, left: float) -> list[Block]:
        return [
            Block(
                block_id=f"p{number}_b{i}", page=number, page_width=320, page_height=480,
                bbox=(left, 60 + i * 60, left + 227, 110 + i * 60), kind="text",
                text="A line of the story that runs on\nto the next line of it\nand ends here.",
                font_size=8.1 if number % 2 else 8.6,
            )
            for i in range(6)
        ]

    blocks = [b for n in range(1, 9) for b in page(n, 71 if n % 2 else 40)]
    nodes = classify_blocks(blocks, {})
    assert all(n.role == BlockRole.PARAGRAPH for n in nodes)


# --- a scan is recognised without decoding it --------------------------------------


def test_a_page_shaped_picture_makes_the_page_a_scan_and_a_photo_does_not():
    from app.pipeline.images import page_is_scan

    doc = fitz.open()
    scanned = doc.new_page(width=400, height=600)
    scanned.insert_image(scanned.rect, pixmap=fitz.Pixmap(fitz.csGRAY, fitz.IRect(0, 0, 800, 1200), False))
    illustrated = doc.new_page(width=400, height=600)
    illustrated.insert_image(fitz.Rect(50, 50, 350, 250), pixmap=fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 600, 400), False))
    assert page_is_scan(doc[0])
    assert not page_is_scan(doc[1])


def test_a_page_of_text_leaves_no_room_for_a_picture_and_a_half_page_gap_does():
    from app.pipeline.images import _room_for_a_picture

    rect = fitz.Rect(0, 0, 327, 526)

    def lines(spans: list[tuple[float, float]]) -> list[Block]:
        return [
            Block(block_id=f"b{i}", page=1, page_width=327, page_height=526,
                  bbox=(36, y0, 263, y1), kind="text", text="text " * 20)
            for i, (y0, y1) in enumerate(spans)
        ]

    area = (32, 38, 261, 423)
    full = lines([(38 + i * 13, 50 + i * 13) for i in range(30)])
    assert not _room_for_a_picture(rect, full, area)
    gap = lines([(38 + i * 13, 50 + i * 13) for i in range(8)] + [(330 + i * 13, 342 + i * 13) for i in range(7)])
    assert _room_for_a_picture(rect, gap, area)
