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

    def frequency(self, word: str) -> int:
        return self._freq.get(fold(word), 0)

    def is_canonical(self, word: str) -> bool:
        return self.frequency(word) >= MIN_CANONICAL_FREQUENCY

    def is_fragment(self, word: str) -> bool:
        """True when a token is too rare to be a standalone word here."""
        return self.frequency(word) <= MAX_FRAGMENT_FREQUENCY


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
        _report_ambiguous(word, current, vocab, page, block_id, report)

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


def _report_ambiguous(
    word: str,
    current: int,
    vocab: DocumentVocabulary,
    page: int,
    block_id: str,
    report: RepairReport,
) -> None:
    """Record a plausible diacritic fix without applying it.

    The user sees these in the quality report, so a genuine scan error is
    visible rather than silently accepted — but the text keeps whatever the
    source actually said.
    """
    for candidate, rule in _confusion_candidates(word, AMBIGUOUS_CONFUSIONS):
        candidate_frequency = vocab.frequency(candidate)
        if candidate_frequency < MIN_CANONICAL_FREQUENCY:
            continue
        report.add(
            Correction(
                kind=CorrectionKind.OCR_CHARACTER,
                grade=Grade.UNCERTAIN,
                original=word,
                corrected=candidate,
                reason=(
                    f"{rule} would give {candidate!r} ({candidate_frequency}x), but Turkish "
                    "minimal pairs make this unsafe without a lexicon; text left as found"
                ),
                confidence=0.45,
                page=page,
                block_id=block_id,
            )
        )
        return


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
