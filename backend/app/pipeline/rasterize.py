from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import fitz

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Padding around a preserved region so glyphs aren't clipped at the edges.
_REGION_PADDING_PT = 4.0
# Absolute DPI floor. Deliberately below screen resolution: on a very large
# source page the pixel cap must win, and a higher floor would silently
# override it and let a single region exhaust memory.
_MIN_DPI = 36
# A region smaller than this in either axis holds no recoverable content.
_MIN_REGION_PT = 2.0


@dataclass
class RasterizedRegion:
    ref: str
    path: Path
    page: int
    bbox: tuple[float, float, float, float]
    width_px: int
    height_px: int
    dpi: int


def _effective_dpi(width_pt: float, height_pt: float) -> int:
    """Pick a DPI that stays readable on an e-reader without producing an asset
    so large it bloats the EPUB or exhausts memory.

    Small regions (a single inline equation) get rendered at a higher DPI than
    a full-page table, because they're displayed much smaller — a flat DPI
    would make one illegible or the other enormous.
    """
    base = settings.fallback_render_dpi
    area_pt = max(width_pt * height_pt, 1.0)
    # Below ~1.5 sq in, bump resolution so small math renders crisply.
    if area_pt < 1.5 * 72 * 72:
        base = int(base * 1.75)

    pixels = (width_pt / 72.0 * base) * (height_pt / 72.0 * base)
    if pixels > settings.fallback_max_pixels:
        base = int(base * math.sqrt(settings.fallback_max_pixels / pixels))
    return max(_MIN_DPI, base)


def rasterize_region(
    page: fitz.Page,
    bbox: tuple[float, float, float, float],
    images_dir: Path,
    ref: str,
    padding: float = _REGION_PADDING_PT,
) -> RasterizedRegion | None:
    """Render one region of a page to a high-resolution PNG.

    This is the "preserve the source rather than guess" path: whenever semantic
    reconstruction isn't safe, the caller keeps the original pixels instead of
    emitting content that might be wrong. Only the region is rendered — never
    the whole book.
    """
    # Check the requested region *before* padding: padding would otherwise
    # inflate a zero-area request into a valid-looking 8pt box and produce an
    # asset containing nothing.
    if (bbox[2] - bbox[0]) < _MIN_REGION_PT or (bbox[3] - bbox[1]) < _MIN_REGION_PT:
        logger.warning("refusing to rasterize a degenerate region on page %d", page.number + 1)
        return None

    page_rect = page.rect
    clip = fitz.Rect(
        max(page_rect.x0, bbox[0] - padding),
        max(page_rect.y0, bbox[1] - padding),
        min(page_rect.x1, bbox[2] + padding),
        min(page_rect.y1, bbox[3] + padding),
    )
    if clip.is_empty or clip.width <= 1 or clip.height <= 1:
        logger.warning("refusing to rasterize an out-of-page region on page %d", page.number + 1)
        return None

    dpi = _effective_dpi(clip.width, clip.height)
    try:
        pix = page.get_pixmap(clip=clip, dpi=dpi)
    except Exception:
        logger.exception("failed to rasterize region %s", ref)
        return None

    images_dir.mkdir(parents=True, exist_ok=True)
    out_path = images_dir / f"{ref}.png"
    pix.save(str(out_path))

    return RasterizedRegion(
        ref=ref,
        path=out_path,
        page=page.number + 1,
        bbox=(clip.x0, clip.y0, clip.x1, clip.y1),
        width_px=pix.width,
        height_px=pix.height,
        dpi=dpi,
    )
