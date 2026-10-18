"""Chapter openings, put back together.

A novel opens each chapter with a set piece: a number, an ornament, a title in
display type, and the first word's initial set as a drop cap. A scanned book's
OCR text layer reads every piece of that literally. On a real 327-page novel it
produced:

  * the drop cap as a paragraph of its own -- "O", then ", ve elli dokuz
    yaşında." -- and "P" / "lastik" for "Plastik";
  * the ornament (a cloud, a cat) as letters in 75-point type: "a", "(İL",
    "TİT", "/";
  * the chapter number misread as "1o", "3^", "M", or not at all.

Each is repaired here, on the blocks, before structure is read from them: the
drop cap rejoins its word, ornament text is dropped, and the chapter number is
checked against its neighbours and set at the head of the title.
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path

import fitz

from app.models.document import Block, BlockRole, Span
from app.pipeline.ocr.engine import run_ocr, tesseract_available
from app.pipeline.textrepair import DocumentVocabulary, diacritic_key, fold

# A drop cap spans two or more lines of text.
_DROP_CAP_MIN_RATIO = 2.0
# Display type: a chapter title.
_TITLE_MIN_RATIO = 1.4
# Digits a scanner reads as letters in a drop cap set in display type.
_CAP_DIGIT_LETTERS = str.maketrans({"0": "O", "1": "I", "2": "Z", "4": "A", "5": "S", "6": "G", "8": "B"})
# Letters a scanner reads in place of the digits of a chapter number.
_NUMBER_LETTER_DIGITS = str.maketrans({"o": "0", "O": "0", "l": "1", "I": "1", "i": "1", "|": "1"})
# What a scanner leaves where a drop cap's flourish meets the next letter.
_CAP_DEBRIS = " ,.`´'’"
_ROMAN_RE = re.compile(r"^(?=[IVXLC])M{0,3}(C[MD]|D?C{0,3})(X[CL]|L?X{0,3})(I[XV]|V?I{0,3})$")
_WORD_RE = re.compile(r"[^\W\d_]{2,}")
# A word must occur this often in the book to vouch for a line of display type.
_ATTESTED = 2
# How far from the page's centre a chapter number may sit, as a share of width.
_CENTRED = 0.15


@dataclass
class OpeningsReport:
    titles: list[Block] = field(default_factory=list)
    drop_caps: int = 0
    ornaments: int = 0
    numbers: int = 0
    inferred_numbers: int = 0
    debris_lines: int = 0
    mended_openings: int = 0


def _letters(text: str) -> int:
    return sum(c.isalpha() for c in text)


def _attested(text: str, vocab: DocumentVocabulary) -> bool:
    return any(vocab.frequency(w) >= _ATTESTED for w in _WORD_RE.findall(text))


def _first_line_x0(block: Block) -> float:
    return block.spans[0].bbox[0] if block.spans else block.bbox[0]


def _strip_debris(spans: list[Span]) -> list[Span]:
    """Drop what the scanner made of the drop cap's flourish from the front."""
    spans = list(spans)
    while spans:
        trimmed = spans[0].text.lstrip(_CAP_DEBRIS)
        if trimmed:
            spans[0] = replace(spans[0], text=trimmed)
            return spans
        if spans[0].line_break_after:
            return spans
        spans.pop(0)
    return spans


def _set_text_from_spans(block: Block) -> None:
    lines: list[str] = []
    current: list[str] = []
    for span in block.spans:
        current.append(span.text)
        if span.line_break_after:
            lines.append("".join(current).rstrip())
            current = []
    if current:
        lines.append("".join(current).rstrip())
    block.text = "\n".join(lines)


def _join_drop_cap(cap: Block, target: Block, vocab: DocumentVocabulary) -> bool:
    printed = cap.text.strip()
    letter = printed.translate(_CAP_DIGIT_LETTERS)
    if not letter.isalpha():
        return False
    spans = _strip_debris(target.spans)
    if not spans or not spans[0].text:
        return False
    rest = spans[0].text
    # The rest of a word, or the next word of the sentence: lowercase either
    # way. Anything else beside a large letter -- a capitalised line, a
    # number -- is not the text a drop cap opens.
    if not rest[0].islower():
        return False
    first_word = _WORD_RE.match(rest)
    joined_word = letter + (first_word.group(0) if first_word else "")
    if letter != printed and vocab.frequency(joined_word) < _ATTESTED:
        # A large digit beside text is far more often a numbered marker than a
        # misread capital. Only a word the book uses elsewhere settles it.
        return False
    # "O gün" is two words, "O" + "ve" is "Ove". The book's own vocabulary
    # tells them apart: keep the letter apart only when it is a word, what
    # follows is a word, and the two together are not.
    separate = (
        first_word is not None
        and first_word.start() == 0
        and vocab.frequency(letter) >= _ATTESTED
        and vocab.frequency(first_word.group(0)) >= _ATTESTED
        and vocab.frequency(joined_word) == 0
    )
    spans[0] = replace(spans[0], text=(letter + " " + rest) if separate else letter + rest)
    target.spans = spans
    _set_text_from_spans(target)
    return True


def _span_lines(block: Block) -> list[list[Span]]:
    lines: list[list[Span]] = [[]]
    for span in block.spans:
        lines[-1].append(span)
        if span.line_break_after:
            lines.append([])
    return [line for line in lines if line]


def _drop_debris_line(block: Block) -> bool:
    """Drop a first line of bare marks set to the right of the text below it.

    What a scanner makes of an accent on a drop cap it could not read: "* •"
    over the paragraph, which then opened as a bulleted list item. A real
    bullet stands to the left of its text, never above and to the right.
    """
    lines = _span_lines(block)
    if len(lines) < 2:
        return False
    first = "".join(s.text for s in lines[0]).strip()
    if not first or len(first) > 4 or any(c.isalnum() for c in first):
        return False
    if lines[0][0].bbox[0] <= lines[1][0].bbox[0]:
        return False
    block.spans = [s for line in lines[1:] for s in line]
    _set_text_from_spans(block)
    return True


def _isolate_drop_cap(block: Block, body: float) -> bool:
    """Whether the block is a drop cap, cutting away debris read beside it.

    The scanner sometimes reads the cap's accent or flourish as marks of its
    own, in the same block: "* •" above "Ö".
    """
    large = [s for s in block.spans if s.text.strip() and s.font_size >= body * _DROP_CAP_MIN_RATIO]
    letter = "".join("".join(s.text for s in large).split())
    if not (1 <= len(letter) <= 2 and letter.isalnum()):
        return False
    rest = "".join(s.text for s in block.spans if s not in large)
    if any(c.isalnum() for c in rest):
        return False
    if block.text.strip() != letter:
        block.spans = [replace(large[0], text=letter)]
        block.text = letter
        block.font_size = large[0].font_size
    return True


def _drop_cap_target(cap: Block, blocks: list[Block], body: float) -> Block | None:
    best: tuple[float, Block] | None = None
    for block in blocks:
        if block is cap or block.kind != "text" or not block.font_size:
            continue
        if abs(block.font_size - body) > body * 0.2:
            continue
        top = block.bbox[1]
        if not (cap.bbox[1] - body <= top <= cap.bbox[1] + body * 1.5):
            continue
        x0 = _first_line_x0(block)
        if not (cap.bbox[2] - body * 0.8 <= x0 <= cap.bbox[2] + body * 2.5):
            continue
        distance = abs(top - cap.bbox[1]) + abs(x0 - cap.bbox[2])
        if best is None or distance < best[0]:
            best = (distance, block)
    return best[1] if best else None


# --- a drop cap the scanner could not read ----------------------------------
#
# Where the scanner failed on the drop cap altogether, the chapter opens on
# what was left: "^  onja kadere inanırdı" (Sonja), "J nsanlar hep" (İnsanlar),
# "W C *  unun için" (Bunun), "azı adamların" (Bazı), with the cap's body read
# into the next line as well: "1 ve Ove de", "T i  Ya da". A chapter's first
# word is never lowercase, so a lowercase one is a word missing its capital,
# and the book's own vocabulary says which.

# A letter this frequent alone is a word ("o"), not a piece of a glyph.
_WORD_LETTER_FREQUENCY = 100
_MAX_JUNK_TOKENS = 4
_MAX_MISSING_LETTERS = 3


def _line_spans(block: Block, index: int) -> list[Span]:
    lines = _span_lines(block)
    return lines[index] if index < len(lines) else []


def _set_line_text(block: Block, index: int, text: str) -> None:
    lines = _span_lines(block)
    line = lines[index]
    merged = replace(
        line[0],
        text=text,
        bbox=(
            min(s.bbox[0] for s in line),
            min(s.bbox[1] for s in line),
            max(s.bbox[2] for s in line),
            max(s.bbox[3] for s in line),
        ),
        line_break_after=line[-1].line_break_after,
    )
    lines[index] = [merged]
    block.spans = [s for ln in lines for s in ln]
    _set_text_from_spans(block)


def _is_junk_token(token: str, vocab: DocumentVocabulary, lone_capitals: bool) -> bool:
    """A piece of the drop cap's glyph rather than a word of the text.

    A lone capital is a piece of the cap only where nothing else can be --
    beside it, or where taking it away leaves a word missing its capital that
    the book can supply. Otherwise it may be the word "O".
    """
    letters = sum(c.isalpha() for c in token)
    if not letters:
        return True
    if len(token) == 1:
        if token.isupper():
            return lone_capitals
        return vocab.frequency(token) < _WORD_LETTER_FREQUENCY
    if letters == 1:
        return True
    return len(token) <= 2 and token.isupper() and vocab.frequency(token) < _ATTESTED


def _strip_junk(text: str, vocab: DocumentVocabulary, lone_capitals: bool) -> tuple[str, list[str]]:
    tokens = text.split()
    dropped: list[str] = []
    while tokens and len(dropped) < _MAX_JUNK_TOKENS:
        # A lone capital followed by more debris ("V > e") is debris itself.
        followed_by_debris = len(tokens) > 1 and (
            len(tokens[1]) == 1 or not any(c.isalpha() for c in tokens[1])
        )
        if not _is_junk_token(tokens[0], vocab, lone_capitals or followed_by_debris):
            break
        dropped.append(tokens.pop(0))
    if not dropped:
        return text, dropped
    rest = " ".join(tokens)
    # What is left of a mark glued to the first word: "/zam an".
    return rest.lstrip(_GLYPH_STROKES), dropped


def _capital(letters: str) -> str:
    return {"i": "İ", "ı": "I"}.get(letters[0], letters[0].upper()) + letters[1:]


def _restore_capital(word: str, vocab: DocumentVocabulary) -> str | None:
    """The attested word this one is the end of: "onja" -> "Sonja"."""
    folded = fold(word)
    longest = _MAX_MISSING_LETTERS if len(word) >= 4 else 1
    best: tuple[int, str] | None = None
    for candidate, frequency in vocab.words():
        extra = len(candidate) - len(folded)
        if not 1 <= extra <= longest or not candidate.endswith(folded):
            continue
        if not candidate[:extra].isalpha():
            continue
        if best is None or frequency > best[0]:
            best = (frequency, candidate)
    if best is None:
        return _capital_from_stem(word, vocab)
    prefix = best[1][: len(best[1]) - len(folded)]
    return _capital(prefix) + word


_STEM_LETTERS = 4
_STEM_MIN_EVIDENCE = 3
_STEM_MARGIN = 3


def _capital_from_stem(word: str, vocab: DocumentVocabulary) -> str | None:
    """The letter whose words share this one's start: "üşerken" -> "Düşerken".

    The whole word may occur nowhere else, but "düşer", "düşerek" and "düşen"
    do, and no "süşe-" or "güşe-" word does.
    """
    folded = fold(word)
    if len(folded) < _STEM_LETTERS:
        return None
    stem = folded[:_STEM_LETTERS]
    evidence: dict[str, int] = {}
    for candidate, frequency in vocab.words():
        if len(candidate) > len(stem) and candidate[1:].startswith(stem) and candidate[0].isalpha():
            evidence[candidate[0]] = evidence.get(candidate[0], 0) + frequency
    if not evidence:
        return None
    ranked = sorted(evidence.items(), key=lambda pair: -pair[1])
    letter, count = ranked[0]
    runner_up = ranked[1][1] if len(ranked) > 1 else 0
    if count < _STEM_MIN_EVIDENCE or count < runner_up * _STEM_MARGIN:
        return None
    return _capital(letter) + word


_GLYPH_STROKES = "/\\|^~*'`´"


def _open_quotation(first_line: str, lines: list[tuple[Block, int]]) -> str:
    """Restore the opening quotation mark a dialogue's drop cap carried.

    The mark sits in the margin beside the cap and goes with it: "Sahiden
    nereye gidiyoruz?” diye sordu" closes a quotation it never opened.
    """
    if first_line[0] in "“\"«‘":
        return first_line
    text = first_line
    for other_block, other_index in lines[1:6]:
        text += " " + "".join(s.text for s in _line_spans(other_block, other_index))
    opening = min((i for i in (text.find("“"), text.find("«")) if i >= 0), default=-1)
    closing = min((i for i in (text.find("”"), text.find("»")) if i >= 0), default=-1)
    if closing >= 0 and (opening < 0 or closing < opening):
        return ("«" if text[closing] == "»" else "“") + first_line
    return first_line


def _strip_first_line(text: str, vocab: DocumentVocabulary, lone_capitals: bool) -> tuple[str, str | None]:
    """The first line without the cap's debris, its first word completed."""
    stripped, _ = _strip_junk(text, vocab, lone_capitals)
    # "\\^/aşam": the strokes of a "Y" glued to the rest of its word.
    unmarked = stripped.lstrip(_GLYPH_STROKES)
    if unmarked != stripped and unmarked[:1].islower():
        stripped = unmarked
    word = _WORD_RE.match(stripped)
    if not (word and word.start() == 0 and stripped[0].islower()):
        return stripped, None
    restored = _restore_capital(word.group(0), vocab)
    if restored is None:
        return stripped, None
    return restored + stripped[word.end() :], restored


def _mend_first_paragraph(
    blocks: list[Block],
    below: float,
    body: float,
    vocab: DocumentVocabulary,
    removed: set[str],
) -> bool:
    body_blocks = sorted(
        (
            b
            for b in blocks
            if b.bbox[1] >= below - 1
            and b.font_size
            and abs(b.font_size - body) <= body * 0.2
            and _span_lines(b)
        ),
        key=lambda b: (b.bbox[1], b.bbox[0]),
    )
    if not body_blocks:
        return False
    # The paragraph's lines in order, whichever block each was read into.
    lines: list[tuple[Block, int]] = []
    for block in body_blocks:
        lines.extend((block, i) for i in range(len(_span_lines(block))))
    lines.sort(key=lambda ref: (_line_spans(*ref)[0].bbox[1], _line_spans(*ref)[0].bbox[0]))
    first_block, first_index = lines[0]
    first_spans = _line_spans(first_block, first_index)
    top = first_spans[0].bbox[1]
    text_x = first_spans[0].bbox[0]
    first_text = "".join(s.text for s in first_spans).strip()

    # Marks left in the margin where the cap stood: a "*" above the first line.
    marks = 0
    for block in blocks:
        text = block.text.strip()
        if block in body_blocks or not text or len(text) > 3 or any(c.isalnum() for c in text):
            continue
        if block.bbox[1] >= below - 1 and (block.bbox[3] <= top + body * 0.5 or block.bbox[2] <= text_x + 2):
            removed.add(block.block_id)
            marks += 1

    stripped, restored_word = _strip_first_line(first_text, vocab, lone_capitals=True)
    if restored_word is None and any(t.isupper() and len(t) == 1 for t in first_text.split()[:_MAX_JUNK_TOKENS]):
        # Taking a lone capital away left nothing the book could complete:
        # it was a word ("O gün"), not a piece of the cap.
        stripped, restored_word = _strip_first_line(first_text, vocab, lone_capitals=False)
    if stripped == first_text:
        return bool(marks)
    if not stripped:
        # Nothing on the line but the cap's debris.
        if len(_span_lines(first_block)) == 1:
            removed.add(first_block.block_id)
        else:
            _set_line_text(first_block, first_index, "")
        return True
    stripped = _open_quotation(stripped, lines)
    _set_line_text(first_block, first_index, stripped)

    # The rest of the cap's glyph, read beside the next line or as a block of
    # its own in the margin.
    depth = top + body * 3.5
    for block, index in lines[1:3]:
        spans = _line_spans(block, index)
        if not spans or spans[0].bbox[1] > depth:
            break
        text = "".join(s.text for s in spans).strip()
        if len(text) <= 3 and len(_span_lines(block)) == 1 and spans[0].bbox[2] <= text_x + 2:
            removed.add(block.block_id)
            continue
        cleaned, junk = _strip_junk(text, vocab, lone_capitals=True)
        if junk and cleaned:
            _set_line_text(block, index, cleaned)
    return True


def _parse_number(text: str) -> int | None:
    compact = "".join(text.split())
    if _ROMAN_RE.match(compact):
        return None  # roman numerals are left exactly as printed
    digits = compact.translate(_NUMBER_LETTER_DIGITS)
    if digits.isdigit() and len(digits) <= 3:
        return int(digits)
    return None


# Ornament text is a glyph or three. Anything longer above a title -- an author's
# name, an epigraph -- is text, attested in the book or not.
_MAX_ORNAMENT_LETTERS = 3


_VOWELS = frozenset("aeıioöuüyâîûAEIİOÖUÜYÂÎÛ")


def _is_ornament_text(block: Block, title: Block, vocab: DocumentVocabulary) -> bool:
    text = block.text
    letters = _letters(text)
    # A glyph or three in type far larger than the title's is a drawing, even
    # where the letters it was read as happen to spell a word.
    if letters <= _MAX_ORNAMENT_LETTERS and block.font_size and title.font_size and (
        block.font_size >= title.font_size * 1.3
    ):
        return True
    if _attested(text, vocab):
        return False
    # Short, or unpronounceable: "mrnrnm" is a cat.
    return letters <= _MAX_ORNAMENT_LETTERS or not any(c in _VOWELS for c in text)


@dataclass
class _Opening:
    page: int
    title: Block
    number_block: Block | None
    number: int | None
    roman: bool = False


def repair_openings(
    blocks_by_page: dict[int, list[Block]],
    furniture: dict[str, BlockRole],
    body_size: float,
) -> tuple[set[str], OpeningsReport]:
    """Repair drop caps, ornaments and chapter numbers in place.

    Returns the ids of blocks that no longer carry anything (absorbed or
    ornament), for the caller to drop from its block lists.
    """
    report = OpeningsReport()
    removed: set[str] = set()
    if not body_size:
        return removed, report
    vocab = DocumentVocabulary(
        [b for blocks in blocks_by_page.values() for b in blocks if b.block_id not in furniture]
    )
    openings: list[_Opening] = []

    for page_num in sorted(blocks_by_page):
        blocks = [
            b
            for b in blocks_by_page[page_num]
            if b.kind == "text" and b.text.strip() and b.block_id not in furniture
        ]

        for block in blocks:
            if _drop_debris_line(block):
                report.debris_lines += 1

        for cap in blocks:
            if not _isolate_drop_cap(cap, body_size):
                continue
            target = _drop_cap_target(cap, blocks, body_size)
            if target is not None and _join_drop_cap(cap, target, vocab):
                removed.add(cap.block_id)
                report.drop_caps += 1

        live = [b for b in blocks if b.block_id not in removed]
        titles = [
            b
            for b in live
            if b.font_size
            and b.font_size >= body_size * _TITLE_MIN_RATIO
            and _letters(b.text) >= 4
            and _attested(b.text, vocab)
        ]
        if not titles:
            continue
        title = min(titles, key=lambda b: b.bbox[1])
        if title.bbox[1] > title.page_height * 0.6:
            continue  # display type low on a page is not a chapter opening
        # Starting above the title, not ending above it: an ornament read as a
        # 116-point letter hangs down past the title's first line.
        above = sorted(
            (b for b in live if b.bbox[1] < title.bbox[1] - 2 and b not in titles),
            key=lambda b: b.bbox[1],
        )
        # Display type with nothing legible in it, beside or among the title's
        # lines, is an ornament read as text.
        beside = [
            b
            for b in live
            if b not in titles
            and b not in above
            and b.bbox[1] < max(t.bbox[3] for t in titles)
            and b.font_size
            and b.font_size >= body_size * _TITLE_MIN_RATIO
            and _is_ornament_text(b, title, vocab)
        ]

        number_block: Block | None = None
        number: int | None = None
        roman = False
        centre = title.page_width / 2
        for block in above:
            compact = "".join(block.text.split())
            near_centre = abs((block.bbox[0] + block.bbox[2]) / 2 - centre) <= title.page_width * _CENTRED
            if number_block is None and near_centre and len(compact) <= 4 and block.bbox[1] < title.bbox[1]:
                # The chapter number heads the page. A large ornament glyph read
                # into the same block ("1" and a 75-point "a") is cut away.
                spans = [s for s in block.spans if s.font_size < title.font_size * 1.3 and s.text.strip()]
                candidate = "".join("".join(s.text for s in spans).split())
                if candidate and len(candidate) <= 4:
                    number_block = block
                    roman = bool(_ROMAN_RE.match(candidate)) and candidate.isupper() and len(candidate) > 1
                    number = _parse_number(candidate)
                    if roman:
                        number_block.text = candidate
                    continue
            if _is_ornament_text(block, title, vocab):
                removed.add(block.block_id)
                report.ornaments += 1
        for block in beside:
            removed.add(block.block_id)
            report.ornaments += 1
        openings.append(_Opening(page_num, title, number_block, number, roman))
        report.titles.extend(titles)
        if _mend_first_paragraph(
            [b for b in live if b.block_id not in removed and b not in titles],
            max(t.bbox[3] for t in titles),
            body_size,
            vocab,
            removed,
        ):
            report.mended_openings += 1

    _settle_numbers(openings, removed, report)
    return removed, report


def _partly_reads_as(opening: _Opening, expected: int) -> bool:
    if opening.number_block is None:
        return False
    digits = "".join(c for c in opening.number_block.text if c.isdigit())
    return bool(digits) and str(expected).startswith(digits)


def _settle_numbers(openings: list[_Opening], removed: set[str], report: OpeningsReport) -> None:
    """Check each chapter number against its neighbours and set it on the title.

    Chapters are numbered in sequence, so a number the scanner garbled --
    "M" between 35 and 37 -- or missed altogether is the one its neighbours
    leave room for. Numbers are only touched in a book that numbers most of
    its chapters; a book of unnumbered chapters is left alone.
    """
    numbered = [o for o in openings if o.number is not None]
    if len(numbered) < 3 or len(numbered) < len(openings) * 0.5:
        for opening in openings:
            if opening.number_block is not None and opening.number is None and not opening.roman:
                removed.add(opening.number_block.block_id)
        return

    values: list[int | None] = [o.number for o in openings]
    for i, opening in enumerate(openings):
        before = values[i - 1] if i > 0 else None
        after = values[i + 1] if i + 1 < len(openings) else None
        current = values[i]
        if before is not None and after is not None and after == before + 2:
            if current != before + 1:
                values[i] = before + 1
                report.inferred_numbers += 1
        elif current is None and before is not None and _partly_reads_as(opening, before + 1):
            # The last chapter has no successor to confirm it, but a number
            # was printed there and what can be read of it agrees: "3^" after 38.
            values[i] = before + 1
            report.inferred_numbers += 1

    for opening, value in zip(openings, values):
        if opening.number_block is not None:
            removed.add(opening.number_block.block_id)
        if opening.roman and opening.number_block is not None:
            label = opening.number_block.text
        elif value is None:
            continue
        else:
            label = str(value)
        title = opening.title
        first = title.spans[0] if title.spans else None
        # On the title's first line, so the title keeps the shape it was
        # printed in: a heading is judged partly by how many lines it runs to.
        number_span = Span(
            text=label + " ",
            bbox=tuple(opening.number_block.bbox) if opening.number_block else tuple(title.bbox),
            font=first.font if first else (title.font or ""),
            font_size=first.font_size if first else (title.font_size or 0.0),
            bold=first.bold if first else title.bold,
            italic=False,
            baseline=first.baseline if first else 0.0,
        )
        title.spans = [number_span] + list(title.spans)
        _set_text_from_spans(title)
        report.numbers += 1


# --- display type, read again ----------------------------------------------
#
# A scanner's OCR is trained on text type. A chapter title in a display face
# defeats it: "BİL6İ5AYAR" for BİLGİSAYAR, "6ECİKEN" for GECİKEN, "(ÜÇ «AFTA
# ÖNCESİ)" for HAFTA, "TEFTI'S FDİYOR" for TEFTİŞ EDİYOR. Read again from the
# page at high resolution, the same titles come back right, so the title's
# words are compared one for one and the reading the book itself vouches for
# is kept.

_REREAD_DPI = 300
_REREAD_PADDING_PT = 3.0
_WORD_EDGE_PUNCT = ",.;:!?()\"“”‘’'«»"


def _clean(token: str) -> bool:
    core = token.strip(_WORD_EDGE_PUNCT)
    return bool(core) and core.isalpha()


def _token_score(token: str, vocab: DocumentVocabulary) -> int:
    core = token.strip(_WORD_EDGE_PUNCT)
    attested = bool(core) and core.isalpha() and vocab.frequency(core) >= _ATTESTED
    return (2 if attested else 0) + (1 if _clean(token) else 0)


def _needs_reread(text: str, vocab: DocumentVocabulary) -> bool:
    # A chapter's number is not a misread word.
    return any(
        _token_score(t, vocab) < 3
        for t in text.split()
        if len(t.strip(_WORD_EDGE_PUNCT)) >= 2 and any(c.isalpha() for c in t)
    )


# Glyphs a display face is misread as, and the letters they stand for. Only a
# substitution that yields a word the book uses elsewhere is ever made.
_GLYPH_LETTERS = {
    "0": "OÖD", "1": "Iİ", "2": "Z", "3": "B", "4": "A", "5": "SŞ",
    "6": "GĞŞB", "7": "T", "8": "B", "9": "GŞ", "!": "Iİ", "|": "Iİ", "«": "H",
}
_MAX_GLYPHS_PER_WORD = 3


def _restore_glyphs(token: str, vocab: DocumentVocabulary) -> str:
    """"6EY" -> "ŞEY", "BİL6İ5AYAR" -> "BİLGİSAYAR": the attested reading."""
    if not any(c.isalpha() for c in token):
        return token
    lead = len(token) - len(token.lstrip(_WORD_EDGE_PUNCT.replace("!", "")))
    tail = len(token) - len(token.rstrip(_WORD_EDGE_PUNCT.replace("!", "")))
    core = token[lead : len(token) - tail]
    slots = [i for i, c in enumerate(core) if c in _GLYPH_LETTERS]
    if not slots or len(slots) > _MAX_GLYPHS_PER_WORD:
        return token
    if core.endswith("!") and len(slots) == 1:
        return token  # a word and its exclamation mark
    upper = core.upper() == core
    best: tuple[int, str] | None = None
    readings = [""]
    for i, c in enumerate(core):
        options = _GLYPH_LETTERS[c] if i in slots else c
        if i in slots and not upper:
            options = options.lower()
        readings = [r + o for r in readings for o in options]
    for reading in readings:
        frequency = vocab.frequency(reading)
        if frequency >= _ATTESTED and (best is None or frequency > best[0]):
            best = (frequency, reading)
    if best is None:
        return token
    return token[:lead] + best[1] + token[len(token) - tail :]


def _merge_glyphs(original: str, candidate: str) -> str:
    """Take the fresh reading only where the first one has no letter."""
    return "".join(c if c.isalpha() else n for c, n in zip(original, candidate))


def _better(original: str, candidate: str, vocab: DocumentVocabulary) -> str:
    if original == candidate:
        return original
    if _token_score(candidate, vocab) >= 3:
        if _clean(original) and len(original) != len(candidate):
            # A clean word is replaced only glyph for glyph, never by a
            # different word of another length.
            return original
        return candidate if _token_score(original, vocab) < 3 else original
    if _clean(original):
        return original
    if len(original) == len(candidate):
        merged = _merge_glyphs(original, candidate)
        if _token_score(merged, vocab) > _token_score(original, vocab):
            return merged
    return candidate if _token_score(candidate, vocab) > _token_score(original, vocab) else original


def _fold_token(token: str) -> str:
    return diacritic_key("".join(c for c in token if c.isalnum()))


def reread_titles(
    titles: list[Block],
    page_for: Callable[[int], fitz.Page | None],
    vocab_blocks: list[Block],
    languages: str | None,
    work_dir: Path,
) -> int:
    """Correct misread words in display titles.

    First from the book's own vocabulary, which settles a digit read for a
    letter; then from a fresh OCR of the page, compared word for word. Returns
    the number of words corrected.
    """
    if not titles:
        return 0
    vocab = DocumentVocabulary(vocab_blocks)
    corrected = 0
    # The book's own language alone: with English beside it, Tesseract reads
    # Turkish capitals without their dots ("BIR", "GECIKEN").
    language = (languages or "").split("+")[0] or None
    can_reread = tesseract_available()
    if can_reread:
        work_dir.mkdir(parents=True, exist_ok=True)
    for index, title in enumerate(titles):
        if not _needs_reread(title.text, vocab):
            continue
        lines = [line.split() for line in title.text.split("\n")]
        old = [t for line in lines for t in line]
        new = [_restore_glyphs(t, vocab) for t in old]

        page = page_for(title.page) if can_reread and _needs_reread(" ".join(new), vocab) else None
        if page is not None:
            x0, y0, x1, y1 = title.bbox
            clip = fitz.Rect(x0, y0, x1, y1) + (
                -_REREAD_PADDING_PT, -_REREAD_PADDING_PT, _REREAD_PADDING_PT, _REREAD_PADDING_PT
            )
            image_path = work_dir / f"title_{index}.png"
            try:
                page.get_pixmap(dpi=_REREAD_DPI, clip=clip & page.rect, colorspace=fitz.csGRAY).save(str(image_path))
                fresh = [w.text for w in run_ocr(image_path, language, psm=6).words]
            finally:
                image_path.unlink(missing_ok=True)
            matcher = difflib.SequenceMatcher(
                None, [_fold_token(t) for t in new], [_fold_token(t) for t in fresh], autojunk=False
            )
            for tag, i1, i2, j1, j2 in matcher.get_opcodes():
                if tag not in ("equal", "replace") or (i2 - i1) != (j2 - j1):
                    continue
                for k in range(i2 - i1):
                    new[i1 + k] = _better(new[i1 + k], fresh[j1 + k], vocab)

        corrected += sum(1 for a, b in zip(old, new) if a != b)
        if new == old:
            continue
        cursor = 0
        rebuilt: list[str] = []
        for line in lines:
            rebuilt.append(" ".join(new[cursor : cursor + len(line)]))
            cursor += len(line)
        _replace_lines(title, rebuilt)
    return corrected


def _replace_lines(block: Block, texts: list[str]) -> None:
    """Set the block's lines to new text, keeping each line's type and place."""
    lines = _span_lines(block)
    if len(lines) != len(texts):
        return
    spans: list[Span] = []
    for line, text in zip(lines, texts):
        first = line[0]
        bbox = (
            min(s.bbox[0] for s in line),
            min(s.bbox[1] for s in line),
            max(s.bbox[2] for s in line),
            max(s.bbox[3] for s in line),
        )
        spans.append(replace(first, text=text, bbox=bbox, line_break_after=True))
    spans[-1] = replace(spans[-1], line_break_after=lines[-1][-1].line_break_after)
    block.spans = spans
    _set_text_from_spans(block)
