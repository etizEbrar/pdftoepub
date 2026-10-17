from __future__ import annotations

import re
from dataclasses import dataclass

import fitz

from app.core.logging import get_logger
from app.models.document import Block, TableCell, TableData
from app.pipeline.footnotes import strip_all_sentinels
from app.pipeline.hyphenation import HyphenEvidence, join_lines_with_hyphenation_repair

logger = get_logger(__name__)

_CAPTION_RE = re.compile(r"^\s*(table|tablo|tabelle|tableau)\s*[\d.]+", re.IGNORECASE)
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
) -> list[DetectedTable]:
    """Find tables using PyMuPDF's geometric ruling/whitespace analysis.

    Purely local and deterministic — no model, no API. Every detection carries a
    confidence so the renderer can choose semantic markup or an image fallback.
    """
    page_num = page.number + 1
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

    return results


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
