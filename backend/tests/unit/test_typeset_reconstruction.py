"""Regressions from a realistically typeset book.

Each test here corresponds to a defect found by converting
`build_hard_typeset_book` and reading the generated XHTML — the fixtures that
test one feature on a clean page all passed while these were broken.
"""

from __future__ import annotations

from app.models.document import Block, BlockRole, Span, StructuralNode
from app.pipeline.headings import merge_division_numbers
from app.pipeline.paragraphs import reconstruct_paragraphs
from app.pipeline.verse import detect_verse


def _line_block(
    block_id: str,
    text: str,
    x0: float,
    y0: float,
    width: float,
    size: float = 11.0,
    page: int = 1,
) -> Block:
    bbox = (x0, y0, x0 + width, y0 + size + 4)
    span = Span(
        text=text, bbox=bbox, font="Helvetica", font_size=size,
        bold=False, italic=False, baseline=y0 + size, line_break_after=True,
    )
    return Block(
        block_id=block_id, page=page, page_width=612, page_height=792, bbox=bbox,
        kind="text", text=text, spans=[span], font="Helvetica", font_size=size,
    )


def _nodes_for(blocks: list[Block]) -> list[StructuralNode]:
    return [
        StructuralNode(
            node_id=f"n_{b.block_id}", role=BlockRole.PARAGRAPH, text=b.text,
            source_block_ids=[b.block_id], page=b.page,
        )
        for b in blocks
    ]


class TestProseIsNotVerse:
    """A run of short, ragged, *end-stopped* lines is prose, not poetry.

    Narrow-set prose — dialogue, aphorisms, consecutive short sentences — is
    short and ragged exactly like verse. Only enjambment separates them, and it
    was measured but never enforced, so ordinary paragraphs came out as
    <br/>-separated verse.
    """

    @staticmethod
    def _end_stopped_prose() -> list[Block]:
        return [
            _line_block("s1", "Bir şey söyleyecekti… ama vazgeçti.", 90, 130, 210),
            _line_block("s2", "Sonra durdu... ve bekledi.", 79, 147, 158),
            _line_block("s3", "Uzun bir sessizlik. . . kimse konuşmadı.", 79, 164, 232),
            _line_block("s4", "“Gitmeliyiz,” dedi — sesi titriyordu.", 79, 181, 219),
            # Full-measure line, so the short ones above are genuinely short
            # relative to the column — the same geometry that fooled the
            # detector in the real book.
            _line_block(
                "s5",
                "Sabahın ilk saatlerinde sokaklar bomboştu ve rüzgâr geçiyordu.",
                79, 198, 430,
            ),
        ]

    def test_short_end_stopped_sentences_stay_prose(self):
        blocks = self._end_stopped_prose()
        nodes = _nodes_for(blocks)
        count = detect_verse(nodes, {b.block_id: b for b in blocks})

        assert count == 0, "consecutive complete sentences were turned into verse"
        assert all(n.role == BlockRole.PARAGRAPH for n in nodes)

    def test_genuine_enjambed_verse_is_still_detected(self):
        """The guard must not be so strict that real poetry is lost.

        The full-measure prose block is what establishes the column width the
        poem's lines are judged short against; without it there is nothing to
        be short *of*.
        """
        blocks = [
            _line_block("v1", "Because I could not stop for Death", 72, 130, 184),
            _line_block("v2", "He kindly stopped for me", 92, 148, 132),
            _line_block("v3", "The Carriage held but just Ourselves", 72, 166, 195),
            _line_block("v4", "And Immortality", 92, 184, 83),
            _line_block(
                "p1",
                "This closing paragraph is ordinary prose running to the margin.",
                72, 210, 430,
            ),
        ]
        nodes = _nodes_for(blocks)
        assert detect_verse(nodes, {b.block_id: b for b in blocks}) == 1

    def test_author_punctuation_survives_the_prose_path_verbatim(self):
        """The three ellipsis forms are the author's; none may be rewritten."""
        blocks = self._end_stopped_prose()
        nodes = _nodes_for(blocks)
        detect_verse(nodes, {b.block_id: b for b in blocks})
        merged = reconstruct_paragraphs(nodes)
        text = " ".join(n.text for n in merged)

        assert "…" in text, "the single-character ellipsis was lost"
        assert "..." in text, "the three-period ellipsis was rewritten"
        assert ". . ." in text, "the spaced ellipsis was collapsed"
        assert "—" in text and "“" in text


class TestDivisionNumberMerging:
    """"1" set above a chapter title belongs to that title.

    The number is usually set no larger than the body, so it classifies as a
    paragraph. Requiring both sides to be headings stranded it as a stray
    <p>1</p> at the end of the previous chapter, and left three chapters all
    called "Sisin İçinden" in the navigation.
    """

    @staticmethod
    def _numeral_then_title(number_role: BlockRole) -> list[StructuralNode]:
        return [
            StructuralNode(node_id="n1", role=number_role, text="1",
                           source_block_ids=["b1"], page=3),
            StructuralNode(node_id="n2", role=BlockRole.HEADING, text="Sisin İçinden",
                           source_block_ids=["b2"], page=3, level=1),
        ]

    def test_a_body_sized_numeral_is_folded_into_the_heading(self):
        nodes = self._numeral_then_title(BlockRole.PARAGRAPH)
        assert merge_division_numbers(nodes) == 1
        assert len(nodes) == 1
        assert nodes[0].text == "1 Sisin İçinden"
        assert nodes[0].role == BlockRole.HEADING

    def test_a_heading_sized_numeral_still_merges(self):
        nodes = self._numeral_then_title(BlockRole.HEADING)
        assert merge_division_numbers(nodes) == 1
        assert nodes[0].text == "1 Sisin İçinden"

    def test_no_punctuation_is_invented_when_joining(self):
        nodes = self._numeral_then_title(BlockRole.PARAGRAPH)
        merge_division_numbers(nodes)
        assert nodes[0].text == "1 Sisin İçinden", "a full stop the author never set"

    def test_a_numeral_on_another_page_is_not_pulled_into_the_heading(self):
        nodes = [
            StructuralNode(node_id="n1", role=BlockRole.PARAGRAPH, text="1",
                           source_block_ids=["b1"], page=2),
            StructuralNode(node_id="n2", role=BlockRole.HEADING, text="Sisin İçinden",
                           source_block_ids=["b2"], page=3, level=1),
        ]
        assert merge_division_numbers(nodes) == 0
        assert len(nodes) == 2

    def test_ordinary_prose_before_a_heading_is_left_alone(self):
        nodes = [
            StructuralNode(node_id="n1", role=BlockRole.PARAGRAPH,
                           text="Kimse acele etmiyordu bu saatte.",
                           source_block_ids=["b1"], page=3),
            StructuralNode(node_id="n2", role=BlockRole.HEADING, text="Sisin İçinden",
                           source_block_ids=["b2"], page=3, level=1),
        ]
        assert merge_division_numbers(nodes) == 0
        assert len(nodes) == 2


class TestQuoteReconstruction:
    """A wrapped extract is one blockquote, not one per line."""

    def test_consecutive_quote_lines_merge_into_a_single_quote(self):
        nodes = [
            StructuralNode(node_id="q1", role=BlockRole.QUOTE,
                           text="Şehir, kendini hatırlamayanların şehridir,",
                           source_block_ids=["b1"], page=3),
            StructuralNode(node_id="q2", role=BlockRole.QUOTE,
                           text="demişti yaşlı adam, kimse dinlemezken.",
                           source_block_ids=["b2"], page=3),
        ]
        merged = reconstruct_paragraphs(nodes)
        quotes = [n for n in merged if n.role == BlockRole.QUOTE]
        assert len(quotes) == 1, "the extract was split into one quote per line"
        assert quotes[0].text == (
            "Şehir, kendini hatırlamayanların şehridir, demişti yaşlı adam, "
            "kimse dinlemezken."
        )

    def test_a_paragraph_never_absorbs_the_quote_that_follows_it(self):
        """A change of role is a boundary even mid-sentence."""
        nodes = [
            StructuralNode(node_id="p1", role=BlockRole.PARAGRAPH,
                           text="Yaşlı adam şunu söyledi,",
                           source_block_ids=["b1"], page=3),
            StructuralNode(node_id="q1", role=BlockRole.QUOTE,
                           text="şehir kendini hatırlamayanların şehridir.",
                           source_block_ids=["b2"], page=3),
        ]
        merged = reconstruct_paragraphs(nodes)
        assert len(merged) == 2
        assert merged[0].role == BlockRole.PARAGRAPH
        assert merged[1].role == BlockRole.QUOTE

    def test_paragraph_merging_is_unaffected(self):
        nodes = [
            StructuralNode(node_id="p1", role=BlockRole.PARAGRAPH,
                           text="Sabahın ilk saatlerinde sokaklar bomboştu ve",
                           source_block_ids=["b1"], page=1),
            StructuralNode(node_id="p2", role=BlockRole.PARAGRAPH,
                           text="rüzgâr pencerelerin önünden geçiyordu.",
                           source_block_ids=["b2"], page=1),
        ]
        merged = reconstruct_paragraphs(nodes)
        assert len(merged) == 1
        assert merged[0].text == (
            "Sabahın ilk saatlerinde sokaklar bomboştu ve rüzgâr "
            "pencerelerin önünden geçiyordu."
        )


class TestSymbolMarkedFootnotes:
    """A note marked "*" is a note, not a bullet point.

    "* Yazarın notu: ..." matches the bullet pattern as well as the note
    pattern, and the bullet rule was tested first. The note therefore became a
    list item and its marker was eaten as the bullet character — which also
    left the reference in the body with nothing to link to.
    """

    @staticmethod
    def _page_with_symbol_note() -> list[Block]:
        body = [
            _line_block(
                "b1",
                "Bu satır bir dipnota atıfta bulunur * ve devam eder.",
                79, 120, 430, size=11.0,
            ),
            _line_block(
                "b2",
                "Sabahın ilk saatlerinde sokaklar bomboştu ve rüzgâr geçiyordu.",
                79, 140, 430, size=11.0,
            ),
        ]
        # Small type, low on the page: the footnote zone.
        note = _line_block(
            "b3", "* Yazarın notu: bu bir açıklamadır.", 79, 700, 260, size=8.0
        )
        return body + [note]

    def test_a_symbol_marked_note_is_classified_as_a_footnote(self):
        from app.pipeline.structure import classify_blocks

        nodes = classify_blocks(self._page_with_symbol_note())
        roles = {n.text[:12]: n.role for n in nodes}
        note_nodes = [n for n in nodes if n.text.startswith("*")]

        assert note_nodes, f"the note vanished entirely; roles were {roles}"
        assert note_nodes[0].role == BlockRole.FOOTNOTE, (
            f"the note became {note_nodes[0].role}, not a footnote"
        )

    def test_the_marker_character_is_not_consumed(self):
        """Losing the "*" makes the note impossible to match to its reference."""
        from app.pipeline.structure import classify_blocks

        nodes = classify_blocks(self._page_with_symbol_note())
        note = next(n for n in nodes if "Yazarın notu" in n.text)
        assert note.text.lstrip().startswith("*"), (
            f"marker stripped: {note.text!r}"
        )

    def test_a_real_bullet_list_is_still_a_list(self):
        """The reordering must not turn ordinary bulleted lists into notes."""
        from app.pipeline.structure import classify_blocks

        blocks = [
            _line_block(
                "b1",
                "Sabahın ilk saatlerinde sokaklar bomboştu ve rüzgâr geçiyordu.",
                79, 120, 430, size=11.0,
            ),
            # Body-sized, high on the page: a list, not a note.
            _line_block("b2", "* birinci madde", 79, 150, 160, size=11.0),
            _line_block("b3", "* ikinci madde", 79, 170, 160, size=11.0),
        ]
        nodes = classify_blocks(blocks)
        bullets = [n for n in nodes if n.text.startswith("*")]
        assert bullets, "the bullets disappeared"
        assert all(n.role == BlockRole.LIST_ITEM for n in bullets), (
            f"bullets became {[n.role for n in bullets]}"
        )
