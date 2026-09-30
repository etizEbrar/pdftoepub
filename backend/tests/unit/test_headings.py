from app.models.document import Block, BlockRole, Span, StructuralNode
from app.pipeline.headings import (
    assign_heading_levels,
    merge_division_numbers,
    merge_wrapped_titles,
    score_heading,
)

PAGE_W, PAGE_H = 396.0, 561.0
BODY = 8.85


def _block(
    text: str,
    *,
    size: float = BODY,
    x0: float = 28.0,
    width: float = 250.0,
    y: float = 200.0,
    bold: bool = False,
    centred: bool = False,
) -> Block:
    if centred:
        x0 = (PAGE_W - width) / 2
    bbox = (x0, y, x0 + width, y + size + 4)
    spans = [
        Span(
            text=line,
            bbox=bbox,
            font="helv",
            font_size=size,
            bold=bold,
            italic=False,
            baseline=y + size,
            line_break_after=True,
        )
        for line in text.split("\n")
    ]
    return Block(
        block_id="b1",
        page=1,
        page_width=PAGE_W,
        page_height=PAGE_H,
        bbox=bbox,
        kind="text",
        text=text,
        spans=spans,
        font="helv",
        font_size=size,
        bold=bold,
    )


def _score(block: Block, *, sparse: bool = False, isolated: bool = True, first: bool = False):
    gap = 40.0 if isolated else 2.0
    return score_heading(
        block,
        BODY,
        gap_above=gap,
        gap_below=gap,
        line_gap=3.0,
        page_char_count=120 if sparse else 2000,
        is_first_content_block_on_page=first,
    )


# --- what should be a heading --------------------------------------------

def test_display_type_chapter_title_scores_as_a_heading():
    evidence = _score(_block("Kurban", size=28.9, centred=True), sparse=True, first=True)
    assert evidence.score >= 0.55
    assert "display-type" in evidence.signals


def test_division_word_is_recognised_across_languages():
    for text in ("Bölüm 3", "Chapter 4", "Kapitel 2", "Partie II"):
        evidence = _score(_block(text, size=BODY * 1.15))
        assert "division-word" in evidence.signals, text
        assert evidence.score >= 0.55, text


def test_all_caps_short_line_is_a_heading():
    evidence = _score(_block("TEŞEKKÜR", size=BODY * 1.15))
    assert evidence.score >= 0.55
    assert "all-caps" in evidence.signals


# --- what must NOT be a heading ------------------------------------------

def test_geometry_alone_never_makes_a_heading():
    """A centred, isolated line on a sparse page with body-sized type is an
    epigraph or a series line, not a heading."""
    evidence = _score(_block("184 ı MONA ı ROMAN ı 73", centred=True), sparse=True, first=True)
    assert evidence.score == 0.0
    assert "geometry-only" in evidence.signals


def test_url_is_never_a_heading():
    evidence = _score(_block("www.example.com", size=BODY * 1.2, centred=True), sparse=True)
    assert evidence.score == 0.0


def test_epigraph_opening_with_a_quote_is_never_a_heading():
    evidence = _score(
        _block('"Her şey onlar böyle olduğu için böyle . . ."', size=BODY * 1.2, centred=True),
        sparse=True,
    )
    assert evidence.score == 0.0


def test_numbered_list_block_is_not_a_heading():
    """Regression: "1. First / 2. Second" matched the numbered-title pattern and
    outscored the threshold on an otherwise empty page."""
    evidence = _score(_block("1. First\n2. Second"), sparse=True)
    assert evidence.score == 0.0


def test_numbered_note_entry_ending_in_a_full_stop_is_not_a_heading():
    evidence = _score(_block("1. Endnote 1 for chapter 1, with a full citation."), sparse=True)
    assert evidence.score < 0.55


def test_long_sentence_set_apart_is_not_a_heading():
    text = "This sentence is far too long to be a heading and simply happens to sit alone"
    evidence = _score(_block(text, size=BODY * 1.2), sparse=True)
    assert evidence.score < 0.55


def test_ordinary_body_paragraph_is_not_a_heading():
    evidence = _score(_block("In the first hours of morning the streets stood empty."), isolated=False)
    assert evidence.score < 0.55


# --- division number merging ---------------------------------------------

def _heading_node(node_id: str, text: str, level: int = 1, page: int = 14, scale: float = 3.2):
    return StructuralNode(
        node_id=node_id,
        role=BlockRole.HEADING,
        text=text,
        level=level,
        page=page,
        heading_scale=scale,
        source_block_ids=[node_id],
    )


def test_lone_chapter_number_is_folded_into_the_title():
    nodes = [_heading_node("n1", "1"), _heading_node("n2", "Kurban")]
    assert merge_division_numbers(nodes) == 1
    assert len(nodes) == 1
    assert nodes[0].text == "1 Kurban"
    assert nodes[0].source_block_ids == ["n1", "n2"]


def test_numbers_on_different_pages_are_not_merged():
    nodes = [_heading_node("n1", "1", page=14), _heading_node("n2", "Kurban", page=15)]
    assert merge_division_numbers(nodes) == 0
    assert len(nodes) == 2


def test_two_titles_in_a_row_are_not_merged():
    nodes = [_heading_node("n1", "Kurban"), _heading_node("n2", "Ben")]
    assert merge_division_numbers(nodes) == 0
    assert len(nodes) == 2


# --- level assignment -----------------------------------------------------

def test_similar_scales_collapse_to_one_level():
    """A one-off cover title must not monopolise h1 and demote real chapters."""
    nodes = [
        _heading_node("cover", "PİRAYE", scale=3.53, page=1),
        _heading_node("c1", "1. Kurban", scale=3.27, page=14),
        _heading_node("c2", "2. Ben", scale=3.27, page=100),
    ]
    assign_heading_levels(nodes)
    assert {n.level for n in nodes} == {1}


def test_distinct_scales_produce_distinct_levels():
    nodes = [
        _heading_node("a", "Part", scale=3.0),
        _heading_node("b", "Chapter", scale=1.8),
        _heading_node("c", "Section", scale=1.15),
    ]
    assign_heading_levels(nodes)
    assert [n.level for n in nodes] == [1, 2, 3]


def test_levels_never_exceed_four():
    nodes = [_heading_node(f"n{i}", f"H{i}", scale=4.0 - i * 0.5) for i in range(8)]
    assign_heading_levels(nodes)
    assert all(1 <= n.level <= 4 for n in nodes)


class TestDisplayTitleBlocks:
    """A chapter title set over several display lines is one title, not several.

    Measured on a real 168-page Turkish edited volume: every chapter opens with
    "BÖLÜM n" at 14pt over a bold 12pt title running two or three lines, then
    the author names and DOI at the same 12pt but *not* bold. Folding only the
    first line in truncated every title in the navigation ("BÖLÜM 5 ELEKTRİK
    MOTORLARININ ARIZALARININ TESPİTİNDE", losing "YAPAY ZEKA YÖNTEMLERİNİN
    KULLANILMASI"), and left the lines that failed to score as headings behind
    as stray paragraphs. Boldness is what separates the title from the byline.
    """

    @staticmethod
    def _node(node_id, text, role=BlockRole.PARAGRAPH, *, bold=False, page=94):
        return StructuralNode(
            node_id=node_id, role=role, text=text, page=page,
            bold=bold, source_block_ids=[node_id],
        )

    @staticmethod
    def _blocks(*specs):
        return {
            bid: Block(
                block_id=bid, page=94, page_width=PAGE_W, page_height=PAGE_H,
                bbox=(0, 0, 100, 10), kind="text", text=text,
                font_size=size, bold=bold,
            )
            for bid, text, size, bold in specs
        }

    def test_every_bold_title_line_joins_the_division_number(self):
        nodes = [
            self._node("n1", "BÖLÜM 4", BlockRole.HEADING, bold=True),
            self._node("n2", "ELEKTRİKLİ ARAÇLARDA KULLANILAN AKI", bold=True),
            self._node("n3", "ANAHTARLAMALI MOTOR ÇEŞİTLERİ ÜZERİNE BİR",
                       BlockRole.HEADING, bold=True),
            self._node("n4", "İNCELEME", bold=True),
            self._node("n5", "Sümeyye ÇARKIT1,2"),
        ]
        blocks = self._blocks(
            ("n1", "BÖLÜM 4", 14.0, True),
            ("n2", "ELEKTRİKLİ ARAÇLARDA KULLANILAN AKI", 12.0, True),
            ("n3", "ANAHTARLAMALI MOTOR ÇEŞİTLERİ ÜZERİNE BİR", 12.0, True),
            ("n4", "İNCELEME", 12.0, True),
            ("n5", "Sümeyye ÇARKIT1,2", 12.0, False),
        )
        assert merge_division_numbers(nodes, blocks) == 1
        assert nodes[0].text == (
            "BÖLÜM 4 ELEKTRİKLİ ARAÇLARDA KULLANILAN AKI "
            "ANAHTARLAMALI MOTOR ÇEŞİTLERİ ÜZERİNE BİR İNCELEME"
        )
        assert nodes[0].role == BlockRole.HEADING

    def test_the_byline_under_the_title_is_not_swallowed(self):
        nodes = [
            self._node("n1", "BÖLÜM 4", BlockRole.HEADING, bold=True),
            self._node("n2", "ELEKTRİKLİ ARAÇLARDA KULLANILAN AKI", bold=True),
            self._node("n5", "Sümeyye ÇARKIT1,2"),
        ]
        blocks = self._blocks(
            ("n1", "BÖLÜM 4", 14.0, True),
            ("n2", "ELEKTRİKLİ ARAÇLARDA KULLANILAN AKI", 12.0, True),
            ("n5", "Sümeyye ÇARKIT1,2", 12.0, False),
        )
        merge_division_numbers(nodes, blocks)
        assert [n.text for n in nodes] == [
            "BÖLÜM 4 ELEKTRİKLİ ARAÇLARDA KULLANILAN AKI",
            "Sümeyye ÇARKIT1,2",
        ]

    def test_a_title_line_in_another_size_does_not_join(self):
        """A bold run-in lead at a different size belongs to the body, not the title."""
        nodes = [
            self._node("n1", "BÖLÜM 4", BlockRole.HEADING, bold=True),
            self._node("n2", "ELEKTRİKLİ ARAÇLARDA KULLANILAN AKI", bold=True),
            self._node("n3", "Giriş.", bold=True),
        ]
        blocks = self._blocks(
            ("n1", "BÖLÜM 4", 14.0, True),
            ("n2", "ELEKTRİKLİ ARAÇLARDA KULLANILAN AKI", 12.0, True),
            ("n3", "Giriş.", 9.0, True),
        )
        merge_division_numbers(nodes, blocks)
        assert nodes[0].text == "BÖLÜM 4 ELEKTRİKLİ ARAÇLARDA KULLANILAN AKI"
        assert nodes[-1].text == "Giriş."


class TestNonHeadings:
    """Lines that carry no chapter, however they are set."""

    def test_an_isbn_line_is_never_a_heading(self):
        block = _block("978-625-378-117-0 ISBN: 978-625-378-117-0",
                       size=BODY * 1.4, bold=True, centred=True)
        assert _score(block, sparse=True, first=True).score == 0.0

    def test_a_citation_tail_is_never_a_heading(self):
        """"vd., 2019)" is the end of a wrapped citation, not a chapter."""
        block = _block("vd., 2019)", size=BODY * 1.2, bold=True, centred=True)
        assert _score(block, sparse=True, first=True).score == 0.0


class TestNumberedSectionsUnderLabelledChapters:
    """A book that says "BÖLÜM 2" has told us what its chapters are.

    In such a book "1. GİRİŞ" is the first section *of* a chapter, not a
    chapter. Left at chapter level it split a real volume's navigation at the
    introduction of two different chapters, so the same book listed both
    "BÖLÜM 5 ..." and a bare "1. GİRİŞ" as top-level entries. Where a book
    never labels a division, "1. Kurban" really is the chapter and must stay.
    """

    @staticmethod
    def _h(text, level=2):
        return StructuralNode(
            node_id=text[:6], role=BlockRole.HEADING, text=text,
            level=level, heading_scale=1.27, source_block_ids=[text[:6]],
        )

    def test_a_numbered_section_sits_below_a_labelled_chapter(self):
        nodes = [
            self._h("BÖLÜM 1 BİLİM VE TEKNOLOJİDE DÖNÜŞÜMÜN GÜCÜ"),
            self._h("1. GİRİŞ"),
            self._h("BÖLÜM 2 ÇEVİK PROJE YÖNETİMİ"),
            self._h("2. TEMEL ARAŞTIRMA VE BULGULAR"),
        ]
        assign_heading_levels(nodes)
        by_text = {n.text: n.level for n in nodes}
        chapter = by_text["BÖLÜM 1 BİLİM VE TEKNOLOJİDE DÖNÜŞÜMÜN GÜCÜ"]
        assert by_text["1. GİRİŞ"] > chapter
        assert by_text["2. TEMEL ARAŞTIRMA VE BULGULAR"] > chapter

    def test_an_unlabelled_book_keeps_its_numbered_chapters(self):
        nodes = [self._h("1. Kurban", level=1), self._h("2. Sisin İçinden", level=1)]
        assign_heading_levels(nodes)
        assert [n.level for n in nodes] == [1, 1]


class TestWrappedTitles:
    """One title that wrapped is one heading.

    A 31pt cover title set over two lines arrived as two level-1 headings, so a
    real book opened with two navigation entries that were halves of its own
    name — and the split level had to reckon with two "chapters" that were one
    title. Lines of one title share a page, a size and a weight, and a
    continuation never carries a number of its own.
    """

    @staticmethod
    def _nodes(*texts, page=1):
        return [
            StructuralNode(node_id=f"n{i}", role=BlockRole.HEADING, text=t,
                           page=page, bold=True, source_block_ids=[f"b{i}"])
            for i, t in enumerate(texts)
        ]

    @staticmethod
    def _blocks(*specs, page=1):
        return {
            f"b{i}": Block(block_id=f"b{i}", page=page, page_width=PAGE_W,
                           page_height=PAGE_H, bbox=(0, 0, 100, 10), kind="text",
                           text=t, font_size=size, bold=True)
            for i, (t, size) in enumerate(specs)
        }

    def test_two_lines_of_one_cover_title_become_one_heading(self):
        nodes = self._nodes("YAPAY ZEKÂ VE MAKİNE ÖĞRENİMİ İLE",
                            "MÜHENDİSLİKTE YENİLİKÇİ YAKLAŞIMLAR")
        blocks = self._blocks(("YAPAY ZEKÂ VE MAKİNE ÖĞRENİMİ İLE", 31.0),
                              ("MÜHENDİSLİKTE YENİLİKÇİ YAKLAŞIMLAR", 31.0))
        assert merge_wrapped_titles(nodes, blocks) == 1
        assert len(nodes) == 1
        assert nodes[0].text == (
            "YAPAY ZEKÂ VE MAKİNE ÖĞRENİMİ İLE MÜHENDİSLİKTE YENİLİKÇİ YAKLAŞIMLAR"
        )

    def test_sibling_numbered_headings_stay_apart(self):
        """"1.2." after "1.1." starts a section; it never continues one."""
        nodes = self._nodes("1.1. Fırsatlar ve Zorluklar", "1.2. Açıklanabilir Yapay Zekâ")
        blocks = self._blocks(("1.1. Fırsatlar ve Zorluklar", 12.0),
                              ("1.2. Açıklanabilir Yapay Zekâ", 12.0))
        assert merge_wrapped_titles(nodes, blocks) == 0
        assert len(nodes) == 2

    def test_headings_at_different_sizes_stay_apart(self):
        nodes = self._nodes("ELEKTRİKLİ ARAÇLAR", "1. GİRİŞ")
        blocks = self._blocks(("ELEKTRİKLİ ARAÇLAR", 14.0), ("1. GİRİŞ", 12.0))
        assert merge_wrapped_titles(nodes, blocks) == 0

    def test_a_chapter_already_carrying_its_label_is_left_alone(self):
        nodes = self._nodes("BÖLÜM 3 VERİ YAPILARI", "KAYNAKÇA")
        blocks = self._blocks(("BÖLÜM 3 VERİ YAPILARI", 12.0), ("KAYNAKÇA", 12.0))
        assert merge_wrapped_titles(nodes, blocks) == 0
