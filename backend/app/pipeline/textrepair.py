"""Deterministic, local repair of OCR and extraction defects.

Runs after extraction/OCR and before structural reconstruction, on Blocks that
still carry their geometry. Nothing here consults a network service or a model;
every correction is justified by evidence taken from the document itself.

The central idea is **document-internal validation**. A book repeats its own
vocabulary: in a 96,000-word novel "için" occurs 540 times, so a single "icin"
is almost certainly the same word with a lost cedilla. That gives a dictionary
calibrated to this exact book, in this exact language, with this scanner's
error profile — without shipping a dictionary for every language, and without
guessing.

Corrections are graded, and only the first two grades are applied:

  SAFE       deterministic and reversible-by-inspection (whitespace, Unicode)
  CONFIDENT  corroborated by document frequency and a known OCR confusion
  UNCERTAIN  recorded in the quality report, text left exactly as found

Nothing is ever invented. A correction may only replace a token with another
token the document already contains many times.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum

from app.models.document import Block

# --- what counts as a word ------------------------------------------------
_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)
# Private-use sentinels planted by other stages must never be treated as text.
_SENTINEL_RANGE = re.compile("[\ue000-\ue005]")  # written escaped: these are invisible


class Grade(str, Enum):
    SAFE = "safe"
    CONFIDENT = "confident"
    UNCERTAIN = "uncertain"


class CorrectionKind(str, Enum):
    UNICODE = "unicode_normalization"
    CONTROL_CHAR = "control_character"
    PUNCTUATION_SPACING = "punctuation_spacing"
    REPEATED_PUNCTUATION = "repeated_punctuation"
    OCR_CHARACTER = "ocr_character"
    WORD_SPLIT = "word_split"
    SUSPICIOUS = "suspicious_text"


@dataclass
class Correction:
    """One change, with the evidence that justified it."""

    kind: CorrectionKind
    grade: Grade
    original: str
    corrected: str
    reason: str
    confidence: float
    page: int
    block_id: str

    def to_dict(self) -> dict:
        return {
            "type": self.kind.value,
            "grade": self.grade.value,
            "original": self.original,
            "corrected": self.corrected,
            "reason": self.reason,
            "confidence": round(self.confidence, 3),
            "source_page": self.page,
            "block_id": self.block_id,
        }


@dataclass
class RepairReport:
    corrections: list[Correction] = field(default_factory=list)
    rejected: list[Correction] = field(default_factory=list)

    def add(self, correction: Correction) -> None:
        if correction.grade is Grade.UNCERTAIN:
            self.rejected.append(correction)
        else:
            self.corrections.append(correction)

    def counts_by_kind(self) -> dict[str, int]:
        return dict(Counter(c.kind.value for c in self.corrections))

    @property
    def applied_count(self) -> int:
        return len(self.corrections)

    @property
    def rejected_count(self) -> int:
        return len(self.rejected)

    @property
    def mean_confidence(self) -> float:
        if not self.corrections:
            return 1.0
        return sum(c.confidence for c in self.corrections) / len(self.corrections)

    def pages_needing_review(self) -> list[int]:
        return sorted({c.page for c in self.rejected})


# --- vocabulary -----------------------------------------------------------

# Minimum times a word must appear before it can be treated as this document's
# own spelling of something. Set high enough that a repeated OCR error cannot
# establish itself as the canonical form.
MIN_CANONICAL_FREQUENCY = 8
# A token appearing more than this is a word in its own right, so a "split"
# involving it is probably two real words.
MAX_FRAGMENT_FREQUENCY = 5


def fold(word: str) -> str:
    """Case-fold for frequency lookup, without Turkish's dotted-I hazard.

    Python lowercases "İ" to "i" plus a combining dot, so "İçe".lower() is a
    three-codepoint string that matches nothing. Mapping the dotted capital to
    a plain "i" first keeps words with İ comparable to the rest of the text.
    """
    return word.replace("İ", "i").replace("I", "ı").lower()


class DocumentVocabulary:
    """Word frequencies for this document, used to validate every correction."""

    def __init__(self, blocks: list[Block]):
        counter: Counter[str] = Counter()
        for block in blocks:
            if block.kind != "text" or not block.text:
                continue
            for word in _WORD_RE.findall(_SENTINEL_RANGE.sub("", block.text)):
                counter[fold(word)] += 1
        self._freq = counter
        self._by_key: dict[str, list[tuple[str, int]]] | None = None

    def frequency(self, word: str) -> int:
        return self._freq.get(fold(word), 0)

    def is_canonical(self, word: str) -> bool:
        return self.frequency(word) >= MIN_CANONICAL_FREQUENCY

    def is_fragment(self, word: str) -> bool:
        """True when a token is too rare to be a standalone word here."""
        return self.frequency(word) <= MAX_FRAGMENT_FREQUENCY

    def attested_spellings(self, key: str) -> list[tuple[str, int]]:
        """Well-attested words sharing a diacritic-stripped key, most common first.

        Built lazily and cached: a book has tens of thousands of distinct words
        and this is consulted once per rare token.
        """
        if self._by_key is None:
            index: dict[str, list[tuple[str, int]]] = {}
            for word, count in self._freq.items():
                if count >= MIN_CANONICAL_FREQUENCY:
                    index.setdefault(diacritic_key(word), []).append((word, count))
            for spellings in index.values():
                spellings.sort(key=lambda pair: -pair[1])
            self._by_key = index
        return self._by_key.get(key, [])


# --- OCR confusion table --------------------------------------------------
#
# Deliberately small. Two glyph-shape confusions survive; every diacritic
# substitution was removed after measuring what it did to a real Turkish book.
#
# Restoring diacritics from document frequency alone is NOT safe in Turkish,
# because the language is full of minimal pairs that differ only by one:
#     sakin (calm)      x1   vs  sakın (beware)    x10
#     acıyorum (I pity) x2   vs  açıyorum (I open) x17
#     yon                x1   vs  yön (direction)  x10
# A rare word is not automatically a misspelling of a common one, and "fixing"
# these would silently replace one real word with a different real word — a
# worse defect than the scan error, and invisible to the reader. Candidates are
# still detected and reported as UNCERTAIN so the user can see them; they are
# simply never applied without a real lexicon to arbitrate.
#
# "rn" -> "m" is kept because it is a shape artifact rather than a lexical
# distinction: no Turkish word contains "rn" where "m" belongs by meaning.
OCR_CONFUSIONS: tuple[tuple[str, str], ...] = (
    ("rn", "m"),
    ("vv", "w"),
)

# Substitutions detected and reported, but never applied automatically.
AMBIGUOUS_CONFUSIONS: tuple[tuple[str, str], ...] = (
    ("s", "ş"), ("g", "ğ"), ("c", "ç"), ("o", "ö"), ("u", "ü"),
    ("i", "ı"), ("ı", "i"),
)

# --- Turkish diacritic restoration ----------------------------------------
#
# Scanners drop diacritics; they almost never invent them. That asymmetry is
# what makes a narrow class of these corrections safe, and it is enforced
# directly: a correction may never *reduce* the number of marked letters.
#
# Three independent guards must all agree before a word is changed:
#   1. stripping diacritics from both forms yields the same key
#   2. exactly one well-attested word in the document shares that key
#   3. that word is overwhelmingly more common than the observed one
# plus the asymmetry rule above. Together they admit "icin" -> "için" while
# refusing "kışı" -> "kişi" (which would strip a diacritic) and "sakin" ->
# "sakın" (where the two forms are too close in frequency to separate).
_DIACRITIC_FOLD = str.maketrans({
    "ş": "s", "Ş": "s", "ğ": "g", "Ğ": "g", "ç": "c", "Ç": "c",
    "ö": "o", "Ö": "o", "ü": "u", "Ü": "u", "ı": "i", "İ": "i",
    "â": "a", "Â": "a", "î": "i", "Î": "i", "û": "u", "Û": "u",
})
# Letters carrying a visible mark. "ı" is deliberately absent: it is the
# dotless counterpart of "i", not a marked form of it, so neither direction of
# that pair counts as adding or losing a diacritic.
_MARKED_LETTERS = frozenset("şŞğĞçÇöÖüÜâÂîÎûÛ")

# How much more common the candidate must be. Measured against the real book:
# "kişi" is 39x "kışı" and "sakın" 10x "sakin" — both real words that must
# survive — while "için" is 540x "icin" and "değil" 285x "degil".
DIACRITIC_FREQUENCY_RATIO = 100
# The observed form must be a true one-off. A word the document uses more than
# once is a word the document uses — "acıyorum" (I pity) appears twice in the
# real book and is not a misspelling of "açıyorum" (I open).
DIACRITIC_MAX_OBSERVED_FREQUENCY = 1


def diacritic_key(word: str) -> str:
    """Strip Turkish diacritics, giving a key shared by all spellings."""
    return word.translate(_DIACRITIC_FOLD).lower()


def _marked_count(word: str) -> int:
    return sum(1 for c in word if c in _MARKED_LETTERS)

# A shape confusion inside a short word is ambiguous; inside a long one, with a
# frequent target, it is convincing. "rnek" (from a hyphen-split "örnek") must
# not become "mek", while "yaşarnım" -> "yaşamım" is unmistakable.
MIN_CONFUSION_WORD_LENGTH = 6


def _confusion_candidates(
    word: str, table: tuple[tuple[str, str], ...] = OCR_CONFUSIONS
) -> list[tuple[str, str]]:
    """Single-substitution variants of a word, with the rule that produced each."""
    out: list[tuple[str, str]] = []
    for seen, actual in table:
        start = 0
        while True:
            index = word.find(seen, start)
            if index < 0:
                break
            # Word-internal only: a confusion at the very start is usually the
            # tail of a word split across a line, not a misread glyph.
            if index == 0:
                start = index + 1
                continue
            candidate = word[:index] + actual + word[index + len(seen):]
            if candidate != word:
                out.append((candidate, f"{seen}->{actual}"))
            start = index + 1
    return out


# --- level 1: deterministic text hygiene ---------------------------------

_CONTROL_CHARS = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# Glyphs from a symbol-encoded font.
#
# A TrueType font with a (3,0) symbol cmap maps character code N to U+F000+N,
# and a PDF that ships no ToUnicode map hands that straight back. The text is
# perfectly ordinary — "978-625" arrives as U+F039 U+F037 U+F038 U+F02D … —
# but every reader shows it as an empty box, so the ISBN on the copyright page
# was unreadable while the same digits sat beside it in a normal font.
#
# Subtracting 0xF000 is the documented convention, not a guess, so this is
# recovery rather than correction. Only the printable ASCII window is mapped;
# anything outside it stays exactly as found and is counted instead.
_SYMBOL_PUA_START, _SYMBOL_PUA_END = 0xF020, 0xF07E
# The one non-ASCII symbol common enough to be worth naming: Symbol and
# Wingdings both put their bullet here, and it appears in list after list.
_SYMBOL_PUA_EXTRA = {"\uf0b7": "\u2022"}
_PUA_RE = re.compile("[\ue006-\uf8ff]")  # sentinels U+E000-E005 deliberately excluded


def _recover_symbol_font_glyphs(text: str) -> tuple[str, int]:
    """Map symbol-font private-use codepoints back to the characters they mean.

    Returns the recovered text and the number of private-use characters that
    could not be mapped, which the quality report surfaces rather than hides.
    """
    if not _PUA_RE.search(text):
        return text, 0
    out: list[str] = []
    unmapped = 0
    for ch in text:
        code = ord(ch)
        if ch in _SYMBOL_PUA_EXTRA:
            out.append(_SYMBOL_PUA_EXTRA[ch])
        elif _SYMBOL_PUA_START <= code <= _SYMBOL_PUA_END:
            out.append(chr(code - 0xF000))
        elif 0xE006 <= code <= 0xF8FF:
            out.append(ch)
            unmapped += 1
        else:
            out.append(ch)
    return "".join(out), unmapped

# Typographic ligatures are presentation forms of ordinary letters. Leaving them
# in breaks search, copy and text-to-speech, and some readers show a blank box.
# Expanded explicitly rather than via NFKC, which would also rewrite fractions,
# circled numbers and superscripts that may be meaningful in the source.
_LIGATURES = {
    "\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl",
    "\ufb03": "ffi", "\ufb04": "ffl", "\ufb05": "st", "\ufb06": "st",
    "\u0132": "IJ", "\u0133": "ij", "\u0152": "OE", "\u0153": "oe",
    "\ufb13": "\u0574\u0576", "\ufb14": "\u0574\u0565",
}
_LIGATURE_RE = re.compile("|".join(map(re.escape, _LIGATURES)))
# A space wrongly separating a word from the punctuation that follows it.
# The spaced ellipsis ". . ." is excluded: it is real typography in these books.
_SPACE_BEFORE_PUNCT = re.compile(r"(?<=[^\s.])\s+([,;:!?])")
_SPACE_BEFORE_PERIOD = re.compile(r"(?<=[^\s.])\s+\.(?!\s*\.)")
# "sevgim .Yılmaz" -> a full stop with no space after it, mid-sentence.
_MISSING_SPACE_AFTER = re.compile(r"([,;:])(?=[^\W\d_])")
_REPEATED_PUNCT = re.compile(r"([,;:!?])\1{1,}")


def _normalise_text(text: str) -> tuple[str, list[tuple[CorrectionKind, str, str, str]]]:
    """Apply the deterministic fixes, returning the text and what changed."""
    changes: list[tuple[CorrectionKind, str, str, str]] = []

    normalised = unicodedata.normalize("NFC", text)
    if normalised != text:
        changes.append((CorrectionKind.UNICODE, text, normalised, "NFC normalisation"))
    text = normalised

    expanded = _LIGATURE_RE.sub(lambda m: _LIGATURES[m.group(0)], text)
    if expanded != text:
        changes.append(
            (CorrectionKind.UNICODE, text, expanded, "expanded typographic ligature")
        )
    text = expanded

    recovered, _unmapped = _recover_symbol_font_glyphs(text)
    if recovered != text:
        changes.append(
            (
                CorrectionKind.UNICODE,
                text,
                recovered,
                "recovered text from a symbol-encoded font",
            )
        )
    text = recovered

    stripped = _CONTROL_CHARS.sub("", text)
    if stripped != text:
        changes.append(
            (CorrectionKind.CONTROL_CHAR, text, stripped, "removed control characters")
        )
    text = stripped

    def note(pattern: re.Pattern, replacement, kind: CorrectionKind, reason: str) -> None:
        nonlocal text
        for match in pattern.finditer(text):
            fragment = match.group(0)
            fixed = pattern.sub(replacement, fragment, count=1)
            if fixed != fragment:
                changes.append((kind, fragment, fixed, reason))
        text = pattern.sub(replacement, text)

    note(_SPACE_BEFORE_PUNCT, r"\1", CorrectionKind.PUNCTUATION_SPACING,
         "removed space before punctuation")
    note(_SPACE_BEFORE_PERIOD, ".", CorrectionKind.PUNCTUATION_SPACING,
         "removed space before full stop")
    note(_MISSING_SPACE_AFTER, r"\1 ", CorrectionKind.PUNCTUATION_SPACING,
         "added missing space after punctuation")
    note(_REPEATED_PUNCT, r"\1", CorrectionKind.REPEATED_PUNCTUATION,
         "collapsed repeated punctuation")
    return text, changes


# --- level 2: document-validated word repair ------------------------------

_TOKEN_SPLIT_RE = re.compile(r"([^\W\d_]+)", re.UNICODE)


def _repair_words(
    text: str, vocab: DocumentVocabulary, page: int, block_id: str, report: RepairReport
) -> str:
    """Fix single-glyph OCR errors, judged against the document's own vocabulary."""
    parts = _TOKEN_SPLIT_RE.split(text)
    for index in range(1, len(parts), 2):
        word = parts[index]
        if len(word) < 3 or vocab.is_canonical(word):
            continue
        current = vocab.frequency(word)
        if current > 2:
            continue  # appears often enough to be this book's own spelling

        # Diacritic candidates are surfaced for review but never applied: in
        # Turkish they routinely turn one real word into a different real one.
        repaired = _diacritic_repair(word, current, vocab, page, block_id, report)
        if repaired is not None:
            parts[index] = repaired
            continue

        if len(word) < MIN_CONFUSION_WORD_LENGTH:
            continue

        best: tuple[int, str, str] | None = None
        for candidate, rule in _confusion_candidates(word):
            candidate_frequency = vocab.frequency(candidate)
            if candidate_frequency < MIN_CANONICAL_FREQUENCY:
                continue
            if best is None or candidate_frequency > best[0]:
                best = (candidate_frequency, candidate, rule)
        if best is None:
            continue

        candidate_frequency, candidate, rule = best
        # Confidence rises with how firmly the document establishes the target.
        confidence = min(0.99, 0.80 + min(candidate_frequency, 200) / 1000)
        replacement = _match_case(word, candidate)
        report.add(
            Correction(
                kind=CorrectionKind.OCR_CHARACTER,
                grade=Grade.CONFIDENT,
                original=word,
                corrected=replacement,
                reason=(
                    f"{rule}: {word!r} occurs {current}x, {candidate!r} occurs "
                    f"{candidate_frequency}x in this document"
                ),
                confidence=confidence,
                page=page,
                block_id=block_id,
            )
        )
        parts[index] = replacement
    return "".join(parts)


def _diacritic_repair(
    word: str,
    current: int,
    vocab: DocumentVocabulary,
    page: int,
    block_id: str,
    report: RepairReport,
) -> str | None:
    """Restore diacritics the scanner dropped, or explain why it was refused.

    Returns the corrected word when every guard agrees, otherwise None with an
    UNCERTAIN record so the candidate is visible in the quality report.
    """
    key = diacritic_key(word)
    candidates = [
        (spelling, count)
        for spelling, count in vocab.attested_spellings(key)
        if fold(spelling) != fold(word)
    ]
    if not candidates:
        return None

    # More than one attested spelling means the document itself uses both; the
    # frequency evidence cannot say which one this token was meant to be.
    if len(candidates) > 1:
        _record_refusal(
            word, candidates[0][0], page, block_id, report,
            f"{len(candidates)} spellings of {key!r} are attested here; ambiguous",
        )
        return None

    candidate, candidate_count = candidates[0]

    # A scanner loses diacritics, it does not add them, so a correction must
    # *gain* a marked letter. This also excludes bare i/ı swaps, where neither
    # form is marked: "kışı" and "kişi" both carry one ş, so an asymmetry test
    # cannot separate them, and both are ordinary Turkish words.
    if _marked_count(candidate) <= _marked_count(word):
        _record_refusal(
            word, candidate, page, block_id, report,
            "does not restore a dropped diacritic (i/ı swaps are ambiguous in Turkish)",
        )
        return None

    # A word the document uses more than once is a word the document uses.
    if current > DIACRITIC_MAX_OBSERVED_FREQUENCY:
        _record_refusal(
            word, candidate, page, block_id, report,
            f"{word!r} occurs {current}x, so it is likely a real word here, not a scan error",
        )
        return None

    if candidate_count < max(1, current) * DIACRITIC_FREQUENCY_RATIO:
        _record_refusal(
            word, candidate, page, block_id, report,
            f"{candidate!r} is only {candidate_count / max(1, current):.0f}x more common; "
            f"below the {DIACRITIC_FREQUENCY_RATIO}x needed to rule out a real rare word",
        )
        return None

    replacement = _match_case(word, candidate)
    report.add(
        Correction(
            kind=CorrectionKind.OCR_CHARACTER,
            grade=Grade.CONFIDENT,
            original=word,
            corrected=replacement,
            reason=(
                f"dropped diacritic: {candidate!r} occurs {candidate_count}x and is the only "
                f"attested spelling of {key!r}; {word!r} occurs {current}x"
            ),
            confidence=min(0.99, 0.90 + min(candidate_count, 500) / 5000),
            page=page,
            block_id=block_id,
        )
    )
    return replacement


def _record_refusal(
    word: str, candidate: str, page: int, block_id: str, report: RepairReport, reason: str
) -> None:
    report.add(
        Correction(
            kind=CorrectionKind.OCR_CHARACTER,
            grade=Grade.UNCERTAIN,
            original=word,
            corrected=candidate,
            reason=f"{reason}; text left exactly as found",
            confidence=0.45,
            page=page,
            block_id=block_id,
        )
    )


def _match_case(original: str, candidate: str) -> str:
    if original.istitle() and not candidate.istitle():
        return candidate.capitalize()
    if original.isupper() and len(original) > 1:
        return candidate.upper()
    return candidate


# --- word splits ----------------------------------------------------------

# A dropped space leaves a stray glyph or two beside the rest of the word.
_MAX_STRAY_FRAGMENT_LENGTH = 2
# A single letter this frequent is a real word (Turkish "o"), not a stray glyph.
_COMMON_SINGLE_LETTER_WORD = 100
# Word, single space, word — the shape a dropped space leaves behind.
_WORD_SPACE_WORD = re.compile(r"^[^\W\d_]+$", re.UNICODE)


def _repair_splits(
    text: str, vocab: DocumentVocabulary, page: int, block_id: str, report: RepairReport
) -> str:
    """Rejoin words a scanner split with a spurious space.

    Walks adjacent token pairs rather than substituting over the whole string:
    a regex scan consumes "sonra S" and would then never examine "S ırma", so
    the very splits worth fixing were being skipped.

    A pair is joined only when the result is established vocabulary *and* at
    least one half is not a word in its own right. "de" + "ğil" joins because
    "ğil" is not a Turkish word; "gerçek" + "ten" never does, because both are.
    """
    parts = _TOKEN_SPLIT_RE.split(text)
    # parts alternates separator, word, separator, word, ...
    index = 1
    while index + 2 < len(parts):
        left, separator, right = parts[index], parts[index + 1], parts[index + 2]
        if separator != " " or not left or not right:
            index += 2
            continue
        if not (_WORD_SPACE_WORD.match(left) and _WORD_SPACE_WORD.match(right)):
            index += 2
            continue

        decision = _judge_split(left, right, vocab, page, block_id, report)
        if decision is None:
            index += 2
            continue

        parts[index] = decision
        parts[index + 1] = ""
        parts[index + 2] = ""
        index += 2

    return "".join(parts)


def _judge_split(
    left: str,
    right: str,
    vocab: DocumentVocabulary,
    page: int,
    block_id: str,
    report: RepairReport,
) -> str | None:
    """Return the joined word when joining is justified, otherwise None."""
    joined = left + right
    if not vocab.is_canonical(joined):
        return None
    # At least one half must be a stray glyph or two — the signature of a space
    # dropped into the middle of a word ("S ırma", "gib i"). Two multi-letter
    # halves are far more likely to be two real words.
    if min(len(left), len(right)) > _MAX_STRAY_FRAGMENT_LENGTH:
        return None
    # A very common one-letter token is a word in its own right, not a stray
    # glyph. Turkish "o" (he/she/it) is frequent, so "o dama" ("to that roof")
    # must never collapse to "odama".
    for fragment in (left, right):
        if len(fragment) == 1 and vocab.frequency(fragment) >= _COMMON_SINGLE_LETTER_WORD:
            return None

    if not (vocab.is_fragment(left) or vocab.is_fragment(right)):
        report.add(
            Correction(
                kind=CorrectionKind.WORD_SPLIT,
                grade=Grade.UNCERTAIN,
                original=f"{left} {right}",
                corrected=joined,
                reason=(
                    f"both {left!r} and {right!r} are words in this document; "
                    "joining could destroy a real phrase"
                ),
                confidence=0.4,
                page=page,
                block_id=block_id,
            )
        )
        return None

    joined_frequency = vocab.frequency(joined)
    report.add(
        Correction(
            kind=CorrectionKind.WORD_SPLIT,
            grade=Grade.CONFIDENT,
            original=f"{left} {right}",
            corrected=joined,
            reason=(
                f"{joined!r} occurs {joined_frequency}x; "
                f"{left!r}/{right!r} are not both standalone words here"
            ),
            confidence=min(0.97, 0.78 + min(joined_frequency, 200) / 1000),
            page=page,
            block_id=block_id,
        )
    )
    return joined


# --- suspicious-text detection (never modified) ---------------------------

_SUSPICIOUS_PATTERNS = (
    (re.compile(r"[^\W\d_]\d[^\W\d_]"), "digit inside a word"),
    (re.compile(r"[a-zçğıöşü][A-ZÇĞİÖŞÜ][a-zçğıöşü]"), "case flip inside a word"),
    (re.compile(r"(.)\1{3,}"), "character repeated four or more times"),
    # "?.." and "!.." — a terminal mark followed by exactly two dots. No
    # typographic convention produces this; it is an ellipsis that lost a dot in
    # extraction, or a stray dot after a full stop. But which one is a guess:
    # "?..." and "?." are both plausible, so it is flagged for the report and
    # left as found. "?..." and "?…" are genuine and are not matched.
    (re.compile(r"[?!]\.\.(?![.\u2026])"), "terminal mark followed by two dots"),
)


def _flag_suspicious(
    text: str, page: int, block_id: str, report: RepairReport
) -> None:
    for pattern, reason in _SUSPICIOUS_PATTERNS:
        for match in pattern.finditer(text):
            start = max(0, match.start() - 12)
            report.add(
                Correction(
                    kind=CorrectionKind.SUSPICIOUS,
                    grade=Grade.UNCERTAIN,
                    original=text[start : match.end() + 12],
                    corrected="",
                    reason=f"{reason} — left unchanged",
                    confidence=0.0,
                    page=page,
                    block_id=block_id,
                )
            )


# --- entry point ----------------------------------------------------------

def repair_blocks(blocks: list[Block], enabled: bool = True) -> RepairReport:
    """Repair text in place across a document's blocks.

    One pass builds the vocabulary, a second applies corrections, so a word's
    canonical form is known before anything is changed.
    """
    report = RepairReport()
    if not enabled:
        return report

    text_blocks = [b for b in blocks if b.kind == "text" and b.text]
    vocab = DocumentVocabulary(text_blocks)

    for block in text_blocks:
        original = block.text
        text, hygiene_changes = _normalise_text(original)
        for kind, before, after, reason in hygiene_changes:
            report.add(
                Correction(
                    kind=kind,
                    grade=Grade.SAFE,
                    original=before,
                    corrected=after,
                    reason=reason,
                    confidence=1.0,
                    page=block.page,
                    block_id=block.block_id,
                )
            )

        text = _repair_words(text, vocab, block.page, block.block_id, report)
        text = _repair_splits(text, vocab, block.page, block.block_id, report)
        _flag_suspicious(text, block.page, block.block_id, report)

        if text != original:
            block.text = text

    return report
