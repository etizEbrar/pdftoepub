from app.models.document import Block, BlockRole, Span, StructuralNode
from app.pipeline.headings import (
    assign_heading_levels,
    merge_division_numbers,
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
