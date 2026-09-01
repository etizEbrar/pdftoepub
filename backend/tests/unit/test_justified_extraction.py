"""Regressions from converting a real 168-page Turkish engineering book.

The defects here were invisible to every fixture: they only appear in text that
has actually been justified by a typesetter, and in a book long enough for its
chapter structure to matter.
"""

from __future__ import annotations

import fitz
import pytest

from app.models.document import BlockRole, StructuralNode
from app.pipeline.extract import extract_page_blocks
from app.pipeline.headings import is_division_heading, is_division_label, merge_division_numbers


def _justified_page(tmp_path, gap: float = 9.0) -> fitz.Document:
    """A line whose words are spread apart, as justification does.

    MuPDF reports each stretched run as a separate "line" at the same baseline.
    """
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    words = ["sistemler", "sayesinde", "yenilenebilir", "kaynaklarn", "daha", "verimli"]
    x = 51.0
    for word in words:
        page.insert_text((x, 80), word, fontsize=11)
        x += len(word) * 5.4 + gap
    page.insert_text((51.0, 96), "kullanilmasina olanak tanimasi, cevresel etkilerin", fontsize=11)
    path = tmp_path / "justified.pdf"
    doc.save(str(path))
    doc.close()
    return fitz.open(str(path))


class TestJustifiedTextIsOneLine:
    """Words spread across a justified line are one line, not one line each.

    Left split, a page of justified prose arrives as a column of single words,
    which reads downstream as short ragged lines — that is, as poetry — and
    shreds any heading set on such a line into several headings.
    """

    def test_words_on_a_shared_baseline_become_a_single_line(self, tmp_path):
        doc = _justified_page(tmp_path)
        blocks = extract_page_blocks(doc[0], 0)
        doc.close()

        joined = "\n".join(b.text for b in blocks)
        first_line = joined.split("\n")[0]
        assert "sistemler sayesinde" in first_line, (
            f"justified words were not rejoined: {first_line!r}"
        )
        assert "sistemler" in first_line and "verimli" in first_line

    def test_words_are_separated_by_exactly_one_space(self, tmp_path):
        doc = _justified_page(tmp_path)
        blocks = extract_page_blocks(doc[0], 0)
        doc.close()
        text = "\n".join(b.text for b in blocks)
        assert "  " not in text, f"double spaces introduced: {text!r}"
        assert "sistemlersayesinde" not in text, "words were glued without a space"

    def test_a_genuinely_new_line_stays_a_new_line(self, tmp_path):
        """Merging must not swallow the following line of the paragraph."""
        doc = _justified_page(tmp_path)
        blocks = extract_page_blocks(doc[0], 0)
        doc.close()
        text = "\n".join(b.text for b in blocks)
        assert "kullanilmasina" in text
        # The second baseline must not have been folded into the first.
        line_with_verimli = [ln for ln in text.split("\n") if "verimli" in ln][0]
        assert "kullanilmasina" not in line_with_verimli

    def test_a_column_gutter_is_not_treated_as_word_spacing(self, tmp_path):
        """A gap far wider than word spacing must never be bridged."""
        doc = fitz.open()
        page = doc.new_page(width=612, height=792)
        page.insert_text((60, 80), "left column text", fontsize=11)
        page.insert_text((380, 80), "right column text", fontsize=11)
        path = tmp_path / "cols.pdf"
        doc.save(str(path))
        doc.close()

        reopened = fitz.open(str(path))
        blocks = extract_page_blocks(reopened[0], 0)
        reopened.close()
        for block in blocks:
            for line in block.text.split("\n"):
                assert not ("left column" in line and "right column" in line), (
                    f"joined across a column gutter: {line!r}"
                )


class TestDivisionHeadings:
    """"BÖLÜM 3" names a chapter as surely as a bare "3" does."""

    @pytest.mark.parametrize(
        "text", ["BÖLÜM 3", "BÖLÜM 4", "3. BÖLÜM", "CHAPTER 2", "PART II", "KISIM 1"]
    )
    def test_division_labels_are_recognised(self, text):
        assert is_division_label(text), f"{text!r} not recognised as a division label"

    @pytest.mark.parametrize("text", ["1.2. Literatür Taraması", "Sisin İçinden", "Sonuç"])
    def test_ordinary_headings_are_not_division_labels(self, text):
        assert not is_division_label(text)

    def test_a_subsection_number_is_not_a_chapter(self):
        """"1.2." is a section within a chapter, not a chapter of its own."""
        assert not is_division_heading("1.2. Literatür Taraması")
        assert is_division_heading("BÖLÜM 3 VERİ YAPILARI ÜZERİNE DERLEME")

    def test_a_division_label_merges_with_the_title_beneath_it(self):
        nodes = [
            StructuralNode(node_id="n1", role=BlockRole.HEADING, text="BÖLÜM 3",
                           source_block_ids=["b1"], page=66, level=2),
            StructuralNode(node_id="n2", role=BlockRole.HEADING,
                           text="VERİ YAPILARI ÜZERİNE DERLEME",
                           source_block_ids=["b2"], page=66, level=2),
        ]
        assert merge_division_numbers(nodes) == 1
        assert nodes[0].text == "BÖLÜM 3 VERİ YAPILARI ÜZERİNE DERLEME"


class TestNumberingHierarchy:
    """A book that numbers its own sections has stated its own hierarchy.

    In the real Turkish book "BÖLÜM 1" and "1.1. Bilimde Yapay Zekâ" are set at
    the same size, so levels inferred from type alone made both h2 and the
    navigation read as a flat list of forty equal entries.
    """

    @staticmethod
    def _headings(*texts_and_scales) -> list[StructuralNode]:
        out = []
        for i, (text, scale) in enumerate(texts_and_scales):
            n = StructuralNode(
                node_id=f"h{i}", role=BlockRole.HEADING, text=text,
                source_block_ids=[f"b{i}"], page=1 + i,
            )
            n.heading_scale = scale
            out.append(n)
        return out

    def test_numbered_sections_sit_below_their_chapter(self):
        from app.pipeline.headings import assign_heading_levels

        nodes = self._headings(
            ("BÖLÜM 1", 1.6), ("1.1. Bilimde Yapay Zekâ", 1.6),
            ("1.2. Açıklanabilir Yapay Zekâ", 1.6), ("BÖLÜM 2", 1.6),
        )
        assign_heading_levels(nodes)
        by_text = {n.text: n.level for n in nodes}
        assert by_text["1.1. Bilimde Yapay Zekâ"] > by_text["BÖLÜM 1"], (
            f"sections not nested under the chapter: {by_text}"
        )
        assert by_text["BÖLÜM 1"] == by_text["BÖLÜM 2"], "chapters at differing levels"

    def test_a_chapter_opener_numbered_1_is_not_demoted(self):
        """"1. GİRİŞ" opens a division; only dotted numbers are subsections."""
        from app.pipeline.headings import assign_heading_levels

        nodes = self._headings(
            ("BÖLÜM 1", 1.6), ("1. GİRİŞ", 1.6), ("BÖLÜM 2", 1.6),
        )
        assign_heading_levels(nodes)
        by_text = {n.text: n.level for n in nodes}
        assert by_text["1. GİRİŞ"] == by_text["BÖLÜM 1"]

    def test_deeper_numbering_goes_deeper_still(self):
        from app.pipeline.headings import assign_heading_levels

        nodes = self._headings(
            ("BÖLÜM 1", 1.6), ("1.2. Section", 1.6), ("1.2.3. Subsection", 1.6),
            ("BÖLÜM 2", 1.6),
        )
        assign_heading_levels(nodes)
        by_text = {n.text: n.level for n in nodes}
        assert by_text["1.2.3. Subsection"] > by_text["1.2. Section"] > by_text["BÖLÜM 1"]

    def test_a_book_without_division_labels_is_left_to_typography(self):
        """No divisions means no evidence of a chapter level to nest under."""
        from app.pipeline.headings import assign_heading_levels

        nodes = self._headings(("1.1. One", 1.6), ("1.2. Two", 1.6))
        assign_heading_levels(nodes)
        assert {n.level for n in nodes} == {1}, "levels changed without evidence"
