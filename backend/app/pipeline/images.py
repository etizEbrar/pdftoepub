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


_ROOM_GRID_PT = 12.0


# Pages with this much text show where the book sets its type.
_TYPE_AREA_MIN_CHARS = 300
_TYPE_AREA_SAMPLE_PAGES = 80


def type_area(doc: fitz.Document) -> tuple[float, float, float, float] | None:
    """Where the book sets its text, from the pages that are full of it.

    Read from the text alone, without the pictures, so it costs a few
    milliseconds a page. The median page's extent, running head to last line.
    """
    step = max(1, doc.page_count // _TYPE_AREA_SAMPLE_PAGES)
    from app.pipeline.extract import TEXT_ONLY_FLAGS

    extents: list[tuple[float, float, float, float]] = []
    for index in range(0, doc.page_count, step):
        blocks = [
            b for b in doc[index].get_text("dict", flags=TEXT_ONLY_FLAGS).get("blocks", [])
            if b.get("type") == 0
        ]
        chars = sum(len(s.get("text", "")) for b in blocks for ln in b.get("lines", []) for s in ln.get("spans", []))
        if chars < _TYPE_AREA_MIN_CHARS:
            continue
        extents.append(
            (
                min(b["bbox"][0] for b in blocks),
                min(b["bbox"][1] for b in blocks),
                max(b["bbox"][2] for b in blocks),
                max(b["bbox"][3] for b in blocks),
            )
        )
    if len(extents) < 3:
        return None
    middle = len(extents) // 2
    return tuple(sorted(e[i] for e in extents)[middle] for i in range(4))  # type: ignore[return-value]


def _room_for_a_picture(
    page_rect: fitz.Rect,
    text_blocks: list[Block],
    area: tuple[float, float, float, float] | None = None,
) -> bool:
    """Whether the text leaves an empty rectangle the size of the smallest picture kept.

    Looked for inside the book's type area: the margins around the text are a
    long empty strip on every page of an old book, and no picture.
    """
    boxes = [b.bbox for b in text_blocks if b.kind == "text" and b.text.strip()]
    if not boxes:
        return True
    if area is None:
        area = (min(b[0] for b in boxes), page_rect.y0, max(b[2] for b in boxes), page_rect.y1)
    left, top = max(page_rect.x0, area[0]), max(page_rect.y0, area[1])
    right, bottom = min(page_rect.x1, area[2]), min(page_rect.y1, area[3])
    if right - left < page_rect.width * _ILLUSTRATION_MIN_SIDE or bottom - top < page_rect.height * _ILLUSTRATION_MIN_SIDE:
        return True
    columns = max(1, int((right - left) / _ROOM_GRID_PT))
    rows = max(1, int((bottom - top) / _ROOM_GRID_PT))
    cell_w, cell_h = (right - left) / columns, (bottom - top) / rows
    filled = [[False] * columns for _ in range(rows)]
    for x0, y0, x1, y1 in boxes:
        for r in range(max(0, int((y0 - top) / cell_h)), min(rows, int((y1 - top) / cell_h) + 1)):
            for c in range(max(0, int((x0 - left) / cell_w)), min(columns, int((x1 - left) / cell_w) + 1)):
                filled[r][c] = True
    need_w = page_rect.width * _ILLUSTRATION_MIN_SIDE
    need_h = page_rect.height * _ILLUSTRATION_MIN_SIDE
    need_area = page_rect.width * page_rect.height * _ILLUSTRATION_MIN_AREA
    # Largest empty rectangle, row by row, over a histogram of empty runs.
    heights = [0] * columns
    for r in range(rows):
        for c in range(columns):
            heights[c] = 0 if filled[r][c] else heights[c] + 1
        stack: list[int] = []
        for c in range(columns + 1):
            current = heights[c] if c < columns else 0
            while stack and heights[stack[-1]] >= current:
                height = heights[stack.pop()]
                left = stack[-1] + 1 if stack else 0
                w, h = (c - left) * cell_w, height * cell_h
                if w >= need_w and h >= need_h and w * h >= need_area:
                    return True
            stack.append(c)
    return False


# A picture carries a caption beside it or a few labels on it, not lines of
# text over a quarter of its area.
_MAX_PICTURE_TEXT_SHARE = 0.25


def _text_share(region: tuple[float, float, float, float], text_blocks: list[Block]) -> float:
    area = _area(region)
    if area <= 0:
        return 0.0
    covered = 0.0
    for block in text_blocks:
        if block.kind != "text":
            continue
        x0, y0, x1, y1 = block.bbox
        covered += _area((max(x0, region[0]), max(y0, region[1]), min(x1, region[2]), min(y1, region[3])))
    return covered / area


def illustrations_in_background(
    page: fitz.Page,
    page_index: int,
    text_blocks: list[Block],
    images_dir: Path,
    area: tuple[float, float, float, float] | None = None,
) -> list[dict]:
    """Cut the real pictures out of a page background, leaving the ornaments.

    The background is not discarded wholesale: a scanned book's photographs and
    drawings live in it too. Everything the text layer does not cover is
    examined, and only a region large enough to be a picture is kept, rendered
    from the page as it prints.
    """
    page_rect = page.rect
    page_area = page_rect.width * page_rect.height
    if not _room_for_a_picture(page_rect, text_blocks, area):
        # A page of text leaves no space a picture could be in, and looking
        # means decoding the scan: two thirds of a scanned book's conversion
        # time went on pages of nothing but text.
        return []
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
        if _text_share(bbox, text_blocks) > _MAX_PICTURE_TEXT_SHARE:
            # Rules and ornaments around lines of print -- a title page --
            # join into one region of ink. Its words are already text; as a
            # picture as well, the page appeared twice.
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
    area: tuple[float, float, float, float] | None = None,
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
    return kept + illustrations_in_background(page, page_index, text_blocks, images_dir, area)


# A first page this much covered by one picture, carrying no more text than a
# cover's title, author and strapline, is the book's cover.
_COVER_IMAGE_COVERAGE = 0.5
_COVER_MAX_TEXT_CHARS = 400


def cover_from_first_page(
    page: fitz.Page,
    extracted_images: list[dict],
    text_blocks: list[Block],
    images_dir: Path,
) -> dict | None:
    """The first page, whole, as the book's cover.

    A cover is designed as one picture: artwork with its title set over it.
    Read like any other page, its title came out as a line of text and the
    artwork as a page background, from which the largest picture -- one of
    the two people on the cover -- was cut out and used as the cover instead.
    The page is rendered as it prints, title and all, and nothing on it is
    read as text.
    """
    page_area = page.rect.width * page.rect.height
    if page_area <= 0 or not any(
        _area(img["bbox"]) >= page_area * _COVER_IMAGE_COVERAGE for img in extracted_images
    ):
        return None
    chars = sum(len(b.text.strip()) for b in text_blocks if b.kind == "text")
    # A picture with no text over it may be a scanned page of text: OCR decides
    # that, and a cover it cannot read is kept as the whole page anyway.
    if not chars or chars > _COVER_MAX_TEXT_CHARS:
        return None
    region = rasterize.rasterize_region(page, tuple(page.rect), images_dir, "cover", padding=0.0, photo=True)
    if region is None:
        return None
    for img in extracted_images:
        if not img.get("path"):
            continue
        try:
            Path(img["path"]).unlink(missing_ok=True)
        except OSError:
            pass
    return {
        "ref": region.ref,
        "path": str(region.path),
        "ext": region.path.suffix.lstrip("."),
        "page": page.number + 1,
        "bbox": list(region.bbox),
    }


# A blank leaf: the paper's own colour nearly everywhere. Ink is anything this
# much darker than the paper, and a page with less than this share of it --
# a library stamp, a pencilled shelf mark -- has nothing to read. Measured on
# real scans: blank leaves at 0.02% or less, the sparsest page of verse at 2%.
_BLANK_PROBE_DPI = 40
_BLANK_INK_CONTRAST = 50
_BLANK_MAX_INK_SHARE = 0.001


def is_blank_page(page: fitz.Page) -> bool:
    """Whether a page without a text layer is an empty leaf of paper.

    A scanned book opens and closes on endpapers and flyleaves. Each went to
    OCR, which found nothing, and was then kept as a picture of a page: a
    reader paged through a dozen photographs of blank paper before chapter one.
    """
    try:
        pix = page.get_pixmap(dpi=_BLANK_PROBE_DPI, colorspace=fitz.csGRAY, alpha=False)
    except Exception:
        return False
    samples = pix.samples
    if not samples:
        return False
    histogram = [samples.count(level) for level in range(256)]
    total = len(samples)
    # The paper is the median level: aged, tinted or grey, it fills the page.
    running, paper = 0, 255
    for level, count in enumerate(histogram):
        running += count
        if running >= total / 2:
            paper = level
            break
    ink = sum(histogram[: max(0, paper - _BLANK_INK_CONTRAST)])
    return ink / total < _BLANK_MAX_INK_SHARE


# An image shaped like the page and at least this many pixels per point across
# it is a scan of the page (or one layer of one), whatever else is on it.
_SCAN_ASPECT_TOLERANCE = 0.03
_SCAN_MIN_PIXELS_PER_POINT = 1.0


def page_is_scan(page: fitz.Page) -> bool:
    """Whether every picture on the page is the page itself, read cheaply.

    Answered from the images' pixel sizes alone. Finding where an image sits
    on the page means running the page, which decodes every scan in full: on a
    232-page book each run cost a third of a second and memory MuPDF kept, and
    a page was run three or four times over -- for its text, its pictures,
    its tables -- to throw the scan away at the end.
    """
    width, height = page.rect.width, page.rect.height
    if not width or not height:
        return False
    images = page.get_images(full=True)
    if not images:
        return False
    aspect = width / height
    for item in images:
        pixels_wide, pixels_high = item[2], item[3]
        if not pixels_wide or not pixels_high:
            return False
        if abs(pixels_wide / pixels_high - aspect) > aspect * _SCAN_ASPECT_TOLERANCE:
            return False
        if pixels_wide < width * _SCAN_MIN_PIXELS_PER_POINT:
            return False
    return True
