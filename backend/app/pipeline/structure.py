from __future__ import annotations

import re
import statistics

from app.models.document import Block, BlockRole, StructuralNode

BULLET_RE = re.compile(r"^[•●○◦▪‣–\-\*]\s+")
NUMBERED_RE = re.compile(r"^(\d{1,3}|[a-zA-Z]|[ivxlcdmIVXLCDM]{1,6})[.)]\s+")
# A note body opens with its marker; unlike NUMBERED_RE the separator is
# optional, since footnotes are commonly set as "1 Text" with no punctuation.
NOTE_ENTRY_RE = re.compile(r"^\s*([\d]{1,4}|[*†‡§¶#]{1,3})[.)\]]?\s+\S")
TERMINAL_PUNCT = ".!?\"”’:;»)]"


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
    line_gap = _typical_line_gap(text_blocks)
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
        isolated = gap_above > line_gap * 1.6 and gap_below > line_gap * 1.2
        is_short = len(text) <= 140 and "\n" not in text.strip("\n")[:141]
        ends_with_terminal = bool(text) and text[-1] in TERMINAL_PUNCT
        indented = b.bbox[0] > left_margins.get(b.column, b.bbox[0]) + max(body_size * 1.2, 8)

        role = BlockRole.PARAGRAPH
        level = None
        confidence = 0.85

        looks_like_heading = (
            is_short
            and not ends_with_terminal
            and (b.bold or size_ratio >= 1.15 or (first_line.isupper() and len(first_line) > 2))
            and size_ratio >= 1.05
        )
        if looks_like_heading and isolated:
            role = BlockRole.HEADING
            level = _heading_level(size_ratio)
            strong = (b.bold and size_ratio >= 1.15) or size_ratio >= 1.4
            confidence = 0.95 if strong else 0.75
        elif looks_like_heading and not isolated:
            # Same typographic signal but not visually isolated — still plausible
            # (e.g. a heading immediately followed by its first paragraph) but
            # lower confidence since isolation is a strong independent signal.
            role = BlockRole.HEADING
            level = _heading_level(size_ratio)
            confidence = 0.65
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
        elif b.font_size and body_size and b.font_size < body_size * 0.85 and b.bbox[1] > b.page_height * 0.75:
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
            )
        )

    return nodes
