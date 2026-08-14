from __future__ import annotations

import re
from dataclasses import dataclass

import fitz

from app.core.logging import get_logger
from app.models.document import Block, TableCell, TableData

logger = get_logger(__name__)

_CAPTION_RE = re.compile(r"^\s*(table|tablo|tabelle|tableau)\s*[\d.]+", re.IGNORECASE)
_CAPTION_SEARCH_GAP_PT = 60.0


@dataclass
class DetectedTable:
    page: int
    bbox: tuple[float, float, float, float]
    data: TableData
    covered_block_ids: list[str]


def _cell_text(cell_value: str | None) -> str:
    if not cell_value:
        return ""
    return " ".join(str(cell_value).split())


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


def _find_caption(page_blocks: list[Block], bbox: tuple[float, float, float, float]) -> str | None:
    """Look just above and just below the table for a 'Table N' style caption."""
    best: tuple[float, str] | None = None
    for block in page_blocks:
        if block.kind != "text" or not block.text.strip():
            continue
        text = block.text.strip()
        if not _CAPTION_RE.match(text):
            continue
        gap_above = bbox[1] - block.bbox[3]
        gap_below = block.bbox[1] - bbox[3]
        gap = min(g for g in (abs(gap_above), abs(gap_below)))
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


def detect_tables_on_page(page: fitz.Page, page_blocks: list[Block]) -> list[DetectedTable]:
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

        rows = [[_cell_text(c) for c in row] for row in extracted or []]
        rows = [r for r in rows if any(c.strip() for c in r)]
        if len(rows) < 2:
            continue

        confidence = _score_table(rows)
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

        bbox = tuple(float(v) for v in table.bbox)  # type: ignore[arg-type]
        results.append(
            DetectedTable(
                page=page_num,
                bbox=bbox,
                data=TableData(
                    rows=len(rows),
                    cols=col_count,
                    cells=cells,
                    has_header_row=has_header,
                    caption=_find_caption(page_blocks, bbox),
                    confidence=confidence,
                ),
                covered_block_ids=_blocks_inside(page_blocks, bbox),
            )
        )

    return results


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
