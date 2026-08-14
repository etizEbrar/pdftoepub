from __future__ import annotations

from pathlib import Path

import fitz  # PyMuPDF

from app.models.document import Block, Span
from app.pipeline.bidi import visual_to_logical

# PyMuPDF span flag bitmasks (see PyMuPDF docs on TextPage.extractDICT).
_FLAG_SUPERSCRIPT = 1
_FLAG_ITALIC = 2
_FLAG_BOLD = 16


def _looks_bold(font_name: str, flags: int) -> bool:
    return bool(flags & _FLAG_BOLD) or "bold" in font_name.lower()


def _looks_italic(font_name: str, flags: int) -> bool:
    lname = font_name.lower()
    return bool(flags & _FLAG_ITALIC) or "italic" in lname or "oblique" in lname


def extract_page_blocks(page: fitz.Page, page_index: int) -> list[Block]:
    """Geometry-aware text extraction: one Block per PDF text block, each carrying
    the spans that make it up. Text and geometry stay bound together (per spec)."""
    raw = page.get_text("dict")
    blocks: list[Block] = []
    page_num = page_index + 1

    for bi, raw_block in enumerate(raw.get("blocks", [])):
        if raw_block.get("type") != 0:
            continue  # image blocks handled separately in images.py

        block_id = f"p{page_num}_b{bi:03d}"
        lines_text: list[str] = []
        all_spans: list[Span] = []
        block_bbox = raw_block.get("bbox", (0, 0, 0, 0))

        for raw_line in raw_block.get("lines", []):
            line_parts: list[str] = []
            for raw_span in raw_line.get("spans", []):
                text = raw_span.get("text", "")
                if text == "":
                    continue
                # MuPDF hands back right-to-left scripts in visual order;
                # XHTML needs logical order. See bidi.visual_to_logical.
                text = visual_to_logical(text)
                font_name = raw_span.get("font", "")
                flags = raw_span.get("flags", 0)
                origin = raw_span.get("origin", (0.0, 0.0))
                span = Span(
                    text=text,
                    bbox=tuple(raw_span.get("bbox", (0, 0, 0, 0))),
                    font=font_name,
                    font_size=round(float(raw_span.get("size", 0.0)), 2),
                    bold=_looks_bold(font_name, flags),
                    italic=_looks_italic(font_name, flags),
                    baseline=round(float(origin[1]), 2),
                    is_superscript=bool(flags & _FLAG_SUPERSCRIPT),
                )
                all_spans.append(span)
                line_parts.append(span.text)
            if line_parts:
                lines_text.append("".join(line_parts).rstrip())
                all_spans[-1].line_break_after = True

        text = "\n".join(lines_text)
        if not text.strip():
            continue

        dominant = _dominant_span(all_spans)
        blocks.append(
            Block(
                block_id=block_id,
                page=page_num,
                page_width=page.rect.width,
                page_height=page.rect.height,
                bbox=tuple(block_bbox),
                kind="text",
                text=text,
                spans=all_spans,
                font=dominant.font if dominant else None,
                font_size=dominant.font_size if dominant else None,
                bold=dominant.bold if dominant else False,
                italic=dominant.italic if dominant else False,
                baseline=all_spans[-1].baseline if all_spans else None,
                line_id=f"p{page_num}_l{bi:03d}000",
            )
        )

    return blocks


def _dominant_span(spans: list[Span]) -> Span | None:
    """The span whose text is longest — used to represent the block's "body" style,
    so a single superscript reference at the start doesn't skew font/size/weight."""
    if not spans:
        return None
    return max(spans, key=lambda s: len(s.text))


def extract_images(page: fitz.Page, page_index: int, images_dir: Path) -> list[dict]:
    """Extract raster images on the page as files, preserving their page position."""
    page_num = page_index + 1
    raw = page.get_text("dict")
    results: list[dict] = []
    for bi, raw_block in enumerate(raw.get("blocks", [])):
        if raw_block.get("type") != 1:
            continue
        image_bytes = raw_block.get("image")
        if not image_bytes:
            continue
        ext = raw_block.get("ext", "png")
        ref = f"p{page_num}_img{bi:03d}"
        out_path = images_dir / f"{ref}.{ext}"
        out_path.write_bytes(image_bytes)
        results.append(
            {
                "ref": ref,
                "path": str(out_path),
                "ext": ext,
                "page": page_num,
                "bbox": list(raw_block.get("bbox", (0, 0, 0, 0))),
            }
        )
    return results
