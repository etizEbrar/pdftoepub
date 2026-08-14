import pytest

from app.models.document import Block, TextDirection
from app.pipeline.bidi import (
    contains_rtl,
    detect_direction,
    document_direction,
    is_mixed_direction,
    ocr_languages_for_direction,
    visual_to_logical,
)

ARABIC = "هذا نص عربي للاختبار"
HEBREW = "זהו טקסט בעברית"
ENGLISH = "This is English text"


def _block(text: str, block_id: str = "b1") -> Block:
    return Block(
        block_id=block_id,
        page=1,
        page_width=612,
        page_height=792,
        bbox=(0, 0, 100, 20),
        kind="text",
        text=text,
    )


def test_detects_arabic_as_rtl():
    assert detect_direction(ARABIC) == TextDirection.RTL


def test_detects_hebrew_as_rtl():
    assert detect_direction(HEBREW) == TextDirection.RTL


def test_detects_english_as_ltr():
    assert detect_direction(ENGLISH) == TextDirection.LTR


def test_numbers_and_punctuation_alone_stay_ltr_rather_than_being_guessed():
    assert detect_direction("123 456 -- (7.8)") == TextDirection.LTR
    assert detect_direction("") == TextDirection.LTR


def test_arabic_sentence_with_latin_citation_stays_rtl():
    # Neutral characters (digits, parentheses) must not drag the base direction
    # to LTR, or an Arabic paragraph would render backwards.
    mixed = "النص العربي مع (Smith 2020) أرقام إضافية هنا"
    assert detect_direction(mixed) == TextDirection.RTL


def test_predominantly_latin_line_with_one_arabic_word_stays_ltr():
    mixed = "This English sentence quotes the word سلام once only here"
    assert detect_direction(mixed) == TextDirection.LTR


def test_is_mixed_direction_detects_both_scripts():
    assert is_mixed_direction("النص العربي مع English") is True
    assert is_mixed_direction(ENGLISH) is False
    assert is_mixed_direction(ARABIC) is False


def test_document_direction_is_weighted_by_text_volume():
    blocks = [_block(ARABIC * 10, "a"), _block("Figure 1", "b")]
    assert document_direction(blocks) == TextDirection.RTL


def test_document_direction_ltr_when_mostly_latin():
    blocks = [_block(ENGLISH * 10, "a"), _block(ARABIC, "b")]
    assert document_direction(blocks) == TextDirection.LTR


def test_ocr_language_mapping_selects_the_right_tesseract_pack():
    assert ocr_languages_for_direction("ar") == "ara+eng"
    assert ocr_languages_for_direction("he") == "heb+eng"
    assert ocr_languages_for_direction("tr") == "tur+eng"
    assert ocr_languages_for_direction(None) is None
    assert ocr_languages_for_direction("xx") is None


# --- visual -> logical order ---------------------------------------------
#
# These use PDF round-tripping to prove the behaviour against what MuPDF
# actually produces, rather than against a hand-written assumption.


def _round_trip_through_pdf(text: str) -> str:
    """Write `text` into a PDF and read it back the way the pipeline does."""
    import fitz

    from app.pipeline.extract import extract_page_blocks

    font_path = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"
    doc = fitz.open()
    page = doc.new_page(width=500, height=200)
    writer = fitz.TextWriter(page.rect)
    writer.append(fitz.Point(30, 100), text, font=fitz.Font(fontfile=font_path), fontsize=13)
    writer.write_text(page)
    blocks = extract_page_blocks(page, 0)
    doc.close()
    return blocks[0].text.strip() if blocks else ""


def _unicode_font_missing() -> bool:
    from pathlib import Path

    return not Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf").exists()


requires_unicode_font = pytest.mark.skipif(
    _unicode_font_missing(), reason="no Arabic/Hebrew-capable font installed"
)


def test_contains_rtl_identifies_strong_characters():
    assert contains_rtl(ARABIC) is True
    assert contains_rtl(HEBREW) is True
    assert contains_rtl(ENGLISH) is False
    assert contains_rtl("2024 (v1.2)") is False


def test_ltr_text_is_never_reversed():
    assert visual_to_logical(ENGLISH) == ENGLISH
    assert visual_to_logical("Numbers 123 and (parens).") == "Numbers 123 and (parens)."


def test_visual_to_logical_is_a_no_op_on_text_without_rtl():
    for sample in ("", "   ", "Plain ASCII", "Ünicode áccents"):
        assert visual_to_logical(sample) == sample


@requires_unicode_font
@pytest.mark.parametrize(
    "text",
    [
        "هذا نص عربي يستخدم لاختبار اتجاه الكتابة",
        "الفصل الأول",
        "זהו טקסט בעברית לבדיקת כיוון הכתיבה.",
        "كتاب (Smith 2020) مهم جدا",
    ],
)
def test_rtl_text_round_trips_exactly_through_a_real_pdf(text: str):
    """Pure RTL, RTL headings, Hebrew, and RTL with a Latin citation are all
    restored character-for-character."""
    assert _round_trip_through_pdf(text) == text


@requires_unicode_font
def test_english_survives_a_pdf_round_trip_untouched():
    text = "This is English only text."
    assert _round_trip_through_pdf(text) == text


@requires_unicode_font
def test_heavily_mixed_line_keeps_every_character_even_when_spacing_drifts():
    """The documented limitation: inverting bidi without the original embedding
    levels can move a space or terminal mark across a direction boundary. No
    character may be lost or invented."""
    text = "النص العربي مع English words و 2024 أرقام."
    result = _round_trip_through_pdf(text)

    assert sorted(result.replace(" ", "")) == sorted(text.replace(" ", ""))
    assert "English words" in result
    assert "2024" in result
