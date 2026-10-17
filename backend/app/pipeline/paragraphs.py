from __future__ import annotations

import statistics
from dataclasses import dataclass

from app.models.document import Block, BlockRole, StructuralNode
from app.pipeline.footnotes import strip_all_sentinels
from app.pipeline.hyphenation import HyphenEvidence, join_lines_with_hyphenation_repair
from app.pipeline.structure import BULLET_RE, NUMBERED_RE, TERMINAL_PUNCT


@dataclass
class _Geometry:
    """Where a paragraph's last line ends and the next block's first begins."""

    last_line_full: bool
    next_indented: bool
    crosses_boundary: bool
    uses_indents: bool


def _continues(
    prev_last_line: str, next_first_line: str, geometry: _Geometry | None = None
) -> tuple[bool, float]:
    """Decide whether `next_first_line` is a wrapped continuation of the paragraph
    ending in `prev_last_line`, per spec section 13: use surrounding text, not the
    mere presence of a PDF line/page break.

    Primary signal: the previous line doesn't end a sentence. A lowercase next
    line reinforces confidence but isn't required — capitalized proper nouns can
    legitimately start a wrapped (non-paragraph-initial) line.

    Where the page geometry is known it decides the cases punctuation cannot.
    A line that wraps fills the measure; one that stops short of the margin
    ended there on purpose — a heading, a byline, a label — whatever its last
    character. A first line set in from the margin opens a paragraph.
    """
    prev_stripped = prev_last_line.rstrip()
    next_stripped = next_first_line.lstrip()
    if not prev_stripped or not next_stripped:
        return False, 0.0
    reinforced = next_stripped[0].islower()
    ends_sentence = prev_stripped[-1] in TERMINAL_PUNCT

    if geometry is None:
        if ends_sentence:
            return False, 0.0
        return True, (0.9 if reinforced else 0.7)

    if ends_sentence:
        # A sentence that ended exactly at the foot of a page or column. In a
        # book that indents its paragraphs, a full last line followed by an
        # unindented one is the same paragraph carrying on.
        if (
            geometry.crosses_boundary
            and geometry.uses_indents
            and geometry.last_line_full
            and not geometry.next_indented
        ):
            return True, 0.75
        return False, 0.0
    if not geometry.last_line_full:
        return (True, 0.7) if reinforced else (False, 0.0)
    if geometry.next_indented and not reinforced:
        return False, 0.0
    return True, (0.9 if reinforced else 0.7)


@dataclass
class _LineBox:
    x0: float
    x1: float


def _line_boxes(block: Block) -> list[_LineBox]:
    boxes: list[_LineBox] = []
    current = []
    for span in block.spans:
        if span.text.strip():
            current.append(span)
        if span.line_break_after and current:
            boxes.append(_LineBox(min(s.bbox[0] for s in current), max(s.bbox[2] for s in current)))
            current = []
    if current:
        boxes.append(_LineBox(min(s.bbox[0] for s in current), max(s.bbox[2] for s in current)))
    return boxes


# A wrapped line ends within this share of the measure from its right edge.
# Justified type ends exactly on it; ragged type within a word or two.
_FULL_LINE_TOLERANCE = 0.12
# A paragraph's first line is set in by at least this many type sizes.
_INDENT_SIZE_RATIO = 0.8
# Share of a book's multi-line paragraphs that must open indented before an
# unindented line is evidence of a continuation.
_INDENTED_STYLE_SHARE = 0.5


class _Layout:
    """The measure of each page and column, read from the book's own prose."""

    def __init__(self, blocks: list[Block]) -> None:
        lefts: dict[tuple[int, int], list[float]] = {}
        rights: dict[tuple[int, int], list[float]] = {}
        all_lefts: dict[int, list[float]] = {}
        all_rights: dict[int, list[float]] = {}
        indented = paragraphs = 0
        for block in blocks:
            if block.kind != "text":
                continue
            boxes = _line_boxes(block)
            if len(boxes) < 3:
                continue
            key = (block.page, block.column)
            # Lines after the first: the first may be indented.
            left = min(b.x0 for b in boxes[1:])
            right = max(b.x1 for b in boxes)
            lefts.setdefault(key, []).append(left)
            rights.setdefault(key, []).append(right)
            all_lefts.setdefault(block.column, []).append(left)
            all_rights.setdefault(block.column, []).append(right)
            size = block.font_size or 10.0
            paragraphs += 1
            if boxes[0].x0 > left + size * _INDENT_SIZE_RATIO:
                indented += 1
        self._lefts = {k: statistics.median(v) for k, v in lefts.items()}
        self._rights = {k: statistics.median(v) for k, v in rights.items()}
        self._column_lefts = {k: statistics.median(v) for k, v in all_lefts.items()}
        self._column_rights = {k: statistics.median(v) for k, v in all_rights.items()}
        self.uses_indents = paragraphs >= 5 and indented / paragraphs >= _INDENTED_STYLE_SHARE

    def measure(self, block: Block) -> tuple[float, float] | None:
        key = (block.page, block.column)
        left = self._lefts.get(key, self._column_lefts.get(block.column))
        right = self._rights.get(key, self._column_rights.get(block.column))
        if left is None or right is None or right <= left:
            return None
        return left, right

    def geometry(self, prev: Block, nxt: Block) -> _Geometry | None:
        prev_measure = self.measure(prev)
        next_measure = self.measure(nxt)
        prev_boxes = _line_boxes(prev)
        next_boxes = _line_boxes(nxt)
        if not prev_measure or not next_measure or not prev_boxes or not next_boxes:
            return None
        left, right = prev_measure
        width = right - left
        last = prev_boxes[-1]
        last_line_full = (
            last.x1 >= right - width * _FULL_LINE_TOLERANCE
            and last.x0 <= left + width * 0.3
        )
        next_left, _ = next_measure
        size = nxt.font_size or 10.0
        next_indented = next_boxes[0].x0 > next_left + size * _INDENT_SIZE_RATIO
        return _Geometry(
            last_line_full=last_line_full,
            next_indented=next_indented,
            crosses_boundary=prev.page != nxt.page or prev.column != nxt.column,
            uses_indents=self.uses_indents,
        )


# Roles whose consecutive nodes form one flowing block of prose. A block quote
# wraps across lines exactly as a paragraph does, and leaving it out produced one
# <blockquote> per line of the extract instead of one per quotation.
_MERGEABLE_ROLES = (BlockRole.PARAGRAPH, BlockRole.QUOTE)

# Set apart from the text without interrupting it. A running head between the
# last line of one page and the first of the next ended every paragraph that
# crossed a page: on a 168-page book that was nearly every page. Notes and
# figures float the same way, and are put after the paragraph they interrupted.
_TRANSPARENT_ROLES = (
    BlockRole.HEADER,
    BlockRole.FOOTER,
    BlockRole.PAGE_NUMBER,
    BlockRole.FOOTNOTE,
    BlockRole.IMAGE,
    BlockRole.CAPTION,
    BlockRole.TABLE,
    BlockRole.IMAGE_FALLBACK,
)


def _item_marker(text: str) -> tuple[str, int | None] | None:
    """("bullet", None) or ("number", n) for a line that opens a list item."""
    plain = strip_all_sentinels(text).lstrip()
    if BULLET_RE.match(plain):
        return "bullet", None
    match = NUMBERED_RE.match(plain)
    if match and match.group(1).isdigit():
        return "number", int(match.group(1))
    return None


def _opens_next_item(line: str, current_item_text: str) -> bool:
    """Whether `line` starts the item after the one whose text is given.

    MuPDF's blocks do not respect a list's items: one block can hold the end
    of item 1 and the start of item 2. A number opens an item only when it is
    the next in sequence, so a wrapped line that happens to begin "3." does
    not.
    """
    current = _item_marker(current_item_text)
    marker = _item_marker(line)
    if current is None or marker is None or marker[0] != current[0]:
        return False
    if marker[0] == "bullet":
        return True
    return current[1] is not None and marker[1] == current[1] + 1


def reconstruct_paragraphs(
    nodes: list[StructuralNode],
    evidence: HyphenEvidence | None = None,
    blocks_by_id: dict[str, Block] | None = None,
) -> list[StructuralNode]:
    """Merge consecutive prose nodes (which may span PDF blocks, columns, and
    pages) into full logical paragraphs, repairing hyphenation across the joins.

    Merging is per role: a paragraph never absorbs the block quote that follows
    it, and vice versa, because the change of role is itself a boundary. A
    list item does take the paragraph that finishes it on the next page.
    """
    blocks_by_id = blocks_by_id or {}
    layout = _Layout(list(blocks_by_id.values())) if blocks_by_id else None

    result: list[StructuralNode] = []
    run_nodes: list[StructuralNode] = []
    run_lines: list[str] = []
    run_source_ids: list[str] = []
    run_confidence = 1.0
    run_page: int | None = None
    run_role: BlockRole = BlockRole.PARAGRAPH
    held: list[StructuralNode] = []

    def flush() -> None:
        nonlocal run_nodes, run_lines, run_source_ids, run_confidence, run_page, held
        if run_lines:
            if run_role == BlockRole.LIST_ITEM and len(run_nodes) == 1:
                result.append(run_nodes[0])
            else:
                text = join_lines_with_hyphenation_repair(run_lines, evidence)
                result.append(
                    StructuralNode(
                        node_id=f"para_{run_source_ids[0]}",
                        role=run_role,
                        text=text,
                        confidence=run_confidence,
                        source_block_ids=list(run_source_ids),
                        bold=all(n.bold for n in run_nodes),
                        italic=all(n.italic for n in run_nodes),
                        page=run_page,
                    )
                )
        result.extend(held)
        run_nodes, run_lines, run_source_ids, run_confidence, run_page = [], [], [], 1.0, None
        held = []

    def geometry_between(node: StructuralNode) -> _Geometry | None:
        if layout is None or not run_source_ids or not node.source_block_ids:
            return None
        prev = blocks_by_id.get(run_source_ids[-1])
        nxt = blocks_by_id.get(node.source_block_ids[0])
        if prev is None or nxt is None:
            return None
        return layout.geometry(prev, nxt)

    for node in nodes:
        if run_lines and node.role in _TRANSPARENT_ROLES:
            held.append(node)
            continue

        starts_run = node.role in _MERGEABLE_ROLES or node.role == BlockRole.LIST_ITEM
        if not starts_run:
            flush()
            result.append(node)
            continue

        node_lines = node.text.split("\n")
        merges, confidence = False, 1.0
        if run_lines and (
            (node.role == run_role and node.role in _MERGEABLE_ROLES)
            or (run_role == BlockRole.LIST_ITEM and node.role == BlockRole.PARAGRAPH)
        ):
            merges, confidence = _continues(
                run_lines[-1], node_lines[0] if node_lines else "", geometry_between(node)
            )
            # An item finished on the next page is lowercase there; a capital
            # after a list is the paragraph that follows it.
            if merges and run_role == BlockRole.LIST_ITEM:
                first = node_lines[0].lstrip() if node_lines else ""
                merges = bool(first) and first[0].islower()

        if merges and run_role == BlockRole.LIST_ITEM:
            # The paragraph finishing this item may also hold the items after it.
            groups: list[list[str]] = [[]]
            item_text = run_lines[0]
            for line in node_lines:
                if _opens_next_item(line, item_text):
                    groups.append([line])
                    item_text = line
                else:
                    groups[-1].append(line)
            if groups[0]:
                run_nodes.append(node)
                run_lines.extend(groups[0])
                run_source_ids.extend(node.source_block_ids)
                run_confidence = min(run_confidence, confidence, node.confidence)
            for number, group in enumerate(groups[1:], start=1):
                flush()
                item = StructuralNode(
                    node_id=f"{node.node_id}_item{number}",
                    role=BlockRole.LIST_ITEM,
                    text="\n".join(group),
                    confidence=node.confidence,
                    source_block_ids=list(node.source_block_ids),
                    page=node.page,
                )
                run_nodes = [item]
                run_lines = list(group)
                run_source_ids = list(item.source_block_ids)
                run_confidence = item.confidence
                run_page = item.page
                run_role = BlockRole.LIST_ITEM
        elif merges:
            run_nodes.append(node)
            run_lines.extend(node_lines)
            run_source_ids.extend(node.source_block_ids)
            run_confidence = min(run_confidence, confidence, node.confidence)
        else:
            flush()
            run_nodes = [node]
            run_lines = list(node_lines)
            run_source_ids = list(node.source_block_ids)
            run_confidence = node.confidence
            run_page = node.page
            run_role = node.role

    flush()
    return result
