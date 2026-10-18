from __future__ import annotations

from pathlib import Path

import fitz

from app.core.logging import get_logger
from app.models.document import Block
from app.pipeline import rasterize

logger = get_logger(__name__)


def to_image_blocks(extracted_images: list[dict], page_width: float, page_height: float) -> list[Block]:
    """Wrap extracted raster images as Blocks so they flow through reading-order
    and structure classification alongside text, preserving their position in
    the logical document (spec section 22)."""
    blocks: list[Block] = []
    for img in extracted_images:
        blocks.append(
            Block(
                block_id=img["ref"],
                page=img["page"],
                page_width=page_width,
                page_height=page_height,
                bbox=tuple(img["bbox"]),
                kind="image",
                image_ref=img["ref"],
            )
        )
    return blocks


# An image this large, with the page's text printed over it, is the page itself:
# the scan under an OCR text layer, or the background and mask layers a scanner
# splits a page into. On a real 327-page novel every page carried two of them,
# and every one went into the EPUB as a picture of the page it already held.
_BACKGROUND_COVERAGE = 0.5
# Text characters inside the image's box that mark it as a page under text,
# rather than a large photograph with a caption beside it.
_BACKGROUND_MIN_TEXT_CHARS = 3

# What of a page background is still worth a picture: a region of ink outside
# the text at least this share of the page. A chapter's ornament -- a cloud, a
# cat -- is far smaller; a photograph or a drawing is not.
_ILLUSTRATION_MIN_AREA = 0.06
_ILLUSTRATION_MIN_SIDE = 0.15
# The scan is examined at low resolution, in square cells this many pixels on a
# side; a cell is inked when this share of it is dark.
_PROBE_DPI = 36
_CELL_PX = 6
_INK_LEVEL = 150
_CELL_INK_SHARE = 0.04
# Text boxes are grown by this much before being blanked, so the edges of the
# glyphs they hold are not mistaken for a picture.
_TEXT_MARGIN_PT = 3.0
# The scanner's own edge -- the shadow of the binding, the platen's border --
# is ink too. A region pressed against the page edge on two sides is that.
_EDGE_PT = 4.0

_DARK = bytes(1 if level < _INK_LEVEL else 0 for level in range(256))


def _area(bbox) -> float:
    return max(0.0, bbox[2] - bbox[0]) * max(0.0, bbox[3] - bbox[1])


def _inside(inner, outer) -> bool:
    cx = (inner[0] + inner[2]) / 2
    cy = (inner[1] + inner[3]) / 2
    return outer[0] <= cx <= outer[2] and outer[1] <= cy <= outer[3]


def is_page_background(image: dict, text_blocks: list[Block], page: fitz.Page) -> bool:
    page_area = page.rect.width * page.rect.height
    if page_area <= 0 or _area(image["bbox"]) < page_area * _BACKGROUND_COVERAGE:
        return False
    chars = sum(
        len(block.text.strip())
        for block in text_blocks
        if block.kind == "text" and _inside(block.bbox, image["bbox"])
    )
    return chars >= _BACKGROUND_MIN_TEXT_CHARS


def _ink_cells(page: fitz.Page, text_blocks: list[Block]) -> tuple[set[tuple[int, int]], float]:
    """Cells of the page, outside its text, that carry ink."""
    pix = page.get_pixmap(dpi=_PROBE_DPI, colorspace=fitz.csGRAY, alpha=False)
    scale = _PROBE_DPI / 72.0
    for block in text_blocks:
        if block.kind != "text":
            continue
        x0, y0, x1, y1 = block.bbox
        rect = fitz.IRect(
            int((x0 - _TEXT_MARGIN_PT) * scale),
            int((y0 - _TEXT_MARGIN_PT) * scale),
            int((x1 + _TEXT_MARGIN_PT) * scale) + 1,
            int((y1 + _TEXT_MARGIN_PT) * scale) + 1,
        ) & pix.irect
        if not rect.is_empty:
            pix.set_rect(rect, (255,))
    dark = pix.samples.translate(_DARK)
    width, height, stride = pix.width, pix.height, pix.stride
    threshold = _CELL_PX * _CELL_PX * _CELL_INK_SHARE
    cells: set[tuple[int, int]] = set()
    for cy in range(0, height, _CELL_PX):
        for cx in range(0, width, _CELL_PX):
            right = min(cx + _CELL_PX, width)
            inked = sum(
                dark[row * stride + cx : row * stride + right].count(1)
                for row in range(cy, min(cy + _CELL_PX, height))
            )
            if inked >= threshold:
                cells.add((cx // _CELL_PX, cy // _CELL_PX))
    return cells, _CELL_PX / scale


def _regions(cells: set[tuple[int, int]]) -> list[tuple[int, int, int, int]]:
    """Bounding boxes, in cells, of groups of inked cells touching or one apart."""
    remaining = set(cells)
    regions = []
    while remaining:
        stack = [remaining.pop()]
        x0 = x1 = stack[0][0]
        y0 = y1 = stack[0][1]
        while stack:
            cx, cy = stack.pop()
            x0, x1, y0, y1 = min(x0, cx), max(x1, cx), min(y0, cy), max(y1, cy)
            for dx in (-2, -1, 0, 1, 2):
                for dy in (-2, -1, 0, 1, 2):
                    neighbour = (cx + dx, cy + dy)
                    if neighbour in remaining:
                        remaining.remove(neighbour)
                        stack.append(neighbour)
        regions.append((x0, y0, x1 + 1, y1 + 1))
    return regions


def illustrations_in_background(
    page: fitz.Page, page_index: int, text_blocks: list[Block], images_dir: Path
) -> list[dict]:
    """Cut the real pictures out of a page background, leaving the ornaments.

    The background is not discarded wholesale: a scanned book's photographs and
    drawings live in it too. Everything the text layer does not cover is
    examined, and only a region large enough to be a picture is kept, rendered
    from the page as it prints.
    """
    page_rect = page.rect
    page_area = page_rect.width * page_rect.height
    try:
        cells, cell_pt = _ink_cells(page, text_blocks)
    except Exception:
        logger.exception("could not examine the background of page %d", page_index + 1)
        return []
    found: list[dict] = []
    for x0, y0, x1, y1 in _regions(cells):
        bbox = (
            max(page_rect.x0, x0 * cell_pt),
            max(page_rect.y0, y0 * cell_pt),
            min(page_rect.x1, x1 * cell_pt),
            min(page_rect.y1, y1 * cell_pt),
        )
        width, height = bbox[2] - bbox[0], bbox[3] - bbox[1]
        if _area(bbox) < page_area * _ILLUSTRATION_MIN_AREA:
            continue
        if width < page_rect.width * _ILLUSTRATION_MIN_SIDE or height < page_rect.height * _ILLUSTRATION_MIN_SIDE:
            continue
        edges = sum(
            (
                bbox[0] <= page_rect.x0 + _EDGE_PT,
                bbox[1] <= page_rect.y0 + _EDGE_PT,
                bbox[2] >= page_rect.x1 - _EDGE_PT,
                bbox[3] >= page_rect.y1 - _EDGE_PT,
            )
        )
        if edges >= 2 and min(width, height) < min(page_rect.width, page_rect.height) * 0.1:
            continue
        ref = f"p{page_index + 1}_art{len(found):02d}"
        region = rasterize.rasterize_region(page, bbox, images_dir, ref, photo=True)
        if region is None:
            continue
        found.append(
            {
                "ref": region.ref,
                "path": str(region.path),
                "ext": region.path.suffix.lstrip("."),
                "page": page_index + 1,
                "bbox": list(region.bbox),
            }
        )
    return found


def drop_page_backgrounds(
    page: fitz.Page,
    page_index: int,
    extracted_images: list[dict],
    text_blocks: list[Block],
    images_dir: Path,
) -> list[dict]:
    """The page's images minus the page itself, plus any picture cut from it."""
    backgrounds = [img for img in extracted_images if is_page_background(img, text_blocks, page)]
    if not backgrounds:
        return extracted_images
    for img in backgrounds:
        try:
            Path(img["path"]).unlink(missing_ok=True)
        except OSError:
            pass
    kept = [img for img in extracted_images if img not in backgrounds]
    return kept + illustrations_in_background(page, page_index, text_blocks, images_dir)
