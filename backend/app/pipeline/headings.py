from __future__ import annotations

import re
import statistics
from dataclasses import dataclass

from app.models.document import Block, BlockRole, StructuralNode

# Words that open a division, across the languages this pipeline targets.
# Matched case-insensitively at the start of a short, isolated line.
_DIVISION_WORDS = (
    "bölüm", "kısım", "kitap", "fasıl",          # Turkish
    "chapter", "part", "book", "section",         # English
    "kapitel", "teil", "abschnitt",               # German
    "chapitre", "partie",                         # French
    "capítulo", "parte", "capitolo",              # Spanish / Italian
    "الفصل", "الباب",                              # Arabic
)
_DIVISION_RE = re.compile(
    r"^\s*(?:%s)\b" % "|".join(re.escape(w) for w in _DIVISION_WORDS), re.IGNORECASE
)
# "1", "12.", "IV", "XIV." — a division number standing on its own.
_BARE_NUMBER_RE = re.compile(r"^\s*(\d{1,3}|[IVXLCDM]{1,7})\s*[.\)]?\s*$", re.IGNORECASE)
# "1. Kurban", "Chapter 3 — Beginnings"
_NUMBERED_TITLE_RE = re.compile(
    r"^\s*(?:(?:%s)\s+)?(\d{1,3}|[IVXLCDM]{1,7})\s*[.\):—–-]\s*\S"
    % "|".join(re.escape(w) for w in _DIVISION_WORDS),
    re.IGNORECASE,
)

_MAX_HEADING_CHARS = 120
_MAX_HEADING_LINES = 2  # a long title may wrap once; more than that is body text
_MAX_HEADING_WORDS = 12  # headings are terse; a longer line is a sentence
_CENTRED_TOLERANCE = 0.06  # fraction of page width
_SPARSE_PAGE_CHARS = 900
# "1." / "a)" / "iv." opening a line — shared by numbered headings and list items.
_ITEM_NUMBER_RE = re.compile(r"^\s*(\d{1,3}|[a-zA-Z]|[ivxlcdmIVXLCDM]{1,6})[.)]\s+\S")

# Signals that show the typesetter *meant* this as a heading. Geometry alone is
# not enough: on a sparse front-matter page a URL, a series line and an epigraph
# are all centred and isolated, and would otherwise all score as headings.
_STRONG_SIGNALS = frozenset(
    {"display-type", "larger-type", "slightly-larger-type", "bold", "division-word",
     "numbered-title", "all-caps"}
)

_URL_RE = re.compile(r"^(https?://|www\.)|\.(com|org|net|io|co)\b", re.IGNORECASE)
# An epigraph or pull quote opens with a quotation mark; it is content, not a
# heading, however isolated it is on the page.
_OPENS_AS_QUOTE_RE = re.compile(r'^\s*[«"“”\'‘’]')

# Score at or above which a block is accepted as a heading, and the score that
# additionally marks it as a top-level division. Both are deliberately high:
# inventing chapters to raise a count is worse than reporting thin structure.
HEADING_THRESHOLD = 0.55
CHAPTER_THRESHOLD = 0.80

# Two heading scales within this relative distance are the same visual level.
_LEVEL_GROUP_TOLERANCE = 0.18


@dataclass
class HeadingEvidence:
    """Why a block was judged a heading — kept so decisions stay explainable."""

    score: float
    signals: list[str]
    is_division: bool

    @property
    def confidence(self) -> float:
        return min(0.99, self.score)


def _is_centred(block: Block) -> bool:
    centre = (block.bbox[0] + block.bbox[2]) / 2
    return abs(centre - block.page_width / 2) <= block.page_width * _CENTRED_TOLERANCE


def _text_of(block: Block) -> str:
    return " ".join(block.text.split())


def score_heading(
    block: Block,
    body_size: float,
    gap_above: float,
    gap_below: float,
    line_gap: float,
    page_char_count: int,
    is_first_content_block_on_page: bool,
) -> HeadingEvidence:
    """Combine independent structural signals into a heading score.

    Deliberately not typography-only: scanned books re-set from an OCR layer
    often carry almost no size variation, so a size-based rule alone finds
    nothing. Each signal is weak by itself; a heading needs several to agree.
    """
    text = _text_of(block)
    signals: list[str] = []
    score = 0.0

    if not text or len(text) > _MAX_HEADING_CHARS:
        return HeadingEvidence(0.0, signals, False)
    if _URL_RE.search(text) or _OPENS_AS_QUOTE_RE.match(text):
        return HeadingEvidence(0.0, signals, False)

    # A heading occupies one line, occasionally two when a long title wraps.
    # Anything taller is body content — and a block whose every line opens with
    # its own number is a list, which "1. Title" numbering would otherwise make
    # look exactly like a numbered heading.
    source_lines = [ln for ln in block.text.split("\n") if ln.strip()]
    if len(source_lines) > _MAX_HEADING_LINES:
        return HeadingEvidence(0.0, signals, False)
    if len(source_lines) > 1 and all(_ITEM_NUMBER_RE.match(ln.strip()) for ln in source_lines):
        return HeadingEvidence(0.0, signals, False)

    size_ratio = (block.font_size or body_size) / body_size if body_size else 1.0

    # --- typography -------------------------------------------------------
    if size_ratio >= 1.8:
        score += 0.45
        signals.append("display-type")
    elif size_ratio >= 1.35:
        score += 0.32
        signals.append("larger-type")
    elif size_ratio >= 1.12:
        score += 0.18
        signals.append("slightly-larger-type")
    if block.bold and size_ratio >= 1.02:
        score += 0.14
        signals.append("bold")

    # --- lexical / numbering ---------------------------------------------
    if _DIVISION_RE.match(text):
        score += 0.30
        signals.append("division-word")
    if _NUMBERED_TITLE_RE.match(text):
        score += 0.22
        signals.append("numbered-title")
    if text.isupper() and len(text) > 2:
        score += 0.16
        signals.append("all-caps")

    # --- geometry ---------------------------------------------------------
    if _is_centred(block) and len(text) < 60:
        score += 0.18
        signals.append("centred")
    isolated_above = gap_above > line_gap * 2.2
    isolated_below = gap_below > line_gap * 1.6
    if isolated_above and isolated_below:
        score += 0.24
        signals.append("isolated")
    elif isolated_above:
        score += 0.12
        signals.append("space-above")

    # --- page context -----------------------------------------------------
    if page_char_count and page_char_count < _SPARSE_PAGE_CHARS:
        score += 0.16
        signals.append("sparse-page")
        if is_first_content_block_on_page:
            score += 0.10
            signals.append("opens-page")

    # A line ending in sentence punctuation is prose, however it is set. Only a
    # division word earns an exemption ("Chapter One."); numbering does not,
    # because "1. Some note text." is a list entry, not a heading.
    if text.endswith((".", "!", "?")) and not _BARE_NUMBER_RE.match(text):
        if "division-word" not in signals:
            score -= 0.30
            signals.append("ends-like-prose")

    # Headings are terse. A long line is a sentence that happens to be set apart.
    if len(text.split()) > _MAX_HEADING_WORDS and "division-word" not in signals:
        score -= 0.25
        signals.append("too-wordy")

    # Geometry corroborates a heading; it cannot establish one on its own.
    if not any(s in _STRONG_SIGNALS for s in signals):
        signals.append("geometry-only")
        return HeadingEvidence(0.0, signals, False)

    is_division = (
        size_ratio >= 1.8
        or "division-word" in signals
        or ("sparse-page" in signals and size_ratio >= 1.35)
    )
    return HeadingEvidence(max(0.0, score), signals, is_division)


def merge_division_numbers(nodes: list[StructuralNode]) -> int:
    """Fold a lone division number into the title beneath it.

    Books commonly set the number on its own line above the chapter title
    ("1" over "Kurban"). Left apart, the navigation entry reads "Kurban" and
    loses its position in the book, while the stray number becomes a heading of
    its own. Returns the number of merges performed.
    """
    merged_count = 0
    result: list[StructuralNode] = []
    index = 0

    while index < len(nodes):
        node = nodes[index]
        nxt = nodes[index + 1] if index + 1 < len(nodes) else None

        if (
            node.role == BlockRole.HEADING
            and nxt is not None
            and nxt.role == BlockRole.HEADING
            and node.page == nxt.page
            and _BARE_NUMBER_RE.match(_text_of_node(node))
            and not _BARE_NUMBER_RE.match(_text_of_node(nxt))
        ):
            number = _text_of_node(node).rstrip(".) ")
            title = _text_of_node(nxt)
            nxt.text = f"{number}. {title}"
            nxt.source_block_ids = list(node.source_block_ids) + list(nxt.source_block_ids)
            nxt.level = min(node.level or 1, nxt.level or 1)
            nxt.confidence = max(node.confidence, nxt.confidence)
            result.append(nxt)
            merged_count += 1
            index += 2
            continue

        result.append(node)
        index += 1

    nodes[:] = result
    return merged_count


def _text_of_node(node: StructuralNode) -> str:
    return " ".join(node.text.split())


def assign_heading_levels(nodes: list[StructuralNode]) -> None:
    """Map detected headings onto h1..h4 using the sizes actually present.

    Levels come from the document's own distinct heading scales rather than
    absolute point sizes, so a book set entirely in 9pt still gets a sensible
    hierarchy instead of everything collapsing to one level.
    """
    headings = [n for n in nodes if n.role == BlockRole.HEADING]
    if not headings:
        return

    scales = sorted({round(n.heading_scale, 2) for n in headings if n.heading_scale}, reverse=True)
    if not scales:
        for n in headings:
            n.level = n.level or 1
        return

    # Collapse scales that are within a relative tolerance of each other. A
    # fixed absolute step splits hairs: a 3.53x cover title and 3.27x chapter
    # titles are the same display size to a reader, but an absolute rule made
    # them separate levels and let the one-off cover monopolise h1, demoting
    # every real chapter to h2.
    grouped: list[float] = []
    for scale in scales:
        if not grouped or (grouped[-1] - scale) / max(grouped[-1], 0.01) > _LEVEL_GROUP_TOLERANCE:
            grouped.append(scale)

    for node in headings:
        scale = round(node.heading_scale or grouped[0], 2)
        level = min(len(grouped), 4)
        for index, group in enumerate(grouped[:4]):
            if scale >= group * (1 - _LEVEL_GROUP_TOLERANCE):
                level = index + 1
                break
        node.level = level


def typical_line_gap(blocks: list[Block]) -> float:
    gaps = [b.font_size * 0.35 for b in blocks if b.font_size]
    return statistics.median(gaps) if gaps else 3.0
