"""The pipeline must never invent punctuation — especially an ellipsis.

An ellipsis is the punctuation most likely to be produced accidentally: by
joining lines, by truncating text, or by standing in for content that could not
be read. These tests fail if any stage emits one the source did not contain.
"""

import re

import pytest

from app.models.document import Block, BlockRole, Span, StructuralNode
from app.pipeline.footnotes import link_references, mark_reference_candidates
from app.pipeline.hyphenation import join_lines_with_hyphenation_repair
from app.pipeline.paragraphs import reconstruct_paragraphs
from app.pipeline.structure import _looks_like_thematic_break, classify_blocks

ELLIPSIS_FORMS = [
    ("unicode", "…"),
    ("three dots", "..."),
    ("spaced dots", ". . ."),
    ("two dots", ".."),
]


def _count_dots(text: str) -> int:
    """Total dot characters, the quantity that must never grow."""
    return text.count(".") + text.count("…") * 3


# --- hyphenation ----------------------------------------------------------

def test_line_joining_never_adds_dots():
    for _, form in ELLIPSIS_FORMS:
        lines = [f"first line{form}", "second line continues"]
        before = sum(_count_dots(line) for line in lines)
        after = _count_dots(join_lines_with_hyphenation_repair(lines))
        assert after <= before, f"joining added dots for {form!r}"


def test_hyphenated_join_preserves_a_trailing_ellipsis():
    out = join_lines_with_hyphenation_repair(["Keşke . . .", "Öylece devam"])
    assert ". . ." in out


def test_joining_does_not_fabricate_an_ellipsis_from_separate_full_stops():
    """Two sentences joined across lines must not become an ellipsis."""
    out = join_lines_with_hyphenation_repair(["Bitti.", "Sonra başladı."])
    assert "..." not in out
    assert ". . ." not in out


# --- paragraph reconstruction --------------------------------------------

def _para(node_id: str, text: str, page: int = 1) -> StructuralNode:
    return StructuralNode(
        node_id=node_id, role=BlockRole.PARAGRAPH, text=text, source_block_ids=[node_id], page=page
    )


def test_paragraph_merging_never_adds_dots():
    nodes = [
        _para("a", "cümle devam ediyor"),
        _para("b", "ve burada bitiyor."),
        _para("c", "Yeni paragraf . . ."),
        _para("d", "devamı geliyor"),
    ]
    before = sum(_count_dots(n.text) for n in nodes)
    merged = reconstruct_paragraphs(nodes)
    after = sum(_count_dots(n.text) for n in merged)
    assert after == before, "paragraph merging changed the number of dots"


def test_merging_across_a_page_boundary_never_adds_dots():
    nodes = [_para("a", "sayfa sonunda kesilen cümle", page=1), _para("b", "sonraki sayfada devam", page=2)]
    merged = reconstruct_paragraphs(nodes)
    assert _count_dots(merged[0].text) == 0


# --- marker handling ------------------------------------------------------

def _block_with_spans(spans: list[Span]) -> Block:
    return Block(
        block_id="b1",
        page=1,
        page_width=396,
        page_height=561,
        bbox=(28, 100, 360, 120),
        kind="text",
        text="".join(s.text for s in spans),
        spans=spans,
        font_size=10.0,
    )


def _span(text: str, size: float = 10.0, brk: bool = False) -> Span:
    return Span(
        text=text, bbox=(0, 0, 40, 12), font="T", font_size=size,
        bold=False, italic=False, baseline=10.0, line_break_after=brk,
    )


def test_reference_marking_never_adds_dots():
    block = _block_with_spans([_span("Bir iddia . . . "), _span("1", 6.0, brk=True)])
    before = _count_dots(block.text)
    mark_reference_candidates([block], 10.0)
    assert _count_dots(block.text) == before


def test_unmatched_marker_becomes_a_superscript_not_an_ellipsis():
    """An unresolvable reference must never be replaced by "..." as a
    placeholder for something the engine could not work out."""
    node = _para("a", "Bir iddia9 devam.")
    _, linked = link_references([node])
    assert linked == 0
    assert "{{SUP:9}}" in node.text
    assert "..." not in node.text
    assert "…" not in node.text


# --- thematic breaks ------------------------------------------------------

def _ornament_block(text: str, x0: float = 150.0, width: float = 96.0) -> Block:
    return Block(
        block_id="orn",
        page=1,
        page_width=396,
        page_height=561,
        bbox=(x0, 200, x0 + width, 212),
        kind="text",
        text=text,
        spans=[_span(text, brk=True)],
        font_size=8.85,
    )


def test_centred_ornament_rows_are_recognised_as_scene_breaks():
    """These are real dividers in the book; OCR renders them differently every
    time, which made them look like stray ellipsis junk in the EPUB."""
    for text in (".........", "• • • • •", ".. . • ..", "* * *", "• • • ••"):
        assert _looks_like_thematic_break(_ornament_block(text)), text


def test_prose_containing_an_ellipsis_is_never_a_scene_break():
    for text in ("Keşke . . .", '" Şimdi" denen zamanda . . .', "aşağıya ... Geride kalan"):
        assert not _looks_like_thematic_break(_ornament_block(text)), text


def test_a_left_aligned_dot_row_is_not_a_scene_break():
    """A divider is centred; a row of dots at the margin is something else
    (a leader line in a table of contents, for instance)."""
    assert not _looks_like_thematic_break(_ornament_block(".........", x0=28.0, width=90.0))


def test_two_dots_alone_are_too_few_to_be_a_divider():
    assert not _looks_like_thematic_break(_ornament_block(".."))


# --- end-to-end over the block classifier --------------------------------

def test_classification_never_introduces_dots_into_body_text():
    blocks = [
        Block(
            block_id=f"b{i}",
            page=1,
            page_width=396,
            page_height=561,
            bbox=(28, 100 + i * 20, 360, 114 + i * 20),
            kind="text",
            text=text,
            spans=[_span(text, brk=True)],
            font_size=8.85,
        )
        for i, text in enumerate(
            ["Normal bir cümle burada", "devam ediyor ve bitiyor.", "Yeni bir paragraf . . ."]
        )
    ]
    before = sum(_count_dots(b.text) for b in blocks)
    nodes = classify_blocks(blocks)
    after = sum(_count_dots(n.text) for n in nodes)
    assert after == before


# --- malformed terminal punctuation is surfaced, never rewritten -------------

def test_a_two_dot_ellipsis_after_a_terminal_mark_is_completed():
    """"?.." is an ellipsis that lost a dot leaving the PDF, and is completed.

    This is the single place the engine writes punctuation the source did not
    contain. It was added deliberately and on instruction; the guards below fix
    its scope so it cannot grow into general punctuation rewriting.
    """
    from app.models.document import Block
    from app.pipeline.textrepair import repair_blocks

    block = Block(block_id="b1", page=1, page_width=612, page_height=792,
                  bbox=(72, 100, 500, 120), kind="text",
                  text="Neden?.. dedi ve sustu. Hayır!.. diye bağırdı.", spans=[],
                  font="Helvetica", font_size=11.0)
    repair_blocks([block])

    assert block.text == "Neden?... dedi ve sustu. Hayır!... diye bağırdı."


@pytest.mark.parametrize(
    "text",
    [
        "Neden?... dedi.",          # already three dots
        "Neden?\u2026 dedi.",           # already a real ellipsis character
        "Neden?. dedi.",            # one dot — could be a full stop, not ours to judge
        "Bekledi. . . sonra.",      # spaced ellipsis, author's own typography
        "Bekledi... sonra.",        # plain ellipsis with no terminal mark
        "Bir soru?.... dört.",      # four dots — not the pattern
        "Ne? dedi.",                # nothing to complete
    ],
)
def test_punctuation_the_author_may_have_meant_is_left_alone(text):
    """The completion is narrow by design: exactly two dots, nothing else."""
    from app.models.document import Block
    from app.pipeline.textrepair import repair_blocks

    block = Block(block_id="b1", page=1, page_width=612, page_height=792,
                  bbox=(72, 100, 500, 120), kind="text", text=text, spans=[],
                  font="Helvetica", font_size=11.0)
    repair_blocks([block])
    assert block.text == text, f"{text!r} was altered"


def test_the_completion_is_recorded_as_a_correction():
    """A change to the author's text must appear in the report, not happen quietly."""
    from app.models.document import Block
    from app.pipeline.textrepair import repair_blocks

    block = Block(block_id="b1", page=1, page_width=612, page_height=792,
                  bbox=(72, 100, 500, 120), kind="text", text="Neden?.. dedi.", spans=[],
                  font="Helvetica", font_size=11.0)
    report = repair_blocks([block])
    assert report.applied_count >= 1, "the rewrite was not reported"
