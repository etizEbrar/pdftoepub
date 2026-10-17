from __future__ import annotations

import re
from dataclasses import dataclass

from app.models.document import Block, BlockRole, StructuralNode
from app.pipeline.footnotes import strip_all_sentinels
from app.pipeline.hyphenation import HyphenEvidence, join_lines_with_hyphenation_repair

_BIBLIOGRAPHY_TITLE_RE = re.compile(
    r"^\s*(?:\d{1,3}(?:\.\d{1,3})*\.?\s*)?"
    r"(?:kaynak[çc]a|kaynaklar|yararlan[ıi]lan kaynaklar|bibliyografya|referanslar"
    r"|references|bibliography|works cited|literature cited|sources"
    r"|literatur|literaturverzeichnis|bibliographie|références|referencias|bibliografía"
    r"|bibliografia|riferimenti bibliografici|المراجع|المصادر)\s*:?\s*$",
    re.IGNORECASE,
)
# "[12] ...", "12. ...", "(12) ..." — a numbered reference list.
_NUMBERED_ENTRY_RE = re.compile(r"^\s*(?:\[\d{1,3}\]|\(\d{1,3}\)|\d{1,3}[.)])\s+\S")
_CONSUMED_ROLES = (BlockRole.PARAGRAPH, BlockRole.QUOTE, BlockRole.LIST_ITEM, BlockRole.VERSE)
_SECTION_ENDS = (
    BlockRole.HEADING,
    BlockRole.ENDNOTE_SECTION_HEADING,
    BlockRole.THEMATIC_BREAK,
    BlockRole.TOC_ENTRY,
)
# A link too long to fit after the text it belongs to is set on a line of its
# own, sometimes back at the margin; it never opens a reference.
_LINK_LINE_RE = re.compile(r"^\s*(?:https?://|www\.|doi\s*:|dx\.doi)", re.IGNORECASE)
# A continuation line is set in by at least this many type sizes.
_HANGING_INDENT_SIZE_RATIO = 0.6
# Share of a list's lines that must be set in before it is read as hanging.
_MIN_HANGING_SHARE = 0.1


def is_bibliography_title(text: str) -> bool:
    return bool(_BIBLIOGRAPHY_TITLE_RE.match(" ".join(strip_all_sentinels(text).split())))


@dataclass
class _Line:
    text: str
    x0: float | None
    size: float
    page: int
    column: int
    block_id: str


def _block_lines(block: Block) -> list[_Line]:
    text_lines = block.text.split("\n")
    span_lines: list[list] = []
    current: list = []
    for span in block.spans:
        current.append(span)
        if span.line_break_after:
            span_lines.append(current)
            current = []
    if current:
        span_lines.append(current)
    size = block.font_size or 10.0
    if len(span_lines) != len(text_lines):
        # Without line geometry the block is one entry, as it was before.
        return [_Line(" ".join(text_lines), None, size, block.page, block.column, block.block_id)]
    lines: list[_Line] = []
    for text, spans in zip(text_lines, span_lines):
        visible = [s for s in spans if s.text.strip()]
        if not visible:
            continue
        lines.append(
            _Line(
                text=text,
                x0=min(s.bbox[0] for s in visible),
                size=size,
                page=block.page,
                column=block.column,
                block_id=block.block_id,
            )
        )
    return lines


def _entries(lines: list[_Line]) -> list[list[_Line]]:
    """Group a reference list's lines into its entries.

    Reference lists are set with a hanging indent: an entry opens at the
    margin and its later lines are set in. That is the only thing on the page
    separating one entry from the next -- the blocks MuPDF draws around them
    hold several entries each, or half of one.
    """
    margins: dict[tuple[int, int], float] = {}
    for line in lines:
        if line.x0 is None:
            continue
        key = (line.page, line.column)
        margins[key] = min(margins.get(key, line.x0), line.x0)

    def indented(line: _Line) -> bool:
        margin = margins.get((line.page, line.column))
        if line.x0 is None or margin is None:
            return False
        return line.x0 > margin + max(line.size * _HANGING_INDENT_SIZE_RATIO, 4.0)

    measured = [ln for ln in lines if ln.x0 is not None]
    hanging = bool(measured) and (
        sum(1 for ln in measured if indented(ln)) / len(measured) >= _MIN_HANGING_SHARE
    )
    numbered = sum(1 for ln in lines if _NUMBERED_ENTRY_RE.match(strip_all_sentinels(ln.text)))

    entries: list[list[_Line]] = []
    previous_block: str | None = None
    for line in lines:
        plain = strip_all_sentinels(line.text)
        if numbered >= 3:
            opens = bool(_NUMBERED_ENTRY_RE.match(plain))
        elif hanging:
            opens = not indented(line)
        else:
            # Neither numbered nor hanging: the blocks are the entries.
            opens = line.block_id != previous_block
        previous_block = line.block_id
        if opens and _LINK_LINE_RE.match(plain):
            opens = False
        if opens or not entries:
            entries.append([line])
        else:
            entries[-1].append(line)
    return entries


def segment_bibliographies(
    nodes: list[StructuralNode],
    blocks_by_id: dict[str, Block],
    evidence: HyphenEvidence | None = None,
) -> int:
    """Rebuild each reference list as one entry per reference.

    Read as prose, a bibliography was merged wherever an entry ended without a
    full stop, split wherever MuPDF ended a block, and its indented lines were
    taken for block quotes and list items. Returns the number of entries.
    """
    result: list[StructuralNode] = []
    total = 0
    index = 0
    while index < len(nodes):
        node = nodes[index]
        result.append(node)
        index += 1
        if node.role != BlockRole.HEADING or not is_bibliography_title(node.text):
            continue

        section: list[StructuralNode] = []
        passthrough: list[StructuralNode] = []
        while index < len(nodes) and nodes[index].role not in _SECTION_ENDS:
            if nodes[index].role in _CONSUMED_ROLES:
                section.append(nodes[index])
            else:
                passthrough.append(nodes[index])
            index += 1
        if not section:
            result.extend(passthrough)
            continue

        block_ids: list[str] = []
        for member in section:
            for block_id in member.source_block_ids:
                if block_id not in block_ids:
                    block_ids.append(block_id)
        lines = [
            line
            for block_id in block_ids
            if block_id in blocks_by_id
            for line in _block_lines(blocks_by_id[block_id])
        ]
        if not lines:
            result.extend(section + passthrough)
            continue

        for entry in _entries(lines):
            ids = list(dict.fromkeys(line.block_id for line in entry))
            text = join_lines_with_hyphenation_repair([ln.text for ln in entry], evidence)
            if not text.strip():
                continue
            result.append(
                StructuralNode(
                    node_id=f"bib_{ids[0]}_{total}",
                    role=BlockRole.BIBLIOGRAPHY_ENTRY,
                    text=text.strip(),
                    confidence=0.85,
                    source_block_ids=ids,
                    page=entry[0].page,
                    evidence=["hanging-indent-entry"],
                )
            )
            total += 1
        # Running heads and the like stay in the stream, after the list.
        result.extend(passthrough)

    nodes[:] = result
    return total
