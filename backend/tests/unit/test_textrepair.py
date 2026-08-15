"""Text repair must fix real scan defects and refuse everything else.

The refusals matter more than the fixes: replacing one real word with a
different real word is a worse defect than the scan error, and invisible to a
reader.
"""

from app.models.document import Block
from app.pipeline.textrepair import (
    CorrectionKind,
    DocumentVocabulary,
    Grade,
    fold,
    repair_blocks,
)


def _block(text: str, block_id: str = "b1", page: int = 1) -> Block:
    return Block(
        block_id=block_id,
        page=page,
        page_width=396,
        page_height=561,
        bbox=(28, 100, 360, 120),
        kind="text",
        text=text,
        font_size=8.85,
    )


def _corpus(sentence: str, repeats: int = 12) -> list[Block]:
    """Blocks that establish a vocabulary, the way a real book repeats itself."""
    return [_block(sentence, f"corpus{i}", page=i + 1) for i in range(repeats)]


# --- Turkish case folding -------------------------------------------------

def test_fold_handles_the_turkish_dotted_capital():
    """Python lowercases "İ" to i + a combining dot, which matches nothing."""
    assert fold("İçe") == fold("içe")
    assert fold("İSTANBUL") == fold("istanbul")
    assert len(fold("İ")) == 1


def test_fold_maps_dotless_capital_to_dotless_lowercase():
    assert fold("Irmak") == "ırmak"


# --- level 1: deterministic hygiene ---------------------------------------

def test_removes_space_before_punctuation():
    blocks = [_block("merhaba , nasılsın ?")]
    repair_blocks(blocks)
    assert blocks[0].text == "merhaba, nasılsın?"


def test_adds_missing_space_after_punctuation():
    blocks = [_block("bir,iki,üç")]
    repair_blocks(blocks)
    assert blocks[0].text == "bir, iki, üç"


def test_collapses_repeated_punctuation():
    blocks = [_block("gerçekten mi??")]
    repair_blocks(blocks)
    assert blocks[0].text == "gerçekten mi?"


def test_a_spaced_ellipsis_is_never_touched():
    """". . ." is real typography in these books, not a defect."""
    original = "Keşke . . . olsaydı"
    blocks = [_block(original)]
    repair_blocks(blocks)
    assert blocks[0].text == original


def test_a_plain_ellipsis_is_never_touched():
    blocks = [_block("bekliyorum... hâlâ")]
    repair_blocks(blocks)
    assert blocks[0].text == "bekliyorum... hâlâ"


def test_strips_control_characters():
    blocks = [_block("temiz\x01metin")]
    repair_blocks(blocks)
    assert "\x01" not in blocks[0].text


# --- level 2: document-validated repair -----------------------------------

def test_repairs_rn_read_as_m_when_the_document_establishes_the_word():
    blocks = _corpus("yaşamım güzel bir yaşamım oldu") + [_block("bu yaşarnım hakkında", "x")]
    report = repair_blocks(blocks)
    assert blocks[-1].text == "bu yaşamım hakkında"
    assert any(c.kind is CorrectionKind.OCR_CHARACTER for c in report.corrections)


def test_refuses_an_rn_repair_the_document_does_not_establish():
    """Without the target appearing often, there is no evidence to act on."""
    blocks = [_block("bu yaşarnım hakkında")]
    repair_blocks(blocks)
    assert blocks[0].text == "bu yaşarnım hakkında"


def test_short_words_are_never_shape_corrected():
    """"rnek" comes from a hyphen-split "örnek"; "mek" would be wrong."""
    blocks = _corpus("mek mek mek") + [_block("rnek burada", "x")]
    repair_blocks(blocks)
    assert "rnek" in blocks[-1].text


def test_rejoins_a_word_split_by_a_stray_space():
    blocks = _corpus("Sırma geldi ve Sırma gitti") + [_block("sonra S ırma geldi", "x")]
    report = repair_blocks(blocks)
    assert "Sırma" in blocks[-1].text
    assert any(c.kind is CorrectionKind.WORD_SPLIT for c in report.corrections)


# --- refusals: the important half -----------------------------------------

def test_never_restores_a_diacritic_because_turkish_minimal_pairs_exist():
    """"sakin" (calm) and "sakın" (beware) are both real words. A rare one is
    not automatically a misspelling of a common one."""
    blocks = _corpus("sakın oraya gitme sakın") + [_block("çok sakin bir adam", "x")]
    report = repair_blocks(blocks)
    assert "sakin" in blocks[-1].text, "a real word was replaced by a different real word"
    # It is still surfaced for review rather than ignored.
    assert any(
        c.grade is Grade.UNCERTAIN and c.kind is CorrectionKind.OCR_CHARACTER
        for c in report.rejected
    )


def test_never_joins_two_words_that_are_both_real():
    """"bu gün" ("this day") must survive, even though "bugün" ("today") is a
    far more common word in the same book."""
    blocks = _corpus("bugün hava güzel bugün")  # establishes the joined form
    blocks += _corpus("bu ev bu yol bu şey", repeats=10)  # establishes "bu"
    blocks += _corpus("gün doğdu gün battı", repeats=10)  # establishes "gün"
    blocks += [_block("işte bu gün geldi", "x")]

    report = repair_blocks(blocks)
    assert "bu gün" in blocks[-1].text, "a real two-word phrase was collapsed"
    assert any(
        c.kind is CorrectionKind.WORD_SPLIT and "both" in c.reason for c in report.rejected
    ), "the ambiguous join should be recorded for review"


def test_two_long_words_are_never_joined_even_when_the_result_is_a_word():
    """A dropped space leaves a stray glyph, not two full words."""
    blocks = _corpus("gerçekten çok gerçekten az")
    blocks += [_block("bu gerçek ten yapıldı", "x")]
    repair_blocks(blocks)
    assert "gerçek ten" in blocks[-1].text


def test_never_joins_across_a_common_single_letter_word():
    """Turkish "o" is a word; "o dama" must not collapse to "odama"."""
    corpus = [_block("o o o o o o o o o o o o o o o", f"o{i}", page=i) for i in range(9)]
    corpus += _corpus("odama girdim odama")
    blocks = corpus + [_block("o dama baktım", "x")]
    repair_blocks(blocks)
    assert "o dama" in blocks[-1].text


def test_suspicious_text_is_reported_but_never_modified():
    original = "bir enerjidirVarlıkları sen"
    blocks = [_block(original)]
    report = repair_blocks(blocks)
    assert blocks[0].text == original
    assert any(c.kind is CorrectionKind.SUSPICIOUS for c in report.rejected)


def test_disabling_repair_leaves_every_block_untouched():
    original = "merhaba , nasılsın ?"
    blocks = [_block(original)]
    report = repair_blocks(blocks, enabled=False)
    assert blocks[0].text == original
    assert report.applied_count == 0


# --- provenance -----------------------------------------------------------

def test_every_correction_records_why_it_was_made():
    blocks = _corpus("yaşamım güzel") + [_block("bu yaşarnım", "x", page=7)]
    report = repair_blocks(blocks)
    for correction in report.corrections:
        assert correction.reason
        assert 0.0 <= correction.confidence <= 1.0
        assert correction.block_id
        payload = correction.to_dict()
        assert {"type", "original", "corrected", "reason", "confidence", "source_page"} <= payload.keys()


def test_a_correction_only_ever_targets_established_vocabulary():
    """The replacement must be a word the document already contains often, so a
    correction can never introduce a word that is not in the source."""
    blocks = _corpus("yaşamım güzel") + [_block("bu yaşarnım", "x")]
    vocab = DocumentVocabulary(blocks)
    report = repair_blocks(blocks)
    for correction in report.corrections:
        if correction.kind in (CorrectionKind.OCR_CHARACTER, CorrectionKind.WORD_SPLIT):
            assert vocab.is_canonical(correction.corrected.replace(" ", ""))


def test_repair_is_linear_and_fast_on_a_large_document():
    import time

    blocks = [_block("yaşamım güzel bir gün oldu bugün", f"b{i}", page=i) for i in range(6000)]
    start = time.time()
    repair_blocks(blocks)
    assert time.time() - start < 10.0
