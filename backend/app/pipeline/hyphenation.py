from __future__ import annotations

import re
from collections.abc import Iterable

# ASCII hyphen, Unicode hyphen, non-breaking hyphen, and SOFT HYPHEN (U+00AD).
#
# The soft hyphen matters more than it looks: typesetters use it to mark a
# discretionary break, and scanners/OCR emit it at every justified line break.
# A single real Turkish book carried 2,279 of them against 72 ASCII hyphens, so
# omitting it left a visible artifact ("sonra\xadsında") on nearly every page.
_HYPHEN_CHARS = "-‐‑­"
# Deliberately excludes en dash (–) and em dash (—): those are never
# line-wrap artifacts and must never be touched.

# A soft hyphen is invisible, so it can also appear *inside* a line rather than
# at its end. Anywhere other than a line break it carries no meaning for
# reflowable text and would render as a stray character in some readers.
SOFT_HYPHEN = "­"


# A word set intact somewhere in the document, and the hyphenated compounds it
# sets intact. Both are read off the book itself, never from a dictionary.
_PLAIN_WORD_RE = re.compile(r"[^\W\d_]{2,}", re.UNICODE)
_HYPHENATED_RE = re.compile(r"([^\W\d_]{2,})[-‐‑]([^\W\d_]{2,})", re.UNICODE)


def _fold(word: str) -> str:
    """Case-fold without Turkish's dotted-I hazard (see textrepair.fold)."""
    return word.replace("İ", "i").replace("I", "ı").lower()


class HyphenEvidence:
    """How this document spells the words it breaks across lines.

    A line-end hyphen is ambiguous: "ge-/liyorum" is one word split at the
    margin, "flux-/switching" is a compound split at its own hyphen. Nothing in
    the two fragments distinguishes them. The document usually settles it,
    because a term used once is used again: if "flux-switching" appears intact
    elsewhere, the hyphen belongs to the word.
    """

    def __init__(self, texts: Iterable[str]) -> None:
        self.closed: set[str] = set()
        self.hyphenated: set[str] = set()
        for text in texts:
            if not text:
                continue
            for line in text.split("\n"):
                # Only hyphens *within* a line are evidence; one at the end of
                # a line is the very artifact we are trying to resolve.
                for left, right in _HYPHENATED_RE.findall(line):
                    self.hyphenated.add(_fold(left) + "-" + _fold(right))
                for word in _PLAIN_WORD_RE.findall(line):
                    self.closed.add(_fold(word))

    def keeps_hyphen(self, left: str, right: str) -> bool | None:
        """True to keep the hyphen, False to close up, None when unattested."""
        pair = _fold(left) + "-" + _fold(right)
        closed = _fold(left + right)
        seen_hyphenated = pair in self.hyphenated
        seen_closed = closed in self.closed
        if seen_hyphenated == seen_closed:
            return None  # both or neither: the document does not decide
        return seen_hyphenated


_SPACE_RUN_RE = re.compile(r"[ \t]{2,}")
_TRAILING_WORD_RE = re.compile(r"([^\W\d_]{2,})$", re.UNICODE)
_LEADING_WORD_RE = re.compile(r"^([^\W\d_]{2,})", re.UNICODE)


def join_lines_with_hyphenation_repair(
    lines: list[str], evidence: HyphenEvidence | None = None
) -> str:
    """Join a paragraph's wrapped source lines into one string, undoing hyphenation
    that PDF line-wrapping introduced (spec section 14) while leaving genuine
    hyphenated words alone.

    Heuristic: a trailing hyphen is treated as a line-wrap artifact only when both
    the character before it and the first character of the next line are lowercase
    letters — the pattern produced by justified/wrapped body text. This is a known
    trade-off: a real compound word that happens to break exactly at its own hyphen
    (e.g. "self-\\nesteem") will also be merged. Dictionary-based disambiguation is
    out of scope for this heuristic; when in doubt this still favors the far more
    common case (wrapped single words) over the rarer one.
    """
    if not lines:
        return ""
    result = lines[0].rstrip()
    for raw_next in lines[1:]:
        next_line = raw_next.strip()
        if not next_line:
            continue
        if (
            result
            and result[-1] in _HYPHEN_CHARS
            and len(result) >= 2
            and result[-2].isalpha()
            and next_line[0].isalpha()
            and next_line[0].islower()
        ):
            # The document's own spelling decides whether the hyphen was the
            # word's or the typesetter's. Unattested, the old heuristic holds:
            # a wrapped single word is far commoner than a compound that broke
            # exactly at its own hyphen.
            keep = None
            if evidence is not None:
                left = _TRAILING_WORD_RE.search(result[:-1])
                right = _LEADING_WORD_RE.match(next_line)
                if left and right:
                    keep = evidence.keeps_hyphen(left.group(1), right.group(1))
            result = result + next_line if keep else result[:-1] + next_line
            continue
        if result and not result.endswith((" ", "\n")):
            result += " "
        result += next_line
    # Any soft hyphen that survived was not at a line break, so it is a
    # discretionary mark with no meaning once the text reflows.
    result = result.replace(SOFT_HYPHEN, "")
    # Runs of spaces come through from the source's own justification. XHTML
    # collapses them on render anyway, so this alters nothing a reader sees; it
    # keeps them from surviving inside an emphasis span as a run of blanks.
    # Only spacing is touched: no word, mark or line break is altered.
    return _SPACE_RUN_RE.sub(" ", result)
