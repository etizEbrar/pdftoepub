from __future__ import annotations

import re
import statistics

from app.models.document import Block, BlockRole, StructuralNode
from app.pipeline import headings as headings_module

BULLET_RE = re.compile(r"^[•●○◦▪‣–\-\*]\s+")
NUMBERED_RE = re.compile(r"^(\d{1,3}|[a-zA-Z]|[ivxlcdmIVXLCDM]{1,6})[.)]\s+")
# A note body opens with its marker; unlike NUMBERED_RE the separator is
# optional, since footnotes are commonly set as "1 Text" with no punctuation.
NOTE_ENTRY_RE = re.compile(r"^\s*([\d]{1,4}|[*†‡§¶#]{1,3})[.)\]]?\s+\S")
TERMINAL_PUNCT = ".!?\"”’:;»)]"

# Characters books use to draw a scene divider. A centred line made only of
# these is a thematic break, not prose — and OCR renders the same divider
# differently on every page ("........", "• • • • •", ".. . • .."), which is
# what made these look like stray ellipsis junk in the EPUB.
_ORNAMENT_CHARS = set(".•*—–~§¤°◆◇■□▪▫★☆·⋅∙‧∗+×#")
_MIN_ORNAMENT_MARKS = 3
_MAX_ORNAMENT_CHARS = 24
_ORNAMENT_CENTRE_TOLERANCE = 0.08  # fraction of page width


def _looks_like_thematic_break(block: Block) -> bool:
    """A short, centred line containing nothing but ornament characters.

    Requires the *whole* block to be ornaments, so a genuine ellipsis inside a
    sentence ("Keşke . . .") is never mistaken for a divider.
    """
    text = " ".join(block.text.split())
    if not text or len(text) > _MAX_ORNAMENT_CHARS:
        return False
    marks = [c for c in text if not c.isspace()]
    if len(marks) < _MIN_ORNAMENT_MARKS:
        return False
    if any(c not in _ORNAMENT_CHARS for c in marks):
        return False
    centre = (block.bbox[0] + block.bbox[2]) / 2
    return abs(centre - block.page_width / 2) <= block.page_width * _ORNAMENT_CENTRE_TOLERANCE


def body_font_size(blocks: list[Block]) -> float:
    sizes: list[float] = []
    for b in blocks:
        if b.kind != "text" or not b.font_size:
            continue
        weight = max(1, len(b.text))
        sizes.extend([b.font_size] * min(weight, 500))
    if not sizes:
        return 10.0
    return statistics.median(sizes)


def _gap_above(ordered: list[Block], i: int) -> float:
    if i == 0:
        return float("inf")
    prev, cur = ordered[i - 1], ordered[i]
    if prev.page != cur.page or prev.column != cur.column:
        return float("inf")
    return cur.bbox[1] - prev.bbox[3]


def _gap_below(ordered: list[Block], i: int) -> float:
    if i == len(ordered) - 1:
        return float("inf")
    cur, nxt = ordered[i], ordered[i + 1]
    if cur.page != nxt.page or cur.column != nxt.column:
        return float("inf")
    return nxt.bbox[1] - cur.bbox[3]


def _typical_line_gap(blocks: list[Block]) -> float:
    gaps = []
    for b in blocks:
        lines = b.text.split("\n")
        if len(lines) > 1 and b.font_size:
            gaps.append(b.font_size * 0.3)
    return statistics.median(gaps) if gaps else 3.0


def _heading_level(size_ratio: float) -> int:
    if size_ratio >= 1.55:
        return 1
    if size_ratio >= 1.3:
        return 2
    if size_ratio >= 1.15:
        return 3
    return 4


def _first_line(text: str) -> str:
    return text.split("\n", 1)[0].strip()


# A note set at 0.75x body or smaller is unambiguously note-sized. Between that
# and 0.85x, type is often just a slightly tighter setting of ordinary prose, so
# an opening marker is required as corroboration. Without this second gate,
# paragraph continuations low on the page were being rendered as footnotes.
_FOOTNOTE_CLEAR_SIZE_RATIO = 0.75
_FOOTNOTE_MAX_SIZE_RATIO = 0.90
_FOOTNOTE_PAGE_FRACTION = 0.66


def _looks_like_footnote_body(
    block: Block, body_size: float, page_has_body_text: bool = True
) -> bool:
    if not block.font_size or not body_size:
        return False
    if block.bbox[1] <= block.page_height * _FOOTNOTE_PAGE_FRACTION:
        return False
    # A footnote annotates body text, so there must be body text above it. A
    # copyright page is entirely small type with nothing to annotate; without
    # this the publisher's address and phone numbers become footnotes.
    if not page_has_body_text:
        return False

    ratio = block.font_size / body_size
    if ratio > _FOOTNOTE_MAX_SIZE_RATIO:
        return False
    if ratio <= _FOOTNOTE_CLEAR_SIZE_RATIO:
        return True
    return bool(NOTE_ENTRY_RE.match(block.text.strip()))


def classify_blocks(
    ordered_blocks: list[Block], furniture: dict[str, BlockRole] | None = None
) -> list[StructuralNode]:
    """One StructuralNode per text Block, tagged with role/level/confidence using
    typography + geometry signals (spec section 16 — never font size alone).

    `furniture` maps block_id -> HEADER/FOOTER/PAGE_NUMBER for blocks already
    identified as running page furniture (see headers_footers.py); those bypass
    the heuristics below entirely and are excluded from EPUB rendering downstream.
    """
    furniture = furniture or {}
    text_blocks = [b for b in ordered_blocks if b.kind == "text" and b.block_id not in furniture]
    body_size = body_font_size(text_blocks)
    pages_with_body_text = {
        b.page
        for b in text_blocks
        if b.font_size and body_size and b.font_size >= body_size * _FOOTNOTE_MAX_SIZE_RATIO
    }
    line_gap = _typical_line_gap(text_blocks)
    # Page-level context for the heading scorer: a chapter opener typically
    # sits alone on a page that carries far less text than the book's norm.
    page_char_counts: dict[int, int] = {}
    first_content_block: dict[int, str] = {}
    for b in text_blocks:
        page_char_counts[b.page] = page_char_counts.get(b.page, 0) + len(b.text.strip())
        first_content_block.setdefault(b.page, b.block_id)
    left_margins: dict[int, float] = {}
    for b in text_blocks:
        key = b.column
        left_margins[key] = min(left_margins.get(key, b.bbox[0]), b.bbox[0])

    nodes: list[StructuralNode] = []
    for i, b in enumerate(ordered_blocks):
        if b.kind == "image":
            nodes.append(
                StructuralNode(
                    node_id=f"n_{b.block_id}",
                    role=BlockRole.IMAGE,
                    confidence=1.0,
                    source_block_ids=[b.block_id],
                    image_ref=b.image_ref,
                    page=b.page,
                )
            )
            continue

        if b.block_id in furniture:
            nodes.append(
                StructuralNode(
                    node_id=f"n_{b.block_id}",
                    role=furniture[b.block_id],
                    text=b.text.strip(),
                    confidence=0.9,
                    source_block_ids=[b.block_id],
                    page=b.page,
                )
            )
            continue

        size_ratio = (b.font_size or body_size) / body_size if body_size else 1.0
        text = b.text.strip()
        first_line = _first_line(text)
        gap_above = _gap_above(ordered_blocks, i)
        gap_below = _gap_below(ordered_blocks, i)
        indented = b.bbox[0] > left_margins.get(b.column, b.bbox[0]) + max(body_size * 1.2, 8)

        role = BlockRole.PARAGRAPH
        level = None
        confidence = 0.85
        evidence: list[str] = []

        if _looks_like_thematic_break(b):
            nodes.append(
                StructuralNode(
                    node_id=f"n_{b.block_id}",
                    role=BlockRole.THEMATIC_BREAK,
                    text=text,
                    confidence=0.9,
                    source_block_ids=[b.block_id],
                    page=b.page,
                    evidence=["centred-ornament-row"],
                )
            )
            continue

        # Multi-signal heading scoring (see pipeline/headings.py). Typography
        # alone is useless on a scanned book re-set from an OCR layer, where
        # nearly every glyph is the same size.
        heading_evidence = headings_module.score_heading(
            b,
            body_size,
            gap_above=gap_above,
            gap_below=gap_below,
            line_gap=line_gap,
            page_char_count=page_char_counts.get(b.page, 0),
            is_first_content_block_on_page=first_content_block.get(b.page) == b.block_id,
        )
        if heading_evidence.score >= headings_module.HEADING_THRESHOLD:
            role = BlockRole.HEADING
            level = _heading_level(size_ratio)
            confidence = heading_evidence.confidence
            evidence = heading_evidence.signals
        elif BULLET_RE.match(first_line) or NUMBERED_RE.match(first_line):
            # PyMuPDF sometimes groups several adjacent bulleted/numbered lines
            # into one block when the vertical gap between them is small. If
            # every line in the block starts its own marker, these are
            # separate list items, not one item with wrapped continuation
            # lines — split them out now rather than merging them later.
            raw_lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
            if len(raw_lines) > 1 and all(BULLET_RE.match(ln) or NUMBERED_RE.match(ln) for ln in raw_lines):
                for li, line in enumerate(raw_lines):
                    nodes.append(
                        StructuralNode(
                            node_id=f"n_{b.block_id}_{li}",
                            role=BlockRole.LIST_ITEM,
                            text=line,
                            confidence=0.85,
                            source_block_ids=[b.block_id],
                            bold=b.bold,
                            italic=b.italic,
                            page=b.page,
                        )
                    )
                continue
            role = BlockRole.LIST_ITEM
            confidence = 0.85
        elif indented and b.italic:
            role = BlockRole.QUOTE
            confidence = 0.7
        elif _looks_like_footnote_body(b, body_size, b.page in pages_with_body_text):
            # Several notes stacked in the footnote area are usually merged into
            # one block. When every line opens with its own marker they are
            # distinct notes, and must be split or they'd all link to whichever
            # marker happened to come first.
            raw_lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
            if len(raw_lines) > 1 and all(NOTE_ENTRY_RE.match(ln) for ln in raw_lines):
                for li, line in enumerate(raw_lines):
                    nodes.append(
                        StructuralNode(
                            node_id=f"n_{b.block_id}_{li}",
                            role=BlockRole.FOOTNOTE,
                            text=line,
                            confidence=0.7,
                            source_block_ids=[b.block_id],
                            page=b.page,
                        )
                    )
                continue
            role = BlockRole.FOOTNOTE
            confidence = 0.6  # refined by footnotes.py, which owns final footnote linking

        nodes.append(
            StructuralNode(
                node_id=f"n_{b.block_id}",
                role=role,
                text=text,
                level=level,
                confidence=confidence,
                source_block_ids=[b.block_id],
                bold=b.bold,
                italic=b.italic,
                page=b.page,
                heading_scale=size_ratio if role == BlockRole.HEADING else None,
                evidence=evidence,
            )
        )

    return nodes
