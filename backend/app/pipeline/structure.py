from __future__ import annotations

import re
import statistics

from app.models.document import Block, BlockRole, StructuralNode
from app.pipeline import headings as headings_module
from app.pipeline import toc as toc_module
from app.pipeline.footnotes import strip_all_sentinels

BULLET_RE = re.compile(r"^[•●○◦▪‣–\-\*]\s+")
NUMBERED_RE = re.compile(r"^(\d{1,3}|[a-zA-Z]|[ivxlcdmIVXLCDM]{1,6})[.)]\s+")
# A note body opens with its marker; unlike NUMBERED_RE the separator is
# optional, since footnotes are commonly set as "1 Text" with no punctuation.
# An extract is usually set a point or two down from the body; more than this
# and it is note-sized rather than quote-sized.
_QUOTE_MAX_SIZE_RATIO = 0.96
# Multi-line blocks a page needs before its own left margin is trusted.
_MIN_PAGE_MARGIN_BLOCKS = 2
_MIN_LINE_BLOCKS_FOR_MARGIN = 6
# "Tablo 6: ...", "Şekil 8: ...", "Figure 2. ..." — a label naming the figure or
# table it belongs to. Captions are set smaller and often indented, which is
# exactly the shape of a block quote, so without this they were reconstructed as
# quotations of the book by itself.
_CAPTION_RE = re.compile(
    r"^\s*(?:tablo|şekil|sekil|resim|grafik|çizelge|cizelge|figure|fig\.|table|chart|plate)"
    r"\s*\d{1,3}\s*[:.\-–—]",
    re.IGNORECASE,
)


def looks_like_caption(text: str) -> bool:
    """True for a line that names the figure or table it accompanies."""
    return bool(_CAPTION_RE.match(" ".join(text.split())))
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
    # The first line that says anything: a block can open with a blank line
    # MuPDF kept above a caption, which hid "Şekil 7:" from every test.
    for line in text.split("\n"):
        if line.strip():
            return line.strip()
    return ""


# A note set at 0.75x body or smaller is unambiguously note-sized. Between that
# and 0.85x, type is often just a slightly tighter setting of ordinary prose, so
# an opening marker is required as corroboration. Without this second gate,
# paragraph continuations low on the page were being rendered as footnotes.
_FOOTNOTE_CLEAR_SIZE_RATIO = 0.75
_FOOTNOTE_MAX_SIZE_RATIO = 0.90
_FOOTNOTE_PAGE_FRACTION = 0.66


def _first_line_of_paragraph(
    ordered: list[Block], index: int, margin_of, body_size: float
) -> bool:
    """A lone indented line with the next line back at the margin.

    That is a paragraph's indented first line, not an extract: a quotation is
    set in on every line. A scanner's text layer makes each printed line a
    block of its own, so the first line of a paragraph arrives alone, indented
    -- and with type a fraction of a point smaller, a whole paragraph was cut
    in two and its first line set as a quotation.
    """
    block = ordered[index]
    if "\n" in block.text.strip():
        return False
    following = next(
        (b for b in ordered[index + 1 :] if b.kind == "text" and b.text.strip()), None
    )
    if following is None or following.page != block.page or following.column != block.column:
        return False
    margin = margin_of(following)
    return following.bbox[0] <= margin + max(body_size * 0.5, 3.0)


def _is_smaller_than_body(block, body_size: float) -> bool:
    """Set noticeably smaller than the body text.

    The margin matters: extraction jitters font sizes by a fraction of a point,
    and treating that as a deliberate size change would turn ordinary indented
    paragraphs into block quotes. Text a machine read from a scan has no type
    size to compare, only the height of the ink each word covers.
    """
    if not body_size or not block.font_size or getattr(block, "machine_read", False):
        return False
    return block.font_size <= body_size * _QUOTE_MAX_SIZE_RATIO


_SMALL_MARKER_RE = re.compile(r"^(?:\d{1,3}|[*†‡§¶#]{1,3})$")
# A marker set at this share of the text's size or less is a superscript,
# whether or not the PDF flags it as one.
_SMALL_MARKER_SIZE_RATIO = 0.8


def _span_lines(block: Block) -> list[list]:
    lines: list[list] = []
    current: list = []
    for span in block.spans:
        current.append(span)
        if span.line_break_after:
            lines.append(current)
            current = []
    if current:
        lines.append(current)
    return lines


def _glued_marker(spans: list) -> bool:
    """A line opening with a small number set hard against its first word."""
    visible = [s for s in spans if s.text.strip()]
    if len(visible) < 2 or not _SMALL_MARKER_RE.match(visible[0].text.strip()):
        return False
    first, second = visible[0], visible[1]
    small = first.is_superscript or (
        second.font_size and first.font_size <= second.font_size * _SMALL_MARKER_SIZE_RATIO
    )
    return bool(small)


def _opens_with_small_marker(block: Block) -> bool:
    lines = [ln for ln in _span_lines(block) if any(s.text.strip() for s in ln)]
    return bool(lines) and _glued_marker(lines[0])


def _note_text(block: Block, text: str) -> str:
    """A note body's text, with a space after each marker set hard against it.

    "¹Kırklareli Üniversitesi" is the note numbered 1, but read as text it is
    the word "1Kırklareli", and neither the note nor its reference could be
    matched.
    """
    lines = _span_lines(block)
    if not any(_glued_marker(line) for line in lines):
        return text
    rebuilt: list[str] = []
    for line in lines:
        visible = [s for s in line if s.text.strip()]
        if _glued_marker(line):
            rest = "".join(s.text for s in line[line.index(visible[1]) :])
            rebuilt.append(f"{visible[0].text.strip()} {rest.lstrip()}")
        else:
            rebuilt.append("".join(s.text for s in line))
    return "\n".join(rebuilt).strip()


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
    return bool(NOTE_ENTRY_RE.match(strip_all_sentinels(block.text).strip())) or (
        _opens_with_small_marker(block)
    )


def _split_at_item_starts(lines: list[str], plain_lines: list[str], starts) -> list[str] | None:
    """Group a block's lines into items, each opening on a line `starts` accepts.

    Returns None unless the block holds more than one item. Lines that do not
    open an item are the wrapped continuation of the one above, so an item
    that runs to two lines is still one item. Requiring every line to carry
    its own marker left a list whose entries wrap as one long item, its
    markers buried in the middle of the text.
    """
    if not lines or not starts(plain_lines[0], 0):
        return None
    items: list[list[str]] = []
    for index, (line, plain) in enumerate(zip(lines, plain_lines)):
        if items and not starts(plain, len(items)):
            items[-1].append(line)
        else:
            items.append([line])
    if len(items) < 2:
        return None
    return ["\n".join(item) for item in items]


def _note_number(text: str) -> int | None:
    match = NOTE_ENTRY_RE.match(text)
    if not match or not match.group(1).isdigit():
        return None
    return int(match.group(1))


def _split_notes(lines: list[str], plain_lines: list[str]) -> list[str] | None:
    """Separate notes stacked in one block, each opening with its number.

    A note's own text can wrap onto a line beginning with a number ("2019
    yılında"), so a line opens a new note only when it carries the next number
    in sequence after the note above it.
    """
    first = _note_number(plain_lines[0]) if plain_lines else None
    if first is None:
        if all(NOTE_ENTRY_RE.match(ln) for ln in plain_lines) and len(plain_lines) > 1:
            return list(lines)
        return None
    return _split_at_item_starts(
        lines, plain_lines, lambda text, count: _note_number(text) == first + count
    )


def _is_list_marker_line(text: str) -> bool:
    return bool(BULLET_RE.match(text) or NUMBERED_RE.match(text))


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
    # Pages carrying text at the body's own size. Note-sized type is enough to
    # be annotated; a quotation needs real body text to be set apart from.
    pages_with_body_size_text = {
        b.page
        for b in text_blocks
        if b.font_size and body_size and b.font_size >= body_size * _QUOTE_MAX_SIZE_RATIO
    }
    line_gap = _typical_line_gap(text_blocks)
    # Page-level context for the heading scorer: a chapter opener typically
    # sits alone on a page that carries far less text than the book's norm.
    page_char_counts: dict[int, int] = {}
    first_content_block: dict[int, str] = {}
    for b in text_blocks:
        page_char_counts[b.page] = page_char_counts.get(b.page, 0) + len(b.text.strip())
        first_content_block.setdefault(b.page, b.block_id)
    # Where the column's paragraphs start: the left edge of its multi-line
    # blocks, whose wrapped lines run from the margin. The smallest x on the
    # page is not the margin -- one diagram label set out in the gutter put it
    # there, and every paragraph in the book then counted as indented.
    edges: dict[int, list[float]] = {}
    for b in text_blocks:
        if b.text.count("\n") >= 2:
            edges.setdefault(b.column, []).append(b.bbox[0])
    left_margins: dict[int, float] = {}
    for b in text_blocks:
        key = b.column
        left_margins[key] = min(left_margins.get(key, b.bbox[0]), b.bbox[0])
    for key, values in edges.items():
        left_margins[key] = statistics.median(values)
    # And per page where the page says: a scan sits further left or right on
    # every leaf, and against the book's median margin every block of a
    # right-hand page counted as indented -- and, in slightly smaller type,
    # as a quotation that cut its paragraph in two.
    page_edges: dict[tuple[int, int], list[float]] = {}
    for b in text_blocks:
        if b.text.count("\n") >= 2:
            page_edges.setdefault((b.page, b.column), []).append(b.bbox[0])
    page_margins = {
        key: statistics.median(values)
        for key, values in page_edges.items()
        if len(values) >= _MIN_PAGE_MARGIN_BLOCKS
    }
    # A text layer that makes each printed line a block has no wrapped blocks
    # to measure; there the margin is where most of the page's lines start,
    # the indented first lines of paragraphs being the few that do not.
    page_starts: dict[tuple[int, int], list[float]] = {}
    for b in text_blocks:
        page_starts.setdefault((b.page, b.column), []).append(b.bbox[0])
    for key, starts in page_starts.items():
        if key not in page_margins and len(starts) >= _MIN_LINE_BLOCKS_FOR_MARGIN:
            page_margins[key] = sorted(starts)[len(starts) // 4]

    def margin_of(block: Block) -> float:
        return page_margins.get((block.page, block.column), left_margins.get(block.column, block.bbox[0]))

    toc_pages = toc_module.detect_toc_pages(text_blocks)

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
        # Inline emphasis is carried as invisible characters by this point; a
        # caption whose label is bold ("Şekil 1.") opened with one and every
        # pattern below, anchored at the start, missed it.
        plain = strip_all_sentinels(text).strip()
        first_line = _first_line(plain)
        gap_above = _gap_above(ordered_blocks, i)
        gap_below = _gap_below(ordered_blocks, i)
        indented = b.bbox[0] > margin_of(b) + max(body_size * 1.2, 8)

        role = BlockRole.PARAGRAPH
        level = None
        confidence = 0.85
        evidence: list[str] = []

        if b.page in toc_pages:
            # The contents page's own title is a heading; everything else on
            # the page is an entry, whatever its type says.
            is_title = toc_module.is_toc_title(plain)
            nodes.append(
                StructuralNode(
                    node_id=f"n_{b.block_id}",
                    role=BlockRole.HEADING if is_title else BlockRole.TOC_ENTRY,
                    text=plain if is_title else toc_module.entry_text(plain),
                    level=_heading_level(size_ratio) if is_title else None,
                    confidence=0.8,
                    source_block_ids=[b.block_id],
                    bold=b.bold,
                    italic=b.italic,
                    page=b.page,
                    heading_scale=size_ratio if is_title else None,
                    evidence=["printed-contents"],
                )
            )
            continue

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
        elif _looks_like_footnote_body(b, body_size, b.page in pages_with_body_text):
            # Checked before the bullet rule: a note opening "* " or "- " also
            # matches BULLET_RE, and losing that contest turned footnotes into
            # list items with their markers eaten as bullets.
            #
            # Several notes stacked in the footnote area are usually merged into
            # one block. When every line opens with its own marker they are
            # distinct notes, and must be split or they'd all link to whichever
            # marker happened to come first.
            text = _note_text(b, text)
            raw_lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
            notes = _split_notes(raw_lines, [strip_all_sentinels(ln) for ln in raw_lines])
            if notes:
                for li, note in enumerate(notes):
                    nodes.append(
                        StructuralNode(
                            node_id=f"n_{b.block_id}_{li}",
                            role=BlockRole.FOOTNOTE,
                            text=note,
                            confidence=0.7,
                            source_block_ids=[b.block_id],
                            page=b.page,
                        )
                    )
                continue
            role = BlockRole.FOOTNOTE
            confidence = 0.6  # refined by footnotes.py, which owns final footnote linking
        elif BULLET_RE.match(first_line) or NUMBERED_RE.match(first_line):
            # PyMuPDF sometimes groups several adjacent bulleted/numbered lines
            # into one block when the vertical gap between them is small. If
            # every line in the block starts its own marker, these are
            # separate list items, not one item with wrapped continuation
            # lines — split them out now rather than merging them later.
            raw_lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
            items = _split_at_item_starts(
                raw_lines,
                [strip_all_sentinels(ln) for ln in raw_lines],
                lambda line, _count: _is_list_marker_line(line),
            )
            if items:
                for li, item in enumerate(items):
                    nodes.append(
                        StructuralNode(
                            node_id=f"n_{b.block_id}_{li}",
                            role=BlockRole.LIST_ITEM,
                            text=item,
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
        elif looks_like_caption(first_line):
            role = BlockRole.CAPTION
            confidence = 0.8
        elif (
            indented
            and (b.italic or _is_smaller_than_body(b, body_size))
            and b.page in pages_with_body_size_text
            and not _first_line_of_paragraph(ordered_blocks, i, margin_of, body_size)
        ):
            # Italics are one way to mark an extract; a smaller measure set
            # in from the margin is just as common and was being flattened
            # into ordinary prose. The footnote test above already claimed
            # small type at the foot of the page, so this cannot steal notes.
            # An extract is set apart from the text around it: a copyright
            # page, all small type and centred, has none, and every line of it
            # had become a quotation.
            role = BlockRole.QUOTE
            confidence = 0.7 if b.italic else 0.6

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

    blocks_by_id = {b.block_id: b for b in ordered_blocks}
    return _merge_entry_continuations(_merge_caption_continuations(nodes, blocks_by_id))


def _merge_entry_continuations(nodes: list[StructuralNode]) -> list[StructuralNode]:
    """Join a contents entry to the line that finishes it.

    A long entry wraps, and each line of a contents page is read as an entry
    of its own: a list of illustrations showed "A vessel larger than our
    little fishing sloop" and, as the next entry, "could not have threaded
    its way among the". The second line of an entry starts in lowercase.
    """
    result: list[StructuralNode] = []
    for node in nodes:
        previous = result[-1] if result else None
        text = strip_all_sentinels(node.text).lstrip()
        if (
            previous is not None
            and node.role == BlockRole.TOC_ENTRY
            and previous.role == BlockRole.TOC_ENTRY
            and node.page == previous.page
            and text[:1].islower()
        ):
            previous.text = f"{previous.text.rstrip()} {node.text.strip()}"
            previous.source_block_ids.extend(node.source_block_ids)
            continue
        result.append(node)
    return result


# A caption's second line sits directly beneath its first.
_CAPTION_LINE_GAP_RATIO = 0.8
_CAPTION_SIZE_TOLERANCE = 0.6
_CAPTION_CENTRE_TOLERANCE = 0.1  # fraction of page width
_MAX_CAPTION_CONTINUATION_LINES = 2


def _merge_caption_continuations(
    nodes: list[StructuralNode], blocks_by_id: dict[str, Block]
) -> list[StructuralNode]:
    """Join a caption to the line that finishes it.

    A two-line caption is often set as two blocks, centred one above the
    other. The second line, short and centred, then read as a quotation of
    its own beneath the figure: "Şekil 1: 2018 Yılına kadar ..." followed by
    a block quote reading "enerji kaynakları (Komusanac vd., 2019)".
    """
    result: list[StructuralNode] = []
    for node in nodes:
        previous = result[-1] if result else None
        if (
            previous is not None
            and previous.role == BlockRole.CAPTION
            and node.role in (BlockRole.PARAGRAPH, BlockRole.QUOTE)
            and node.page == previous.page
            and _continues_caption(previous, node, blocks_by_id)
        ):
            previous.text = f"{previous.text}\n{node.text}"
            previous.source_block_ids.extend(node.source_block_ids)
            continue
        result.append(node)
    return result


def _continues_caption(
    caption: StructuralNode, node: StructuralNode, blocks_by_id: dict[str, Block]
) -> bool:
    above = blocks_by_id.get(caption.source_block_ids[-1])
    below = blocks_by_id.get(node.source_block_ids[0])
    if above is None or below is None or not above.font_size or not below.font_size:
        return False
    if looks_like_caption(_first_line(strip_all_sentinels(node.text))):
        return False
    if len([ln for ln in node.text.split("\n") if ln.strip()]) > _MAX_CAPTION_CONTINUATION_LINES:
        return False
    if abs(above.font_size - below.font_size) > _CAPTION_SIZE_TOLERANCE:
        return False
    gap = below.bbox[1] - above.bbox[3]
    if gap > max(above.font_size * _CAPTION_LINE_GAP_RATIO, 4.0):
        return False
    # A caption's last line is no wider than its first. The paragraph after a
    # figure is set to the full measure, and centred on the page just as a
    # caption is: one article's text after "Şekil 5" became part of its caption.
    if (below.bbox[2] - below.bbox[0]) > (above.bbox[2] - above.bbox[0]) + below.font_size * 2:
        return False
    above_centre = (above.bbox[0] + above.bbox[2]) / 2
    below_centre = (below.bbox[0] + below.bbox[2]) / 2
    return abs(above_centre - below_centre) <= below.page_width * _CAPTION_CENTRE_TOLERANCE
