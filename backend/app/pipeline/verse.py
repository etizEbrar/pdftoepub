from __future__ import annotations

import re
import statistics

from app.models.document import Block, BlockRole, StructuralNode
from app.pipeline import headings

# Verse lines stop well short of the text column; prose runs to the margin.
_SHORT_LINE_RATIO = 0.72
_MIN_VERSE_LINES = 3
_MIN_SHORT_LINE_SHARE = 0.75
_RAGGED_RIGHT_MIN_STDEV_RATIO = 0.05
# At least this share of lines must run on into the next without closing.
#
# Prose set narrow — dialogue, aphorisms, a run of short sentences — is short
# and ragged exactly like verse, and those two signals alone were enough to
# convert it. What separates them is that a poem's lines continue, while
# consecutive prose sentences each stop. This was already measured and folded
# into the confidence score, but nothing rejected on it, so ordinary paragraphs
# became <br/>-separated verse.
#
# The cost is deliberate: fully end-stopped verse is left as prose. That keeps
# the author's words intact and merely loses line breaks, where the opposite
# error rewrites prose into something the author never set.
_MIN_ENJAMBMENT_SHARE = 0.25

# Verse lines are phrases. Below this many words per line on average, the run is
# a column of numbers or fragments — an exercise list, a numbered column, a
# stack of labels — not poetry.
_MIN_MEAN_WORDS_PER_LINE = 3.0
# A line ending in a bare number is a contents entry pointing at a page. A run
# mostly made of those is a table of contents.
_MAX_PAGE_REFERENCE_SHARE = 0.3
# A run whose lines mostly open with their own item number is a list.
_MAX_ITEM_NUMBER_SHARE = 0.4

# Verse is written in ordinary language, so its lines carry the small
# lowercase words that sentences are made of. A list of names or titles carries
# almost none: "Prof. Dr. Elif ORHAN" has no such word at all.
_MIN_LOWERCASE_WORD_SHARE = 0.5
# A run that is mostly capitals is a title block or a heading set over several
# lines, not a poem.
_MAX_ALL_CAPS_SHARE = 0.5
# "EF : Emisyon faktörü (kg/kWh)" — a nomenclature table, one symbol per line.
_MAX_DEFINITION_SHARE = 0.5

_PAGE_REFERENCE_RE = re.compile(r"\d{1,4}\s*$")
_LOWERCASE_WORD_RE = re.compile(r"(?:^|\s)[^\W\d_]{2,}(?=\s|$)")
_DEFINITION_RE = re.compile(r"^\s*\S{1,12}\s*[:=]\s+\S")
_ITEM_NUMBER_RE = re.compile(r"^\s*[\(\[]?\d{1,3}[\.\)\]]?\s")
_BARE_NUMBER_LINE_RE = re.compile(r"^\s*[\(\[]?\d{1,4}[\.\)\]]?\s*$")
# Consecutive verse lines sit about one leading apart; a bigger gap is a stanza
# break, and a much bigger gap ends the poem.
_MAX_LINE_GAP_FACTOR = 1.9
_STANZA_GAP_FACTOR = 1.35
_INDENT_STEP_PT = 9.0
_SENTENCE_END = ".!?:;\"'”’»)"

_CANDIDATE_ROLES = {BlockRole.PARAGRAPH, BlockRole.QUOTE}


def _block_lines(block: Block) -> list[tuple[float, float, str]]:
    """Reconstruct per-line (x0, x1, text) from a block's spans."""
    lines: list[tuple[float, float, str]] = []
    x0 = x1 = None
    parts: list[str] = []
    for span in block.spans:
        if x0 is None:
            x0, x1 = span.bbox[0], span.bbox[2]
        else:
            x0, x1 = min(x0, span.bbox[0]), max(x1, span.bbox[2])
        parts.append(span.text)
        if span.line_break_after:
            lines.append((x0, x1, "".join(parts).strip()))
            x0 = x1 = None
            parts = []
    if parts and x0 is not None:
        lines.append((x0, x1, "".join(parts).strip()))
    if not lines and block.text.strip():
        lines = [(block.bbox[0], block.bbox[2], block.text.strip())]
    return [line for line in lines if line[2]]


def _column_text_width(blocks: list[Block]) -> float:
    """The width of a full prose *line* in this column — the yardstick a verse
    line must fall short of.

    Measured over individual lines rather than block bounding boxes: a two-line
    prose block's bbox is the union of a long line and a short one, which would
    make both look short and turn ordinary wrapped prose into "verse".
    """
    widest = 0.0
    for block in blocks:
        if block.kind != "text" or not block.text.strip():
            continue
        for x0, x1, _ in _block_lines(block):
            widest = max(widest, x1 - x0)
    return widest


def _looks_like_verse_run(
    lines: list[tuple[float, float, str]], reference_width: float
) -> tuple[bool, float]:
    """Judge a candidate run of lines. Requires several independent signals so
    ordinary prose is never converted into poetry."""
    if len(lines) < _MIN_VERSE_LINES or reference_width <= 0:
        return False, 0.0

    widths = [x1 - x0 for x0, x1, _ in lines]
    short_share = sum(1 for w in widths if w < reference_width * _SHORT_LINE_RATIO) / len(widths)
    if short_share < _MIN_SHORT_LINE_SHARE:
        return False, 0.0

    right_edges = [x1 for _, x1, _ in lines]
    stdev_ratio = statistics.pstdev(right_edges) / reference_width if reference_width else 0.0
    if stdev_ratio < _RAGGED_RIGHT_MIN_STDEV_RATIO:
        return False, 0.0  # a straight right edge means it's a justified block

    # Some enjambment: a run where every line closes a sentence is prose.
    enjambed = sum(1 for _, _, text in lines[:-1] if text and text[-1] not in _SENTENCE_END)
    enjambment_share = enjambed / max(1, len(lines) - 1)
    if enjambment_share < _MIN_ENJAMBMENT_SHARE:
        return False, 0.0

    # Everything below rejects material that is short and ragged for reasons
    # that have nothing to do with poetry. Each was found in a real book: a
    # grammar reference produced a thousand "poems" made of contents entries,
    # exercise numbers and cover matter. The bias is deliberately towards prose
    # — leaving a poem as paragraphs keeps every word, while re-setting a list
    # as verse invents line breaks the author never wrote.
    texts = [text for _, _, text in lines]

    if any(_BARE_NUMBER_LINE_RE.match(t) for t in texts):
        return False, 0.0

    mean_words = sum(len(t.split()) for t in texts) / len(texts)
    if mean_words < _MIN_MEAN_WORDS_PER_LINE:
        return False, 0.0

    page_refs = sum(1 for t in texts if _PAGE_REFERENCE_RE.search(t))
    if page_refs / len(texts) > _MAX_PAGE_REFERENCE_SHARE:
        return False, 0.0

    item_numbers = sum(1 for t in texts if _ITEM_NUMBER_RE.match(t))
    if item_numbers / len(texts) > _MAX_ITEM_NUMBER_SHARE:
        return False, 0.0

    # A run that opens by naming a division is a chapter heading set over
    # several lines. Turning it into verse loses the chapter.
    if any(headings.is_division_label(t) for t in texts):
        return False, 0.0

    all_caps = sum(1 for t in texts if t.strip() and t.upper() == t and any(c.isalpha() for c in t))
    if all_caps / len(texts) > _MAX_ALL_CAPS_SHARE:
        return False, 0.0

    definitions = sum(1 for t in texts if _DEFINITION_RE.match(t))
    if definitions / len(texts) > _MAX_DEFINITION_SHARE:
        return False, 0.0

    # Lines made only of capitalised words are names and titles, not verse.
    with_lowercase = sum(
        1
        for t in texts
        if any(w.islower() for w in _LOWERCASE_WORD_RE.findall(t))
    )
    if with_lowercase / len(texts) < _MIN_LOWERCASE_WORD_SHARE:
        return False, 0.0

    confidence = (
        0.35
        + 0.25 * short_share
        + 0.2 * min(stdev_ratio / 0.2, 1.0)
        + 0.2 * enjambment_share
    )
    return True, min(confidence, 0.95)


def _gap_between(previous: Block, current: Block) -> float:
    return current.bbox[1] - previous.bbox[3]


def _is_candidate(node: StructuralNode, blocks_by_id: dict[str, Block]) -> Block | None:
    if node.role not in _CANDIDATE_ROLES or len(node.source_block_ids) != 1:
        return None
    return blocks_by_id.get(node.source_block_ids[0])


def detect_verse(nodes: list[StructuralNode], blocks_by_id: dict[str, Block]) -> int:
    """Find poetry and collapse each run of verse lines into a single VERSE node.

    Real poetry is typeset as a run of *separate* short blocks — one per line —
    not as one block containing wrapped lines, so this works across consecutive
    nodes rather than inside a single block. Must run before paragraph merging,
    whose "no terminal punctuation means continuation" rule would otherwise fuse
    a poem into one prose paragraph.
    """
    if not nodes:
        return 0

    # Reference width is per page *and column*: in a two-column paper every line
    # is short relative to the page, so a page-wide yardstick would call the
    # whole paper verse.
    blocks_by_column: dict[tuple[int, int], list[Block]] = {}
    for block in blocks_by_id.values():
        blocks_by_column.setdefault((block.page, block.column), []).append(block)
    reference_width = {
        key: _column_text_width(column_blocks)
        for key, column_blocks in blocks_by_column.items()
    }

    result: list[StructuralNode] = []
    converted = 0
    index = 0

    while index < len(nodes):
        node = nodes[index]
        block = _is_candidate(node, blocks_by_id)
        if block is None:
            result.append(node)
            index += 1
            continue

        # Grow a run of vertically adjacent, similarly-sized candidate blocks.
        # Poetry is typeset one line per block, so only single-line blocks may
        # join a run: that keeps a following prose paragraph — whose taller,
        # multi-line box would otherwise satisfy a height-based gap test — from
        # being absorbed and dragging the whole run out of verse.
        run_nodes = [node]
        run_blocks = [block]
        cursor = index + 1
        if len(_block_lines(block)) == 1:
            while cursor < len(nodes):
                next_node = nodes[cursor]
                next_block = _is_candidate(next_node, blocks_by_id)
                if next_block is None or next_block.page != block.page:
                    break
                if next_block.column != run_blocks[-1].column:
                    break
                if len(_block_lines(next_block)) != 1:
                    break
                # Gauge the gap against the text size, not the box height.
                leading = next_block.font_size or (next_block.bbox[3] - next_block.bbox[1])
                if leading <= 0:
                    break
                if _gap_between(run_blocks[-1], next_block) > leading * _MAX_LINE_GAP_FACTOR:
                    break
                size_a = run_blocks[-1].font_size or 0
                size_b = next_block.font_size or 0
                if size_a and size_b and abs(size_a - size_b) > 1.0:
                    break
                run_nodes.append(next_node)
                run_blocks.append(next_block)
                cursor += 1

        lines: list[tuple[float, float, str]] = []
        for run_block in run_blocks:
            lines.extend(_block_lines(run_block))

        is_verse, confidence = _looks_like_verse_run(
            lines, reference_width.get((block.page, block.column), 0.0)
        )
        if not is_verse:
            result.append(node)
            index += 1
            continue

        # Stanza breaks: a gap noticeably larger than the run's typical leading.
        gaps = [
            _gap_between(a, b) for a, b in zip(run_blocks, run_blocks[1:])
        ]
        typical_gap = statistics.median(gaps) if gaps else 0.0

        base_x = min(x0 for x0, _, _ in lines)
        verse_lines: list[str] = []
        indents: list[int] = []
        line_cursor = 0
        for block_index, run_block in enumerate(run_blocks):
            if block_index > 0 and typical_gap > 0:
                if gaps[block_index - 1] > typical_gap * _STANZA_GAP_FACTOR:
                    verse_lines.append("")  # blank line marks the stanza boundary
                    indents.append(0)
            for x0, _x1, text in _block_lines(run_block):
                verse_lines.append(text)
                indents.append(max(0, int(round((x0 - base_x) / _INDENT_STEP_PT))))
                line_cursor += 1

        merged = StructuralNode(
            node_id=f"verse_{run_nodes[0].node_id}",
            role=BlockRole.VERSE,
            text="\n".join(l for l in verse_lines if l),
            confidence=confidence,
            source_block_ids=[b.block_id for b in run_blocks],
            page=block.page,
            verse_lines=verse_lines,
            verse_indents=indents,
        )
        result.append(merged)
        converted += 1
        index = cursor

    nodes[:] = result
    return converted
