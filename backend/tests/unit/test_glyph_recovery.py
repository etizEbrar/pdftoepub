"""Regressions from a real Turkish engineering book.

Both defects were invisible to every fixture and to EPUBCheck, and both reached
the reader as boxes or blanks.
"""

from __future__ import annotations

import pytest

from app.pipeline import footnotes
from app.pipeline.textrepair import _recover_symbol_font_glyphs, _normalise_text


class TestSymbolFontRecovery:
    """A symbol-encoded font hands back U+F000+code instead of the character.

    The copyright page carried its ISBN twice: once in a normal font and once
    in a barcode font whose digits arrived as private-use codepoints. Every
    reader showed the second one as a row of empty boxes.
    """

    def test_symbol_font_digits_become_the_digits_they_encode(self):
        recovered, unmapped = _recover_symbol_font_glyphs(
            ""
        )
        assert recovered == "978-625"
        assert unmapped == 0

    def test_the_symbol_font_bullet_becomes_a_real_bullet(self):
        assert _recover_symbol_font_glyphs("a  b")[0] == "a • b"

    def test_ordinary_text_is_untouched(self):
        for text in ["normal text", "Türkçe karakterler: çğışöü", "978-625-378"]:
            assert _recover_symbol_font_glyphs(text)[0] == text

    def test_the_pipelines_own_sentinels_are_never_rewritten(self):
        """U+E000-E005 carry note markers and emphasis; mangling them would
        break footnote linking and emit unbalanced markup."""
        text = f"{footnotes.BOLD_OPEN}bold{footnotes.BOLD_CLOSE}"
        assert _recover_symbol_font_glyphs(text)[0] == text
        marked = f"{footnotes.MARKER_OPEN}1{footnotes.MARKER_CLOSE}"
        assert _recover_symbol_font_glyphs(marked)[0] == marked

    def test_unmappable_private_use_characters_are_kept_and_counted(self):
        """Source fidelity: what cannot be decoded is preserved, not deleted."""
        recovered, unmapped = _recover_symbol_font_glyphs("xy")
        assert recovered == "xy"
        assert unmapped == 1

    def test_recovery_runs_as_part_of_normalisation(self):
        out, changes = _normalise_text("")
        assert out == "978"
        assert changes, "the recovery was not recorded as a correction"


class TestSentinelsNeverReachTheReader:
    """<title> and the navigation never pass through the inline renderer."""

    def test_strip_all_sentinels_removes_markers_and_emphasis(self):
        text = (
            f"{footnotes.BOLD_OPEN}ISBN: 978{footnotes.BOLD_CLOSE}"
            f"{footnotes.MARKER_OPEN}1{footnotes.MARKER_CLOSE}"
        )
        cleaned = footnotes.strip_all_sentinels(text)
        assert cleaned == "ISBN: 9781"
        for code in range(0xE000, 0xE006):
            assert chr(code) not in cleaned

    def test_a_chapter_title_carries_no_private_use_characters(self):
        from app.pipeline.epub.builder import _plain_title

        title = _plain_title(f"  {footnotes.BOLD_OPEN}Bölüm 3{footnotes.BOLD_CLOSE}  ")
        assert title == "Bölüm 3"

    @pytest.mark.parametrize("code", list(range(0xE000, 0xE006)))
    def test_no_sentinel_survives_title_building(self, code):
        from app.pipeline.epub.builder import _plain_title

        assert chr(code) not in _plain_title(f"Chapter{chr(code)}One")


class TestUnreferencedNotesStayVisible:
    """A note nothing points at must not be marked as a footnote.

    A reading system may hide epub:type="footnote" content until a noteref
    activates it. A 392-page grammar book's answer key was detected as
    fifty-nine notes with no references, so tagging them as footnotes risked
    hiding sixty pages of content the reader needs.
    """

    @staticmethod
    def _render(backrefs: list[str]) -> str:
        from app.models.document import BlockRole, StructuralNode
        from app.pipeline.epub.builder import Chapter, render_chapter_body

        node = StructuralNode(
            node_id="n1", role=BlockRole.FOOTNOTE, text="was living",
            source_block_ids=["b1"], page=380,
        )
        node.footnote_number = "7"
        node.footnote_backrefs = list(backrefs)
        chapter = Chapter(filename="c1.xhtml", title="Key", nodes=[node])
        return render_chapter_body(chapter, "c1.xhtml", {}, {})

    def test_a_referenced_note_is_still_a_footnote(self):
        out = self._render(["ref1"])
        assert 'epub:type="footnote"' in out
        assert "noteback" in out, "the return link is missing"

    def test_an_unreferenced_note_is_an_ordinary_paragraph(self):
        out = self._render([])
        assert 'epub:type="footnote"' not in out, (
            "an unreferenced note was tagged as a footnote and may be hidden"
        )
        assert 'class="note-unlinked"' in out

    def test_the_text_and_its_marker_survive_either_way(self):
        for backrefs in ([], ["ref1"]):
            out = self._render(backrefs)
            assert "was living" in out, "note text lost"
            assert "7" in out, "note marker lost"
