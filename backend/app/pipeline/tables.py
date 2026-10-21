from __future__ import annotations

import re
from dataclasses import dataclass

import fitz

from app.core.logging import get_logger
from app.models.document import Block, TableCell, TableData
from app.pipeline.footnotes import strip_all_sentinels
from app.pipeline.hyphenation import HyphenEvidence, join_lines_with_hyphenation_repair

logger = get_logger(__name__)

_CAPTION_RE = re.compile(
    r"^\s*(table|tablo|tabelle|tableau|çizelge|cizelge)\s*[\d.]+", re.IGNORECASE
)
_CAPTION_SEARCH_GAP_PT = 60.0


@dataclass
class DetectedTable:
    page: int
    bbox: tuple[float, float, float, float]
    data: TableData
    covered_block_ids: list[str]


def _cell_text(cell_value: str | None, evidence: HyphenEvidence | None = None) -> str:
    """Flatten a cell's wrapped lines, repairing the hyphenation at each join.

    A naive whitespace join turned "co-\ninvocation" into "co- invocation": a
    hyphen followed by a space, which is wrong however the break is read. Cells
    wrap exactly like prose, so they need the same repair prose gets.
    """
    if not cell_value:
        return ""
    return " ".join(
        join_lines_with_hyphenation_repair(str(cell_value).split("\n"), evidence).split()
    )


def _looks_like_header(row: list[str], body_rows: list[list[str]]) -> bool:
    """A first row is a header when it is fully populated and, unlike the body
    rows beneath it, contains no numeric-only cells."""
    if not row or not all(c.strip() for c in row):
        return False
    if not body_rows:
        return False

    def numeric_fraction(cells: list[str]) -> float:
        filled = [c for c in cells if c.strip()]
        if not filled:
            return 0.0
        numeric = sum(1 for c in filled if re.fullmatch(r"[-+()%.,\d\s]+", c))
        return numeric / len(filled)

    header_numeric = numeric_fraction(row)
    body_numeric = max(numeric_fraction(r) for r in body_rows)
    return header_numeric < 0.34 and body_numeric > header_numeric


def _drop_empty_columns(rows: list[list[str]]) -> list[list[str]]:
    """Remove columns with nothing in any row.

    A grid drawn with doubled rules, or a cell border a hair off the column
    line, is read as an extra column of nothing: tables came out with a blank
    column beside every real one.
    """
    width = max((len(r) for r in rows), default=0)
    keep = [c for c in range(width) if any(c < len(r) and r[c].strip() for r in rows)]
    return [[r[c] if c < len(r) else "" for c in keep] for r in rows]


def _caption_row(rows: list[list[str]]) -> str | None:
    """A first row holding nothing but the table's own "Tablo 1: ..." label."""
    if not rows:
        return None
    filled = [c for c in rows[0] if c.strip()]
    if len(filled) == 1 and _CAPTION_RE.match(filled[0]):
        return " ".join(filled[0].split())
    return None


def _score_table(rows: list[list[str]]) -> float:
    """Confidence that this really is a table we can render faithfully.

    Penalizes the shapes that produce wrong tables: too few rows/columns to be
    distinguishable from ordinary layout, ragged rows, and mostly-empty grids.
    """
    if len(rows) < 2 or not rows[0]:
        return 0.0
    col_count = len(rows[0])
    if col_count < 2:
        return 0.0

    # What makes a grid a grid is that its rows reach across the columns.
    # Display text centred over several lines lands one line per row and leaves
    # the other column empty, which otherwise scores as a clean, consistent
    # table: a real book's chapter openings were being replaced by 3x2 tables
    # and dropping out of the navigation. Ordinary tables keep most rows
    # spanning, so a single gap in a row costs nothing.
    spanning = sum(1 for r in rows if sum(1 for c in r if c.strip()) >= 2)
    if spanning * 2 < len(rows):
        return 0.0

    consistent = sum(1 for r in rows if len(r) == col_count) / len(rows)
    total_cells = sum(len(r) for r in rows)
    filled = sum(1 for r in rows for c in r if c.strip())
    fill_ratio = filled / total_cells if total_cells else 0.0

    score = 0.55 * consistent + 0.45 * fill_ratio
    if len(rows) >= 3 and col_count >= 2:
        score += 0.08  # more rows is stronger evidence of a real grid
    if fill_ratio < 0.45:
        score -= 0.25  # a mostly-empty grid is usually mis-detected layout
    return max(0.0, min(score, 1.0))


def _find_caption(
    page_blocks: list[Block],
    bbox: tuple[float, float, float, float],
    search_below: bool = True,
) -> str | None:
    """Look just above and just below the table for a 'Table N' style caption."""
    best: tuple[float, str] | None = None
    for block in page_blocks:
        if block.kind != "text" or not block.text.strip():
            continue
        # A caption whose label is bold opens with an emphasis sentinel.
        text = strip_all_sentinels(block.text).strip()
        if not _CAPTION_RE.match(text):
            continue
        gap_above = bbox[1] - block.bbox[3]
        gap_below = block.bbox[1] - bbox[3]
        gap = min(abs(gap_above), abs(gap_below)) if search_below else abs(gap_above)
        if gap <= _CAPTION_SEARCH_GAP_PT and (best is None or gap < best[0]):
            best = (gap, " ".join(text.split()))
    return best[1] if best else None


def _blocks_inside(page_blocks: list[Block], bbox: tuple[float, float, float, float]) -> list[str]:
    """Text blocks whose centre falls inside the table, so the caller can drop
    them and avoid emitting the same text twice."""
    covered: list[str] = []
    for block in page_blocks:
        if block.kind != "text":
            continue
        cx = (block.bbox[0] + block.bbox[2]) / 2
        cy = (block.bbox[1] + block.bbox[3]) / 2
        if bbox[0] <= cx <= bbox[2] and bbox[1] <= cy <= bbox[3]:
            covered.append(block.block_id)
    return covered


def detect_tables_on_page(
    page: fitz.Page,
    page_blocks: list[Block],
    evidence: HyphenEvidence | None = None,
    ruled: bool = True,
) -> list[DetectedTable]:
    """Find tables using PyMuPDF's geometric ruling/whitespace analysis.

    Purely local and deterministic — no model, no API. Every detection carries a
    confidence so the renderer can choose semantic markup or an image fallback.
    `ruled=False` looks only for tables set out by alignment under a caption.
    """
    page_num = page.number + 1
    if not ruled:
        return _aligned_tables(page_num, page_blocks, [])
    try:
        found = page.find_tables()
    except Exception:
        logger.exception("table detection failed on page %d", page_num)
        return []

    results: list[DetectedTable] = []
    for index, table in enumerate(getattr(found, "tables", []) or []):
        try:
            extracted = table.extract()
        except Exception:
            logger.warning("could not extract table %d on page %d", index, page_num)
            continue

        try:
            row_boxes = [tuple(float(v) for v in row.bbox) for row in table.rows]
        except Exception:
            row_boxes = []
        if len(row_boxes) != len(extracted or []):
            row_boxes = []
        table_bbox = tuple(float(v) for v in table.bbox)  # type: ignore[arg-type]

        indexed = [
            (i, [_cell_text(c, evidence) for c in row]) for i, row in enumerate(extracted or [])
        ]
        indexed = [(i, r) for i, r in indexed if any(c.strip() for c in r)]

        # Two tables set one after the other with a "Tablo 2: ..." line
        # between them share their rules, and are found as one grid with the
        # columns of both. The caption line is where the second begins.
        segments: list[tuple[str | None, list[tuple[int, list[str]]]]] = []
        caption_here: str | None = None
        current: list[tuple[int, list[str]]] = []
        for i, row in indexed:
            caption = _caption_row([row])
            if caption:
                if current:
                    segments.append((caption_here, current))
                caption_here, current = caption, []
            else:
                current.append((i, row))
        if current:
            segments.append((caption_here, current))

        for caption_in_grid, segment in segments:
            if len(segments) > 1 and row_boxes:
                boxes = [row_boxes[i] for i, _ in segment]
                bbox = (
                    min(b[0] for b in boxes),
                    min(b[1] for b in boxes),
                    max(b[2] for b in boxes),
                    max(b[3] for b in boxes),
                )
            else:
                bbox = table_bbox
            # Where one grid held two tables, the caption between them is the
            # second one's; the first may only find its own above it.
            detected = _detected_table(
                page_num,
                [r for _, r in segment],
                bbox,
                caption_in_grid,
                page_blocks,
                search_below=len(segments) == 1,
            )
            if detected is not None:
                results.append(detected)

    claimed = [t.bbox for t in results]
    results.extend(_aligned_tables(page_num, page_blocks, claimed))
    return results


# --- tables drawn with rules across, none down -------------------------------
#
# Most academic tables are set with three horizontal rules and no vertical
# ones. Ruling-based detection needs both, so a Turkish article's "Çizelge 1"
# came out as one paragraph per row -- "SiO2 19,10 18,20" -- under a heading
# made of its column titles. A table is still unmistakable: under its caption,
# rows whose pieces stand in the same columns, row after row.

# Pieces of a row are separated by more space than a word gap.
_CELL_GAP_RATIO = 1.0
# The first row may start a little way below the caption.
_FIRST_ROW_GAP_PT = 40.0
# A gap between rows this many times the line height ends the table.
_ROW_GAP_RATIO = 3.0
_MIN_ALIGNED_ROWS = 3
# A row of a table is short; a line of prose that long ends it.
_MAX_ROW_CHARS = 160


def _row_cells(block: Block) -> list[tuple[float, float, str]]:
    """The pieces of a block that sits on one line, as (x0, x1, text)."""
    spans = [sp for sp in block.spans if sp.text.strip()]
    if not spans:
        return []
    size = block.font_size or spans[0].font_size or 10.0
    # One printed line only: a wrapped paragraph is not a row.
    baselines = sorted({round(sp.baseline) for sp in spans})
    if baselines[-1] - baselines[0] > size * 0.9:
        return []
    cells: list[tuple[float, float, str]] = []
    for span in sorted(spans, key=lambda sp: sp.bbox[0]):
        if cells and span.bbox[0] - cells[-1][1] <= size * _CELL_GAP_RATIO:
            x0, _, text = cells[-1]
            gap = " " if span.bbox[0] - cells[-1][1] > size * 0.15 and not text.endswith(" ") else ""
            cells[-1] = (x0, span.bbox[2], text + gap + span.text)
        else:
            cells.append((span.bbox[0], span.bbox[2], span.text))
    return [(x0, x1, " ".join(t.split())) for x0, x1, t in cells]


def _columns(rows: list[list[tuple[float, float, str]]]) -> list[tuple[float, float]]:
    """Column extents: the pieces of every row, merged where they overlap."""
    spans = sorted((x0, x1) for row in rows for x0, x1, _ in row)
    columns: list[list[float]] = []
    for x0, x1 in spans:
        if columns and x0 <= columns[-1][1]:
            columns[-1][1] = max(columns[-1][1], x1)
        else:
            columns.append([x0, x1])
    return [(a, b) for a, b in columns]


def _aligned_tables(
    page_num: int, page_blocks: list[Block], claimed: list[tuple[float, float, float, float]]
) -> list[DetectedTable]:
    text_blocks = sorted(
        (b for b in page_blocks if b.kind == "text" and b.text.strip()),
        key=lambda b: (b.bbox[1], b.bbox[0]),
    )
    found: list[DetectedTable] = []
    for index, caption in enumerate(text_blocks):
        caption_text = " ".join(strip_all_sentinels(caption.text).split())
        if not _CAPTION_RE.match(caption_text):
            continue
        if any(_overlaps_vertically(caption.bbox, box) for box in claimed):
            continue
        rows: list[list[tuple[float, float, str]]] = []
        row_blocks: list[Block] = []
        bottom = caption.bbox[3]
        for block in text_blocks[index + 1 :]:
            size = block.font_size or 10.0
            limit = _FIRST_ROW_GAP_PT if not rows else size * _ROW_GAP_RATIO
            if block.bbox[1] - bottom > limit:
                break
            cells = _row_cells(block)
            if len(cells) < 2 or len(strip_all_sentinels(block.text)) > _MAX_ROW_CHARS:
                break
            rows.append(cells)
            row_blocks.append(block)
            bottom = max(bottom, block.bbox[3])
        if len(rows) < _MIN_ALIGNED_ROWS:
            continue
        # Columns come from the body. A header's titles are often set closer
        # together than its columns, and taken as one piece they merged two
        # columns into one.
        columns = _columns(rows[1:])
        if len(columns) < 2:
            continue
        header = [
            (sp.bbox[0], sp.bbox[2], sp.text) for sp in row_blocks[0].spans if sp.text.strip()
        ]
        grid = [_place(header, columns)] + [_place(cells, columns) for cells in rows[1:]]
        # Every row must reach across the table: a run of two-part lines that
        # line up only by chance -- a list of names and dates -- does not.
        if sum(1 for row in grid if sum(1 for c in row if c) >= 2) < len(grid) * 0.8:
            continue
        bbox = (
            min(b.bbox[0] for b in row_blocks),
            min(b.bbox[1] for b in row_blocks),
            max(b.bbox[2] for b in row_blocks),
            max(b.bbox[3] for b in row_blocks),
        )
        detected = _detected_table(page_num, grid, bbox, caption_text, page_blocks)
        if detected is not None:
            detected.covered_block_ids = [b.block_id for b in row_blocks]
            found.append(detected)
            claimed.append(bbox)
    return found


def _place(cells: list[tuple[float, float, str]], columns: list[tuple[float, float]]) -> list[str]:
    """Put each piece in the column it overlaps most, or the nearest one."""
    row = [""] * len(columns)
    pieces: list[tuple[float, float, str]] = []
    for x0, x1, text in sorted(cells):
        # One run of text across several columns -- titles the typesetter
        # separated with spaces -- is split where the spaces are wide, when
        # that gives exactly one title per column it spans.
        spanned = [i for i, (a, b) in enumerate(columns) if min(x1, b) - max(x0, a) > 0]
        parts = [part for part in re.split(r"\s{2,}", text.strip()) if part]
        if len(spanned) > 1 and len(parts) == len(spanned):
            pieces.extend((columns[i][0], columns[i][1], part) for i, part in zip(spanned, parts))
        else:
            pieces.append((x0, x1, text))
    for x0, x1, text in pieces:
        def closeness(column: tuple[float, float]) -> float:
            overlap = min(x1, column[1]) - max(x0, column[0])
            if overlap > 0:
                return overlap
            return -min(abs(x0 - column[1]), abs(column[0] - x1))

        best = max(range(len(columns)), key=lambda i: closeness(columns[i]))
        joined = f"{row[best]} {text}" if row[best] and not row[best].endswith(" ") else row[best] + text
        row[best] = joined
    return [" ".join(c.split()) if c.strip() else "" for c in row]


def _overlaps_vertically(a: tuple[float, ...], b: tuple[float, ...]) -> bool:
    return a[1] < b[3] and b[1] < a[3]


def _detected_table(
    page_num: int,
    rows: list[list[str]],
    bbox: tuple[float, float, float, float],
    caption_in_grid: str | None,
    page_blocks: list[Block],
    search_below: bool = True,
) -> DetectedTable | None:
    rows = _drop_empty_columns(rows)
    if len(rows) < 2:
        return None

    confidence = _score_table(rows)
    # A zero score means the shape is not a table at all, as opposed to a
    # real table we are unsure we can render. Keeping it would still take
    # the text it covers out of the prose and hand it to the image
    # fallback, so a picture of a chapter heading would replace the
    # heading itself.
    if confidence <= 0.0:
        return None
    col_count = max(len(r) for r in rows)
    has_header = _looks_like_header(rows[0], rows[1:])

    cells: list[TableCell] = []
    for r_index, row in enumerate(rows):
        for c_index, value in enumerate(row):
            cells.append(
                TableCell(
                    text=value,
                    row=r_index,
                    col=c_index,
                    is_header=has_header and r_index == 0,
                )
            )

    return DetectedTable(
        page=page_num,
        bbox=bbox,
        data=TableData(
            rows=len(rows),
            cols=col_count,
            cells=cells,
            has_header_row=has_header,
            caption=caption_in_grid or _find_caption(page_blocks, bbox, search_below),
            confidence=confidence,
        ),
        covered_block_ids=_blocks_inside(page_blocks, bbox),
    )


def mark_continuations(tables: list[DetectedTable]) -> None:
    """Flag a table as continuing the previous page's when the two have matching
    column counts and the earlier one runs to the bottom of its page."""
    by_page = sorted(tables, key=lambda t: (t.page, t.bbox[1]))
    for previous, current in zip(by_page, by_page[1:]):
        if current.page != previous.page + 1:
            continue
        if current.data.cols != previous.data.cols:
            continue
        if current.data.caption:
            continue  # its own caption means it's a new table, not a continuation
        current.data.continues_from_previous_page = True
