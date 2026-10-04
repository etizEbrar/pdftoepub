"""Text recognised on the client, turned into the same Blocks as every other path.

The whole point of this seam is that nothing downstream can tell where a page's
words came from. These tests hold that line: the Blocks a phone's OCR produces
must carry the same geometry, the same provenance and the same shape as the
ones Tesseract produces, because reading order, paragraph reconstruction,
heading detection and the table of contents all run on them unchanged.
"""

from app.models.client_ocr import ClientOCR, ClientOCRLine, ClientOCRPage, ClientOCRWord
from app.pipeline.ocr.supplied import blocks_from_client_page

PAGE_W, PAGE_H = 595.28, 841.89


def _word(text: str, x0: float, y0: float, x1: float, y1: float, conf: float = 0.95):
    return ClientOCRWord(text=text, bbox=(x0, y0, x1, y1), confidence=conf)


def _line(*words, confidence: float = 0.95):
    return ClientOCRLine(words=list(words), confidence=confidence)


def _page(*lines, number: int = 1):
    return ClientOCRPage(page=number, lines=list(lines))


class TestBlocksFromClientWords:
    def test_a_line_becomes_one_block_of_text(self):
        page = _page(_line(_word("Dil", 72, 100, 95, 114), _word("Belâsı", 99, 100, 150, 114)))
        outcome = blocks_from_client_page(page, PAGE_W, PAGE_H)

        assert len(outcome.blocks) == 1
        block = outcome.blocks[0]
        assert block.text == "Dil Belâsı"
        assert block.page == 1
        assert block.source == "ocr"
        assert block.kind == "text"
        assert block.page_width == PAGE_W and block.page_height == PAGE_H

    def test_the_block_bbox_encloses_every_word(self):
        page = _page(_line(_word("Dil", 72, 100, 95, 114), _word("Belâsı", 99, 102, 150, 118)))
        block = blocks_from_client_page(page, PAGE_W, PAGE_H).blocks[0]
        assert block.bbox == (72.0, 100.0, 150.0, 118.0)

    def test_turkish_letters_survive_untouched(self):
        """The reason for choosing Vision at all: ı, ş, ğ, ç, ö, ü, İ."""
        page = _page(_line(_word("İçindekiler", 72, 100, 180, 116),
                           _word("şöyle", 185, 100, 230, 116),
                           _word("sığdı", 235, 100, 280, 116)))
        block = blocks_from_client_page(page, PAGE_W, PAGE_H).blocks[0]
        assert block.text == "İçindekiler şöyle sığdı"

    def test_confidence_is_averaged_over_words(self):
        page = _page(_line(_word("bir", 72, 100, 90, 114, conf=0.90),
                           _word("iki", 95, 100, 115, 114, conf=1.00)))
        outcome = blocks_from_client_page(page, PAGE_W, PAGE_H)
        assert outcome.blocks[0].ocr_confidence == 0.95
        assert outcome.mean_confidence == 0.95

    def test_font_size_is_taken_from_the_glyph_height(self):
        """Downstream heading detection reads font_size, so it has to be real."""
        page = _page(_line(_word("BÖLÜM", 72, 100, 180, 128)))   # 28pt tall
        block = blocks_from_client_page(page, PAGE_W, PAGE_H).blocks[0]
        assert block.font_size == 28.0

    def test_each_line_keeps_its_own_break(self):
        page = _page(
            _line(_word("birinci", 72, 100, 120, 112)),
            _line(_word("ikinci", 72, 116, 118, 128)),
        )
        block = blocks_from_client_page(page, PAGE_W, PAGE_H).blocks[0]
        assert block.text == "birinci\nikinci"

    def test_an_empty_page_yields_nothing_and_says_so(self):
        outcome = blocks_from_client_page(_page(), PAGE_W, PAGE_H)
        assert outcome.blocks == []
        assert not outcome.reliable
        assert outcome.word_count == 0


class TestGeometricBlockGrouping:
    """Vision reports lines, never blocks, so the server has to infer them.

    Tesseract supplies its own block numbering and page_ocr trusts it. There is
    no equivalent here, and getting it wrong matters: a column of body text that
    is split into two blocks reads as two paragraphs, and a heading glued to the
    paragraph under it stops being a heading at all.
    """

    def test_lines_set_as_a_paragraph_form_one_block(self):
        page = _page(
            _line(_word("Birinci", 72, 100, 140, 112)),
            _line(_word("ikinci", 72, 114, 135, 126)),
            _line(_word("üçüncü", 72, 128, 138, 140)),
        )
        outcome = blocks_from_client_page(page, PAGE_W, PAGE_H)
        assert len(outcome.blocks) == 1
        assert outcome.blocks[0].text.count("\n") == 2

    def test_a_wide_vertical_gap_starts_a_new_block(self):
        """A heading over a paragraph, with white space between them."""
        page = _page(
            _line(_word("BÖLÜM", 72, 100, 160, 118)),
            _line(_word("Kitabın", 72, 190, 140, 202)),
            _line(_word("ilk", 72, 204, 100, 216)),
        )
        outcome = blocks_from_client_page(page, PAGE_W, PAGE_H)
        assert len(outcome.blocks) == 2
        assert outcome.blocks[0].text == "BÖLÜM"
        assert outcome.blocks[1].text == "Kitabın\nilk"

    def test_side_by_side_columns_do_not_merge(self):
        """Two columns at the same height are two blocks, never one line."""
        page = _page(
            _line(_word("soldaki", 60, 100, 160, 112)),
            _line(_word("sagdaki", 340, 100, 440, 112)),
            _line(_word("sutun", 60, 114, 150, 126)),
            _line(_word("sutun", 340, 114, 430, 126)),
        )
        outcome = blocks_from_client_page(page, PAGE_W, PAGE_H)
        assert len(outcome.blocks) == 2
        texts = sorted(b.text.replace("\n", " ") for b in outcome.blocks)
        assert texts == ["sagdaki sutun", "soldaki sutun"]

    def test_block_ids_are_unique_and_page_scoped(self):
        page = _page(
            _line(_word("bir", 72, 100, 100, 112)),
            _line(_word("iki", 72, 300, 100, 312)),
            number=7,
        )
        ids = [b.block_id for b in blocks_from_client_page(page, PAGE_W, PAGE_H).blocks]
        assert len(ids) == len(set(ids))
        assert all(i.startswith("p7_") for i in ids), ids


class TestPayloadSelection:
    def test_pages_without_lines_are_not_offered(self):
        payload = ClientOCR(
            engine="apple-vision",
            pages=[_page(number=2), _page(_line(_word("var", 72, 100, 100, 112)), number=5)],
        )
        assert list(payload.by_page()) == [5]
