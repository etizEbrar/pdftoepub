from __future__ import annotations

import dataclasses
import statistics

from app.models.document import Block, Span
from app.pipeline.structure import TERMINAL_PUNCT

# A blank line's worth of space between two lines of one block. Ordinary
# leading in a block is a fraction of the type size; a paragraph or section
# break is most of a line.
_BREAK_GAP_SIZE_RATIO = 0.8
_BREAK_GAP_LEADING_RATIO = 2.5
# A heading runs to a few lines at most; a longer bold run is emphasis.
_MAX_HEADING_RUN_LINES = 3


@dataclasses.dataclass
class _Line:
    text: str
    spans: list[Span]
    top: float
    bottom: float
    bold: bool
    size: float
    # Nothing but spaces: kept so text and spans stay paired, but it takes no
    # part in deciding where the block breaks.
    blank: bool = False


def _lines_of(block: Block) -> list[_Line] | None:
    """The block's visual lines, or None when spans and text disagree.

    Extraction writes one text line per span run ending in line_break_after,
    so the two always pair up for a native block. When they do not, splitting
    could put words in the wrong half, and the block is left alone.
    """
    text_lines = block.text.split("\n")
    span_lines: list[list[Span]] = []
    current: list[Span] = []
    for span in block.spans:
        current.append(span)
        if span.line_break_after:
            span_lines.append(current)
            current = []
    if current:
        span_lines.append(current)
    if len(text_lines) != len(span_lines):
        return None

    lines: list[_Line] = []
    for text, spans in zip(text_lines, span_lines):
        visible = [s for s in spans if s.text.strip()]
        lines.append(
            _Line(
                text=text,
                spans=list(spans),
                top=min(s.bbox[1] for s in visible or spans),
                bottom=max(s.bbox[3] for s in visible or spans),
                bold=bool(visible) and all(s.bold for s in visible),
                size=max(s.font_size for s in visible or spans),
                blank=not visible,
            )
        )
    return lines


def _bold_run_length(lines: list[_Line], start: int, step: int) -> int:
    length = 0
    index = start
    while 0 <= index < len(lines) and lines[index].bold:
        length += 1
        index += step
    return length


def _cut_points(lines: list[_Line]) -> list[int]:
    """Indices of lines that begin a new block."""
    # Decisions are made between the lines that carry text; a blank line stays
    # with the block above it.
    positions = [i for i, line in enumerate(lines) if not line.blank]
    real = [lines[i] for i in positions]
    if len(real) < 2:
        return []
    gaps = [real[i + 1].top - real[i].bottom for i in range(len(real) - 1)]
    positive = [g for g in gaps if g > 0]
    leading = statistics.median(positive) if len(positive) >= 2 else 0.0
    size = statistics.median(line.size for line in real) or 10.0
    break_gap = max(size * _BREAK_GAP_SIZE_RATIO, leading * _BREAK_GAP_LEADING_RATIO)

    cuts: list[int] = []
    for i, gap in enumerate(gaps):
        above, below = real[i], real[i + 1]
        cut = False
        if gap > break_gap:
            cut = True
        elif above.bold and not below.bold:
            # A bold heading set directly above its first paragraph, which
            # MuPDF keeps in one block when the leading is tight.
            cut = _bold_run_length(real, i, -1) <= _MAX_HEADING_RUN_LINES
        elif below.bold and not above.bold:
            # The same heading at the foot of the paragraph before it. Only
            # once that paragraph has finished its sentence: mid-sentence, the
            # bold line is emphasis that happens to fill a line.
            stripped = above.text.rstrip()
            cut = (
                bool(stripped)
                and stripped[-1] in TERMINAL_PUNCT
                and _bold_run_length(real, i + 1, 1) <= _MAX_HEADING_RUN_LINES
            )
        if cut:
            cuts.append(positions[i] + 1)
    return cuts


def _part(block: Block, lines: list[_Line], index: int) -> Block:
    spans = [s for line in lines for s in line.spans]
    visible = [s for s in spans if s.text.strip()] or spans
    dominant = max(visible, key=lambda s: len(s.text))
    return dataclasses.replace(
        block,
        block_id=block.block_id if index == 0 else f"{block.block_id}s{index}",
        bbox=(
            min(s.bbox[0] for s in visible),
            min(s.bbox[1] for s in visible),
            max(s.bbox[2] for s in visible),
            max(s.bbox[3] for s in visible),
        ),
        text="\n".join(line.text for line in lines),
        spans=spans,
        font=dominant.font,
        font_size=dominant.font_size,
        bold=dominant.bold,
        italic=dominant.italic,
        baseline=spans[-1].baseline,
    )


def split_block(block: Block) -> list[Block]:
    """Split a text block where the page shows a break that MuPDF did not.

    MuPDF groups lines into blocks by proximity, so a section heading set
    tight above its first paragraph, or a caption followed by the next
    section's heading, arrive as one block. Everything downstream decides a
    block's role from the block as a whole, so the heading was read as the
    opening words of a paragraph and the caption as body text.
    """
    if block.kind != "text" or not block.spans:
        return [block]
    lines = _lines_of(block)
    if not lines or len(lines) < 2:
        return [block]
    cuts = _cut_points(lines)
    if not cuts:
        return [block]
    bounds = [0, *cuts, len(lines)]
    return [
        _part(block, lines[start:end], index)
        for index, (start, end) in enumerate(zip(bounds, bounds[1:]))
        if end > start
    ]


def split_blocks(blocks: list[Block]) -> list[Block]:
    result: list[Block] = []
    for block in blocks:
        result.extend(split_block(block))
    return result
