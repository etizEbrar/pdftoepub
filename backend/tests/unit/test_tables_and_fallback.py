from pathlib import Path

import fitz

from app.core.config import settings
from app.models.document import Block, TableCell, TableData
from app.pipeline.rasterize import rasterize_region
from app.pipeline.tables import _score_table, detect_tables_on_page, mark_continuations


def _ruled_table_pdf(path: Path, rows: int = 4, cols: int = 4) -> Path:
    """A table with real ruling lines, which is what geometric detection keys on."""
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    x0, y0 = 72, 120
    col_w, row_h = 110, 24
    headers = ["Region", "Q1", "Q2", "Q3"][:cols]
    data = [
        ["North", "120", "135", "150"],
        ["South", "98", "104", "119"],
        ["East", "76", "88", "91"],
        ["West", "141", "150", "162"],
    ][:rows]

    for r in range(rows + 2):
        y = y0 + r * row_h
        page.draw_line(fitz.Point(x0, y), fitz.Point(x0 + col_w * cols, y))
    for c in range(cols + 1):
        x = x0 + c * col_w
        page.draw_line(fitz.Point(x, y0), fitz.Point(x, y0 + row_h * (rows + 1)))

    for c, head in enumerate(headers):
        page.insert_text((x0 + c * col_w + 5, y0 + 17), head, fontsize=10)
    for r, row in enumerate(data, start=1):
        for c, value in enumerate(row[:cols]):
            page.insert_text((x0 + c * col_w + 5, y0 + r * row_h + 17), value, fontsize=10)

    page.insert_text((72, y0 - 14), "Table 1. Revenue by region and quarter.", fontsize=10)
    doc.save(str(path))
    doc.close()
    return path


def test_detects_a_ruled_table_with_rows_columns_and_header(tmp_path: Path):
    doc = fitz.open(str(_ruled_table_pdf(tmp_path / "t.pdf")))
    page = doc[0]
    tables = detect_tables_on_page(page, [])
    doc.close()

    assert len(tables) == 1
    data = tables[0].data
    assert data.cols == 4
    assert data.rows >= 4
    assert data.has_header_row is True
    header_cells = [c.text for c in data.cells if c.is_header]
    assert "Region" in header_cells
    assert data.confidence >= settings.table_min_confidence


def test_finds_the_table_caption(tmp_path: Path):
    pdf = _ruled_table_pdf(tmp_path / "t.pdf")
    doc = fitz.open(str(pdf))
    page = doc[0]
    from app.pipeline import extract

    blocks = extract.extract_page_blocks(page, 0)
    tables = detect_tables_on_page(page, blocks)
    doc.close()

    assert tables[0].data.caption is not None
    assert "Table 1" in tables[0].data.caption


def test_covered_blocks_are_reported_so_text_is_not_duplicated(tmp_path: Path):
    pdf = _ruled_table_pdf(tmp_path / "t.pdf")
    doc = fitz.open(str(pdf))
    page = doc[0]
    from app.pipeline import extract

    blocks = extract.extract_page_blocks(page, 0)
    tables = detect_tables_on_page(page, blocks)
    doc.close()

    assert tables[0].covered_block_ids, "table must claim the blocks it absorbed"


def test_confidence_scoring_rejects_shapes_that_are_not_really_tables():
    # One column is a list, not a table.
    assert _score_table([["a"], ["b"], ["c"]]) == 0.0
    # A single row cannot establish a grid.
    assert _score_table([["a", "b"]]) == 0.0
    # A mostly-empty grid is usually mis-detected layout.
    sparse = [["a", "", "", ""], ["", "", "", ""], ["", "", "b", ""]]
    assert _score_table(sparse) < settings.table_min_confidence
    # A full, consistent grid scores well.
    dense = [["h1", "h2", "h3"], ["1", "2", "3"], ["4", "5", "6"]]
    assert _score_table(dense) >= settings.table_min_confidence


def _detected(page: int, cols: int, caption: str | None = None):
    from app.pipeline.tables import DetectedTable

    return DetectedTable(
        page=page,
        bbox=(72, 100, 500, 700),
        data=TableData(rows=4, cols=cols, cells=[], caption=caption, confidence=0.8),
        covered_block_ids=[],
    )


def test_marks_a_table_continuing_onto_the_next_page():
    tables = [_detected(1, 4), _detected(2, 4)]
    mark_continuations(tables)
    assert tables[1].data.continues_from_previous_page is True


def test_a_new_captioned_table_is_not_treated_as_a_continuation():
    tables = [_detected(1, 4), _detected(2, 4, caption="Table 2. Something else.")]
    mark_continuations(tables)
    assert tables[1].data.continues_from_previous_page is False


def test_different_column_counts_are_not_a_continuation():
    tables = [_detected(1, 4), _detected(2, 6)]
    mark_continuations(tables)
    assert tables[1].data.continues_from_previous_page is False


# --- image fallback -------------------------------------------------------

def test_rasterizes_a_region_at_readable_resolution(tmp_path: Path):
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((100, 200), "Region content", fontsize=14)

    region = rasterize_region(page, (90, 180, 400, 260), tmp_path / "imgs", "region1")
    doc.close()

    assert region is not None
    assert region.path.exists()
    assert region.path.stat().st_size > 0
    # Must be a real rendering, never a thumbnail.
    assert region.width_px > 300
    assert region.dpi >= settings.fallback_render_dpi


def test_small_regions_get_a_higher_dpi_so_inline_math_stays_legible(tmp_path: Path):
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((100, 200), "x=1", fontsize=10)

    small = rasterize_region(page, (98, 190, 140, 205), tmp_path / "imgs", "small")
    large = rasterize_region(page, (72, 72, 540, 700), tmp_path / "imgs", "large")
    doc.close()

    assert small is not None and large is not None
    assert small.dpi > large.dpi


def test_oversized_region_is_capped_to_protect_memory(tmp_path: Path):
    doc = fitz.open()
    page = doc.new_page(width=2000, height=3000)
    region = rasterize_region(page, (0, 0, 2000, 3000), tmp_path / "imgs", "huge")
    doc.close()

    assert region is not None
    assert region.width_px * region.height_px <= settings.fallback_max_pixels * 1.05


def test_degenerate_region_is_refused_rather_than_producing_a_broken_asset(tmp_path: Path):
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    assert rasterize_region(page, (100, 100, 100, 100), tmp_path / "imgs", "empty") is None
    doc.close()
