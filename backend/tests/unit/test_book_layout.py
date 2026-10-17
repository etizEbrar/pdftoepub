"""The layout decisions that make an academic volume read as a book.

Each case is a defect a real 168-page Turkish edited volume shipped with.
"""

from __future__ import annotations

from app.models.document import Block, BlockRole, Span, StructuralNode
from app.pipeline import analyze, blocksplit, headings, structure, tables
from app.pipeline.bibliography import _LINK_LINE_RE
from app.pipeline.epub.builder import Chapter, render_chapter_body, slugify
from app.pipeline.footnotes import BOLD_CLOSE, BOLD_OPEN
from app.pipeline.paragraphs import reconstruct_paragraphs

PAGE_W, PAGE_H = 451.0, 680.0
LEFT, RIGHT = 51.0, 400.0


def _span(text, x0, y0, x1, size=11.0, bold=False, end=True):
    return Span(
        text=text,
        bbox=(x0, y0, x1, y0 + size * 1.2),
        font="Times-Bold" if bold else "Times-Roman",
        font_size=size,
        bold=bold,
        italic=False,
        baseline=y0 + size,
        line_break_after=end,
    )


def _block(block_id, lines, page=1, size=11.0):
    """`lines` is a list of (text, x0, x1, bold)."""
    spans = []
    y = 100.0
    for text, x0, x1, bold in lines:
        spans.append(_span(text, x0, y, x1, size=size, bold=bold))
        y += size * 1.35
    return Block(
        block_id=block_id,
        page=page,
        page_width=PAGE_W,
        page_height=PAGE_H,
        bbox=(min(s.bbox[0] for s in spans), spans[0].bbox[1], max(s.bbox[2] for s in spans), spans[-1].bbox[3]),
        kind="text",
        text="\n".join(t for t, *_ in lines),
        spans=spans,
        font_size=size,
        bold=all(b for *_, b in lines),
    )


def _body_block(block_id, page, first_x0=LEFT + 28, last_x1=RIGHT, lines=4, first="Metin"):
    rows = [(f"{first} satır bir", first_x0, RIGHT, False)]
    rows += [("devam eden satır", LEFT, RIGHT, False)] * (lines - 2)
    rows += [("son satır burada", LEFT, last_x1, False)]
    return _block(block_id, rows, page=page)


# --- block splitting --------------------------------------------------------


def test_a_bold_heading_set_tight_above_its_paragraph_becomes_its_own_block():
    block = _block(
        "p1_b001",
        [
            ("2.1. Motorun İzlenmesi", LEFT, 200, True),
            ("Elektrik motorlarının arızalarının erken dönemde tespit", LEFT, RIGHT, False),
            ("edilebilmesi için sistem sürekli izlenmelidir.", LEFT, 300, False),
        ],
    )
    parts = blocksplit.split_block(block)
    assert [p.text for p in parts] == [
        "2.1. Motorun İzlenmesi",
        "Elektrik motorlarının arızalarının erken dönemde tespit\nedilebilmesi için sistem sürekli izlenmelidir.",
    ]
    assert parts[0].bold and not parts[1].bold
    assert parts[0].block_id == "p1_b001" and parts[1].block_id == "p1_b001s1"


def test_a_bold_phrase_that_fills_a_line_mid_sentence_is_not_a_heading():
    block = _block(
        "p1_b002",
        [
            ("Bu çalışmada önerilen yöntem olan", LEFT, RIGHT, False),
            ("Derin Öğrenme Tabanlı Sınıflandırma", LEFT, RIGHT, True),
            ("yaklaşımı ayrıntılı olarak incelenmiştir.", LEFT, 300, False),
        ],
    )
    # The bold line follows an unfinished sentence, so it stays in it.
    parts = blocksplit.split_block(block)
    assert len(parts) == 2
    assert parts[0].text.startswith("Bu çalışmada önerilen yöntem olan\nDerin")


# --- headings ---------------------------------------------------------------


def _score(block, gap_above=14.0, gap_below=14.0):
    return headings.score_heading(
        block,
        11.0,
        gap_above=gap_above,
        gap_below=gap_below,
        line_gap=3.3,
        page_char_count=2500,
        is_first_content_block_on_page=False,
    )


def test_a_numbered_heading_longer_than_forty_characters_is_a_heading():
    block = _block("h1", [("1.1. Bilimde Yapay Zekâ: Fırsatlar ve Zorluklar", 79, 329, True)], size=12.0)
    assert _score(block).score >= headings.HEADING_THRESHOLD


def test_a_bold_heading_at_body_size_is_a_heading():
    block = _block("h2", [("SONUÇ", 87, 128, True)])
    assert _score(block, gap_above=1.4, gap_below=9.0).score >= headings.HEADING_THRESHOLD


def test_a_bold_lead_in_label_is_not_a_heading():
    block = _block("h3", [("Sağlık Hizmetleri:", LEFT, 160, True)])
    assert _score(block, gap_above=2.0, gap_below=2.0).score < headings.HEADING_THRESHOLD


def test_a_heading_opening_with_an_emphasis_marker_still_numbers_itself():
    block = _block("h4", [(f"{BOLD_OPEN}3.{BOLD_CLOSE} ALAN SARGILI AAM", LEFT, 250, True)])
    assert "numbered-title" in _score(block).signals


def test_unnumbered_sections_sit_inside_their_chapter():
    def heading(text, level):
        return StructuralNode(node_id=text, role=BlockRole.HEADING, text=text, level=level, heading_scale=1.1)

    nodes = [
        heading("ÖNSÖZ", 2),
        heading("BÖLÜM 1 VERİ YAPILARI", 2),
        heading("GİRİŞ", 2),
        heading("1.1. Bellek", 3),
        heading("KAYNAKÇA", 2),
        heading("BÖLÜM 2 RÜZGÂR", 2),
        heading("1. GİRİŞ", 3),
        heading("2.1. Türbinler", 3),
    ]
    headings._apply_numbering_hierarchy(nodes)
    assert [n.level for n in nodes] == [2, 2, 3, 3, 3, 2, 3, 4]


# --- classification ---------------------------------------------------------


def test_a_caption_with_a_bold_label_is_a_caption():
    block = _block("c1", [(f"{BOLD_OPEN}Şekil 1.{BOLD_CLOSE} Akı anahtarlamalı motor çeşitleri", 90, 360, False)])
    nodes = structure.classify_blocks([_body_block("b0", 1), block])
    assert nodes[-1].role == BlockRole.CAPTION


def test_list_items_that_wrap_are_still_separate_items():
    block = _block(
        "l1",
        [
            ("• Talep Tahmini: YZ, stok yönetiminde öngörü sağlayarak", 65, RIGHT, False),
            ("verimliliği artırmaktadır.", 75, 220, False),
            ("• Sanal Asistanlar: Müşteri desteğinde hızlı hizmet sunar.", 65, RIGHT, False),
        ],
    )
    nodes = structure.classify_blocks([_body_block("b0", 1), block])
    items = [n for n in nodes if n.role == BlockRole.LIST_ITEM]
    assert len(items) == 2
    assert items[1].text.startswith("• Sanal Asistanlar")


def test_stacked_notes_split_at_the_next_number_only():
    lines = [
        "1 Gazi Üniversitesi, Bilgisayar ve Öğretim Teknolojileri Eğitimi Bölümü,",
        "2019 yılında kurulan merkez, Ankara, Türkiye.",
        "2 Gazi Üniversitesi, Fen Fakültesi, Fizik Bölümü, Ankara, Türkiye.",
    ]
    notes = structure._split_notes(lines, lines)
    assert notes == ["\n".join(lines[:2]), lines[2]]


# --- paragraphs across pages ------------------------------------------------


def _para(block):
    return StructuralNode(
        node_id=f"n_{block.block_id}", role=BlockRole.PARAGRAPH, text=block.text,
        source_block_ids=[block.block_id], page=block.page,
    )


def _layout_blocks(page):
    # Enough paragraphs for the book's measure and indent style to be known.
    return [_body_block(f"p{page}_m{i}", page) for i in range(6)]


def test_a_running_head_between_two_pages_does_not_end_the_paragraph():
    first = _body_block("p1_b9", 1)
    first.text = first.text.replace("son satır burada", "son satır ve")
    second = _body_block("p2_b1", 2, first_x0=LEFT, first="devam")
    head = StructuralNode(node_id="h", role=BlockRole.HEADER, text="8 | Kitap", page=2, source_block_ids=["p2_h"])
    blocks = {b.block_id: b for b in [first, second, *_layout_blocks(1), *_layout_blocks(2)]}
    merged = reconstruct_paragraphs([_para(first), head, _para(second)], blocks_by_id=blocks)
    assert [n.role for n in merged] == [BlockRole.PARAGRAPH, BlockRole.HEADER]
    assert merged[0].source_block_ids == ["p1_b9", "p2_b1"]


def test_a_line_that_stops_short_of_the_margin_ends_there():
    byline = _block("p1_b1", [("Betül ERSÖZ", 326, RIGHT, False)])
    next_line = _block("p1_b2", [("Prof. Dr. Elif ORHAN", 284, RIGHT, False)])
    blocks = {b.block_id: b for b in [byline, next_line, *_layout_blocks(1)]}
    merged = reconstruct_paragraphs([_para(byline), _para(next_line)], blocks_by_id=blocks)
    assert len(merged) == 2


def test_an_indented_line_opens_a_new_paragraph_even_without_a_full_stop():
    first = _body_block("p1_b1", 1)  # ends "son satır burada": no full stop
    second = _body_block("p1_b2", 1, first="Yeni")
    blocks = {b.block_id: b for b in [first, second, *_layout_blocks(1)]}
    merged = reconstruct_paragraphs([_para(first), _para(second)], blocks_by_id=blocks)
    assert len(merged) == 2


def test_a_list_item_finished_in_the_next_block_keeps_the_items_after_it():
    item = StructuralNode(
        node_id="i1", role=BlockRole.LIST_ITEM,
        text="1. Optimize Edilmiş Veri Yapıları: Yapay zekâ algoritmaları, veriye erişim",
        source_block_ids=["b1"], page=1,
    )
    rest = StructuralNode(
        node_id="b2", role=BlockRole.PARAGRAPH,
        text="sürecinde veri yapılarını optimize eder.\n2. Otonom Veri Yapıları: Makine öğrenimi\nyöntemleri uyum sağlar.",
        source_block_ids=["b2"], page=1,
    )
    merged = reconstruct_paragraphs([item, rest])
    assert [n.role for n in merged] == [BlockRole.LIST_ITEM, BlockRole.LIST_ITEM]
    assert merged[0].text.endswith("optimize eder.")
    assert merged[1].text.startswith("2. Otonom")


# --- tables -----------------------------------------------------------------


def test_a_table_loses_its_empty_columns_and_its_caption_row():
    rows = [
        ["Tablo 1: Literatür Tablosu", "", "", ""],
        ["Yazar ve Yıl", "", "Başlık", ""],
        ["Highsmith (2002)", "", "Agile Yazılım", ""],
    ]
    assert tables._caption_row(rows) == "Tablo 1: Literatür Tablosu"
    assert tables._drop_empty_columns(rows[1:]) == [
        ["Yazar ve Yıl", "Başlık"],
        ["Highsmith (2002)", "Agile Yazılım"],
    ]


# --- the package ------------------------------------------------------------


def test_names_keep_their_letters():
    assert slugify("ÖNSÖZ", "x") == "onsoz"
    assert slugify("YAPAY ZEKÂ VE MAKİNE ÖĞRENİMİ", "x") == "yapay-zeka-ve-makine-ogrenimi"
    assert len(slugify("UZUN " * 60, "x")) <= 80


def _render(nodes):
    chapter = Chapter(title="t", nodes=nodes, filename="c.xhtml")
    return render_chapter_body(chapter, "c.xhtml", {}, {})


def _item(text):
    return StructuralNode(node_id=text[:8], role=BlockRole.LIST_ITEM, text=text)


def test_bullets_under_a_numbered_label_nest_inside_it_and_numbering_carries_on():
    html = _render([
        _item("2. Finans ve Bankacılık:"),
        _item("• Dolandırıcılık Tespiti: anomali tespiti."),
        _item("• Yatırım Yönetimi: veri analizleri."),
        _item("3. Üretim ve Otomotiv:"),
        _item("• Öngörücü Bakım: arıza riskini azaltır."),
    ])
    assert html.startswith('<ol start="2">')
    assert html.count("<ol") == 1 and html.count("<ul>") == 2
    assert "<li>Finans ve Bankacılık:<ul><li>Dolandırıcılık" in html


def test_a_figure_carries_its_caption():
    images = {"p1_img1": {"ext": "png", "path": "/nonexistent"}}
    chapter = Chapter(
        title="t",
        nodes=[
            StructuralNode(node_id="i", role=BlockRole.IMAGE, image_ref="p1_img1"),
            StructuralNode(node_id="c", role=BlockRole.CAPTION, text="Şekil 1. Motor çeşitleri"),
        ],
        filename="c.xhtml",
    )
    html = render_chapter_body(chapter, "c.xhtml", {}, images)
    assert html == (
        '<figure><img src="../images/p1_img1.png" alt=""/>'
        "<figcaption>Şekil 1. Motor çeşitleri</figcaption></figure>"
    )


def test_stale_metadata_is_not_taken_for_the_title():
    opening = "YAPAY ZEKÂ VE MAKİNE ÖĞRENİMİ İLE MÜHENDİSLİKTE YENİLİKÇİ YAKLAŞIMLAR EDİTÖRLER"
    assert not analyze._metadata_title_is_plausible("ÖNK", opening)
    assert not analyze._metadata_title_is_plausible("Microsoft Word - taslak.docx", opening)
    assert analyze._metadata_title_is_plausible("Yapay Zeka ve Makine Öğrenimi", opening)


def test_a_link_wrapped_to_the_margin_does_not_open_a_reference():
    assert _LINK_LINE_RE.match("https://home.web.cern.ch/news/news/cern/sparking-future")
    assert not _LINK_LINE_RE.match("Choudhary, A., Fox, G. C., & Hey, T. (2023).")
