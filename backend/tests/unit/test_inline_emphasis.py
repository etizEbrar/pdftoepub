from app.models.document import Block, Span
from app.pipeline.epub.render import _escape_with_emphasis, render_inline
from app.pipeline.footnotes import (
    BOLD_CLOSE,
    BOLD_OPEN,
    ITALIC_CLOSE,
    ITALIC_OPEN,
    mark_reference_candidates,
    strip_emphasis_sentinels,
)

BODY = 10.0


def _span(text: str, *, bold: bool = False, italic: bool = False, size: float = BODY, brk: bool = False):
    return Span(
        text=text,
        bbox=(0, 0, 50, 12),
        font="Times",
        font_size=size,
        bold=bold,
        italic=italic,
        baseline=10.0,
        line_break_after=brk,
    )


def _block(spans: list[Span]) -> Block:
    return Block(
        block_id="b1",
        page=1,
        page_width=600,
        page_height=800,
        bbox=(0, 100, 500, 120),
        kind="text",
        text="".join(s.text for s in spans),
        spans=spans,
        font="Times",
        font_size=BODY,
    )


def _noop_href(_node_id: str) -> str:
    return "#x"


# --- sentinel planting ----------------------------------------------------

def test_mixed_style_block_gets_emphasis_sentinels():
    block = _block([_span("plain "), _span("emphasised", italic=True), _span(" tail", brk=True)])
    mark_reference_candidates([block], BODY)
    assert ITALIC_OPEN in block.text and ITALIC_CLOSE in block.text
    assert strip_emphasis_sentinels(block.text) == "plain emphasised tail"


def test_uniformly_styled_block_gets_no_sentinels():
    """Regression: sentinels in uniformly styled text broke downstream pattern
    matching (endnote-section headings stopped being recognised)."""
    block = _block([_span("Notes", bold=True, brk=True)])
    mark_reference_candidates([block], BODY)
    assert BOLD_OPEN not in block.text
    assert block.text == "Notes"


def test_consecutive_same_style_spans_become_one_run():
    block = _block([_span("one ", italic=True), _span("two", italic=True, brk=True)])
    mark_reference_candidates([block], BODY)
    assert block.text.count(ITALIC_OPEN) <= 1


def test_styles_are_closed_at_a_line_break():
    block = _block(
        [_span("first", italic=True, brk=True), _span("second"), _span(" more", brk=True)]
    )
    mark_reference_candidates([block], BODY)
    first_line = block.text.split("\n")[0]
    assert first_line.count(ITALIC_OPEN) == first_line.count(ITALIC_CLOSE)


# --- rendering ------------------------------------------------------------

def test_sentinels_render_as_semantic_tags():
    text = f"a {ITALIC_OPEN}b{ITALIC_CLOSE} c {BOLD_OPEN}d{BOLD_CLOSE}"
    assert _escape_with_emphasis(text) == "a <em>b</em> c <strong>d</strong>"


def test_author_text_cannot_smuggle_markup_through():
    assert _escape_with_emphasis("<script>alert(1)</script> & co") == (
        "&lt;script&gt;alert(1)&lt;/script&gt; &amp; co"
    )


def test_unclosed_emphasis_is_closed_rather_than_emitting_invalid_xhtml():
    assert _escape_with_emphasis(f"{ITALIC_OPEN}never closed") == "<em>never closed</em>"


def test_stray_close_sentinel_is_dropped():
    assert _escape_with_emphasis(f"stray{BOLD_CLOSE} close") == "stray close"


def test_surviving_soft_hyphen_is_removed_at_render():
    assert _escape_with_emphasis("mid­word") == "midword"


def test_render_inline_combines_emphasis_with_note_references():
    text = f"{ITALIC_OPEN}cited{ITALIC_CLOSE}{{{{NOTEREF:n1:ref1:1}}}} tail"
    out = render_inline(text, _noop_href)
    assert "<em>cited</em>" in out
    assert 'epub:type="noteref"' in out
