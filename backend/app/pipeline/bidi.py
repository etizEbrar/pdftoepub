from __future__ import annotations

import unicodedata

from app.models.document import Block, StructuralNode, TextDirection

# Unicode bidirectional character types that carry strong RTL directionality.
_RTL_BIDI_CATEGORIES = {"R", "AL"}
_LTR_BIDI_CATEGORY = "L"

# A block needs this share of *strong* directional characters to be RTL. Digits,
# punctuation and spaces are bidi-neutral and deliberately excluded from the
# denominator, so "١٩٩٥ (Smith, 2020)" inside an Arabic sentence doesn't drag
# the paragraph to LTR.
_RTL_DOMINANCE = 0.5

# Tesseract language codes whose scripts are written right-to-left.
RTL_OCR_LANGUAGES = {"ara", "heb", "fas", "urd", "syr", "div", "yid"}
# ISO 639-1 codes langdetect can return for RTL languages.
RTL_ISO_CODES = {"ar", "he", "fa", "ur", "yi", "ps", "sd"}


def _bidi_class(ch: str) -> str:
    """Collapse Unicode bidi categories to the four cases this module cares about."""
    category = unicodedata.bidirectional(ch)
    if category in _RTL_BIDI_CATEGORIES:
        return "R"
    if category == _LTR_BIDI_CATEGORY:
        return "L"
    if category in ("EN", "AN"):
        return "D"  # digits: never mirrored, and they anchor an LTR-ish run
    return "N"  # neutral: spaces, punctuation


def contains_rtl(text: str) -> bool:
    return any(_bidi_class(ch) == "R" for ch in text)


def visual_to_logical(text: str) -> str:
    """Convert MuPDF's *visual*-order RTL text back to logical order.

    MuPDF applies the Unicode bidirectional algorithm during extraction and
    hands back display order — verified by round-tripping text PyMuPDF itself
    wrote. XHTML, by contrast, stores logical order and lets the reading system
    apply bidi at render time. Passing visual order straight through would make
    an e-reader apply the algorithm a second time and show the text reversed,
    so each right-to-left run is restored here.

    Guarantees, measured against text round-tripped through a real PDF:
      * Pure RTL paragraphs and headings round-trip exactly.
      * RTL containing a parenthesised Latin citation round-trips exactly.
      * Pure LTR text is returned untouched — never reversed.
      * Lines mixing RTL with digits or long Latin runs keep every character,
        but a space or terminal punctuation mark may sit on the other side of
        a direction boundary. Content is preserved; only neutral placement can
        drift, which is inherent to inverting bidi without the original
        embedding levels.
    """
    if not contains_rtl(text):
        return text

    segments: list[tuple[bool, str]] = []
    current: list[str] = []
    current_is_rtl: bool | None = None

    for ch in text:
        klass = _bidi_class(ch)
        if klass == "R":
            wants_rtl = True
        elif klass in ("L", "D"):
            wants_rtl = False
        else:
            # A neutral continues whichever run it is already inside.
            wants_rtl = current_is_rtl if current_is_rtl is not None else True

        if current_is_rtl is None or wants_rtl == current_is_rtl:
            current.append(ch)
            current_is_rtl = wants_rtl
        else:
            segments.append((current_is_rtl, "".join(current)))
            current = [ch]
            current_is_rtl = wants_rtl

    if current:
        segments.append((bool(current_is_rtl), "".join(current)))

    return "".join(seg[::-1] if is_rtl else seg for is_rtl, seg in segments)


def _strong_counts(text: str) -> tuple[int, int]:
    """Return (rtl_count, ltr_count) over strongly-directional characters only."""
    rtl = ltr = 0
    for ch in text:
        bidi = unicodedata.bidirectional(ch)
        if bidi in _RTL_BIDI_CATEGORIES:
            rtl += 1
        elif bidi == _LTR_BIDI_CATEGORY:
            ltr += 1
    return rtl, ltr


def detect_direction(text: str) -> TextDirection:
    """Classify a string's base direction from its strong characters.

    Deliberately conservative: text with no strong characters at all (pure
    numbers, punctuation) stays LTR rather than being guessed at.
    """
    rtl, ltr = _strong_counts(text)
    total = rtl + ltr
    if total == 0:
        return TextDirection.LTR
    return TextDirection.RTL if (rtl / total) >= _RTL_DOMINANCE else TextDirection.LTR


def is_mixed_direction(text: str) -> bool:
    """True when a string contains both scripts, so the renderer should mark the
    base direction explicitly rather than letting the reader guess."""
    rtl, ltr = _strong_counts(text)
    return rtl > 0 and ltr > 0


def annotate_block_directions(blocks: list[Block]) -> None:
    for block in blocks:
        if block.kind == "text" and block.text:
            block.direction = detect_direction(block.text)


def annotate_node_directions(nodes: list[StructuralNode]) -> None:
    for node in nodes:
        if node.text:
            node.direction = detect_direction(node.text)
        elif node.verse_lines:
            node.direction = detect_direction(" ".join(node.verse_lines))


def document_direction(blocks: list[Block]) -> TextDirection:
    """The book's base direction, weighted by how much text each block holds so
    a single English caption can't flip an Arabic book to LTR."""
    rtl_total = ltr_total = 0
    for block in blocks:
        if block.kind != "text" or not block.text:
            continue
        rtl, ltr = _strong_counts(block.text)
        rtl_total += rtl
        ltr_total += ltr
    total = rtl_total + ltr_total
    if total == 0:
        return TextDirection.LTR
    return TextDirection.RTL if (rtl_total / total) >= _RTL_DOMINANCE else TextDirection.LTR


def ocr_languages_for_direction(base_language: str | None) -> str | None:
    """Map a detected ISO language to Tesseract packs, so an Arabic scan is
    OCR'd with the Arabic model instead of English."""
    if not base_language:
        return None
    mapping = {
        "ar": "ara+eng",
        "he": "heb+eng",
        "fa": "fas+eng",
        "tr": "tur+eng",
        "de": "deu+eng",
        "fr": "fra+eng",
        "es": "spa+eng",
        "it": "ita+eng",
        "ru": "rus+eng",
        "en": "eng",
    }
    return mapping.get(base_language.lower())
