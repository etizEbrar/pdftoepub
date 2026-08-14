from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

import fitz

from app.core.config import settings
from app.core.logging import get_logger
from app.models.document import Block, Span, TextDirection
from app.pipeline.ocr.engine import OCRResult, OCRWord, run_ocr, tesseract_available

logger = get_logger(__name__)

# Tried in order only when the upright pass looks unreliable. Tesseract's own
# OSD proved unable to recover 180-degree pages in practice, so we re-OCR at
# each orientation and keep whichever scores best — deterministic, local, and
# only paid for on pages that actually need it.
_RETRY_ROTATIONS = (90, 180, 270)
_PSM_AUTO_OSD = 1  # auto page segmentation *with* orientation detection
_PSM_AUTO = 3


@dataclass
class PageOCROutcome:
    blocks: list[Block]
    mean_confidence: float
    rotation: int
    reliable: bool
    word_count: int


def rotate_pixmap(pix: fitz.Pixmap, rotation: int) -> fitz.Pixmap:
    """Rotate a rendered page clockwise by `rotation` degrees."""
    if rotation % 360 == 0:
        return pix
    swaps_axes = rotation % 180 == 90
    out_w, out_h = (pix.height, pix.width) if swaps_axes else (pix.width, pix.height)
    doc = fitz.open()
    page = doc.new_page(width=out_w, height=out_h)
    page.insert_image(fitz.Rect(0, 0, out_w, out_h), pixmap=pix, rotate=rotation)
    rotated = page.get_pixmap(matrix=fitz.Identity)
    doc.close()
    return rotated


def unrotate_bbox(
    bbox: tuple[float, float, float, float],
    rotation: int,
    rotated_w: float,
    rotated_h: float,
) -> tuple[float, float, float, float]:
    """Map a bbox from rotated-image space back into the original page's image
    space, so OCR geometry always agrees with the unrotated page and reading
    order stays correct."""
    x0, y0, x1, y1 = bbox
    match rotation % 360:
        case 0:
            return bbox
        case 90:
            return (y0, rotated_w - x1, y1, rotated_w - x0)
        case 180:
            return (rotated_w - x1, rotated_h - y1, rotated_w - x0, rotated_h - y0)
        case 270:
            return (rotated_h - y1, x0, rotated_h - y0, x1)
        case _:
            return bbox


def _group_words_into_lines(words: list[OCRWord]) -> list[list[OCRWord]]:
    """Group by Tesseract's own block/paragraph/line numbering — its layout
    analysis is more reliable than re-deriving lines from raw coordinates."""
    lines: dict[tuple[int, int, int], list[OCRWord]] = {}
    for word in words:
        lines.setdefault((word.block_num, word.par_num, word.line_num), []).append(word)
    return [sorted(lines[key], key=lambda w: w.word_num) for key in sorted(lines.keys())]


def _group_lines_into_blocks(words: list[OCRWord]) -> dict[int, list[list[OCRWord]]]:
    blocks: dict[int, list[list[OCRWord]]] = {}
    for line in _group_words_into_lines(words):
        blocks.setdefault(line[0].block_num, []).append(line)
    return blocks


def _best_orientation(
    pix: fitz.Pixmap, tmp_dir: Path, languages: str | None
) -> tuple[OCRResult, int, float, float]:
    """OCR upright first; pay for rotated retries only when that looks doubtful.

    The retry gate is `ocr_confident_accept_threshold`, not the reliability
    floor. That distinction matters: upside-down text scores in the mid-60s,
    which clears the floor, so gating retries on the floor would accept
    confident-looking nonsense and never try the orientation that reads
    correctly. Normal upright scans score in the 90s and still cost one pass.

    Returns (result, rotation, rotated_width, rotated_height).
    """
    upright_path = tmp_dir / "page.png"
    pix.save(str(upright_path))
    best = run_ocr(upright_path, languages, psm=_PSM_AUTO_OSD)
    best_rotation = 0
    best_size = (float(pix.width), float(pix.height))

    if best.words and best.mean_confidence >= settings.ocr_confident_accept_threshold:
        return best, best_rotation, best_size[0], best_size[1]

    for rotation in _RETRY_ROTATIONS:
        rotated = rotate_pixmap(pix, rotation)
        rotated_path = tmp_dir / f"page_{rotation}.png"
        rotated.save(str(rotated_path))
        candidate = run_ocr(rotated_path, languages, psm=_PSM_AUTO)
        if candidate.mean_confidence > best.mean_confidence:
            best = candidate
            best_rotation = rotation
            best_size = (float(rotated.width), float(rotated.height))
        if best.mean_confidence >= settings.ocr_confident_accept_threshold:
            break  # found a clearly-correct orientation; stop paying for more

    return best, best_rotation, best_size[0], best_size[1]


def ocr_page(
    page: fitz.Page,
    page_index: int,
    languages: str | None = None,
    dpi: int | None = None,
) -> PageOCROutcome:
    """Render a page, OCR it locally, and return Blocks in PDF coordinate space
    so OCR output flows through exactly the same downstream pipeline (reading
    order, paragraphs, headings, footnotes) as native text."""
    if not tesseract_available():
        return PageOCROutcome([], 0.0, 0, reliable=False, word_count=0)

    dpi = dpi or settings.ocr_dpi
    page_num = page_index + 1
    pix = page.get_pixmap(dpi=dpi)

    with tempfile.TemporaryDirectory() as tmp:
        result, rotation, rotated_w, rotated_h = _best_orientation(pix, Path(tmp), languages)

    if not result.words:
        return PageOCROutcome([], 0.0, rotation, reliable=False, word_count=0)

    # Image pixels -> PDF points. get_pixmap(dpi=) scales uniformly from the
    # page rect, so a single factor covers both axes.
    scale = 72.0 / dpi
    origin_x, origin_y = page.rect.x0, page.rect.y0

    blocks: list[Block] = []
    for block_index, lines in sorted(_group_lines_into_blocks(result.words).items()):
        spans: list[Span] = []
        line_texts: list[str] = []
        confidences: list[float] = []
        block_x0 = block_y0 = float("inf")
        block_x1 = block_y1 = float("-inf")

        for line_words in lines:
            parts: list[str] = []
            for word_index, word in enumerate(line_words):
                bbox = unrotate_bbox(word.bbox, rotation, rotated_w, rotated_h)
                pdf_bbox = (
                    origin_x + bbox[0] * scale,
                    origin_y + bbox[1] * scale,
                    origin_x + bbox[2] * scale,
                    origin_y + bbox[3] * scale,
                )
                text = word.text if word_index == 0 else f" {word.text}"
                parts.append(text)
                confidences.append(word.confidence)
                block_x0 = min(block_x0, pdf_bbox[0])
                block_y0 = min(block_y0, pdf_bbox[1])
                block_x1 = max(block_x1, pdf_bbox[2])
                block_y1 = max(block_y1, pdf_bbox[3])
                spans.append(
                    Span(
                        text=text,
                        bbox=pdf_bbox,
                        font="OCR",
                        font_size=round(pdf_bbox[3] - pdf_bbox[1], 2),
                        bold=False,
                        italic=False,
                        baseline=round(pdf_bbox[3], 2),
                        ocr_confidence=word.confidence,
                    )
                )
            if spans:
                spans[-1].line_break_after = True
            line_texts.append("".join(parts))

        if not spans:
            continue

        font_sizes = sorted(s.font_size for s in spans)
        blocks.append(
            Block(
                block_id=f"p{page_num}_ocr{block_index:03d}",
                page=page_num,
                page_width=page.rect.width,
                page_height=page.rect.height,
                bbox=(block_x0, block_y0, block_x1, block_y1),
                kind="text",
                text="\n".join(line_texts),
                spans=spans,
                font="OCR",
                font_size=font_sizes[len(font_sizes) // 2],
                baseline=spans[-1].baseline,
                line_id=f"p{page_num}_ocrl{block_index:03d}000",
                source="ocr",
                ocr_confidence=sum(confidences) / len(confidences),
                direction=TextDirection.LTR,
            )
        )

    mean_confidence = result.mean_confidence
    reliable = mean_confidence >= settings.ocr_min_region_confidence and bool(blocks)
    if not reliable:
        logger.info(
            "page %d OCR mean confidence %.1f below %.1f; preserving page as an image instead",
            page_num,
            mean_confidence,
            settings.ocr_min_region_confidence,
        )

    return PageOCROutcome(
        blocks=blocks,
        mean_confidence=mean_confidence,
        rotation=rotation,
        reliable=reliable,
        word_count=len(result.words),
    )
