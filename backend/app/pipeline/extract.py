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


# Two fragments belong to the same visual line when their vertical extents
# overlap by at least this share of the shorter one.
_SAME_LINE_OVERLAP = 0.55
# A horizontal gap wider than this many times the font size is not word spacing.
# Justified setting stretches spaces a long way, but a column gutter or the gap
# between table cells is wider still, and gluing across one would destroy the
# reading order rather than repair it.
_MAX_WORD_GAP_RATIO = 2.5
# Below this, the fragments are touching and need no space inserted.
_MIN_SPACE_GAP_RATIO = 0.12


def _vertically_overlaps(a: tuple, b: tuple) -> bool:
    top = max(a[1], b[1])
    bottom = min(a[3], b[3])
    overlap = bottom - top
    if overlap <= 0:
        return False
    shorter = min(a[3] - a[1], b[3] - b[1])
    return shorter > 0 and overlap / shorter >= _SAME_LINE_OVERLAP


def _group_fragments_into_visual_lines(raw_lines: list[dict]) -> list[list[dict]]:
    """Regroup MuPDF "lines" that are really fragments of one visual line.

    Justified text stretches the spaces between words, and MuPDF reports each
    stretched run as its own line. A page of justified Turkish prose then
    arrives as one word per line, which downstream reads as ragged short lines
    — i.e. as poetry — and shreds chapter titles across several headings.

    Fragments are merged only within a single MuPDF block, so this cannot join
    text across a column boundary: separate columns are separate blocks.
    """
    groups: list[list[dict]] = []
    for line in raw_lines:
        bbox = line.get("bbox")
        if not bbox:
            groups.append([line])
            continue
        for group in groups:
            if _vertically_overlaps(group[0].get("bbox", (0, 0, 0, 0)), bbox):
                group.append(line)
                break
        else:
            groups.append([line])

    ordered: list[list[dict]] = []
    for group in groups:
        # Right-to-left runs are laid out with the first word furthest right.
        rtl = any(line.get("dir", (1, 0))[0] < 0 for line in group)
        group.sort(key=lambda ln: ln.get("bbox", (0,))[0], reverse=rtl)

        # Sharing a baseline is not enough. Two columns of a page sit on the
        # same baseline with a gutter between them, and MuPDF will happily put
        # both in one block. A gap far too wide to be word spacing ends the
        # visual line rather than being bridged.
        run: list[dict] = []
        for fragment in group:
            if run:
                previous = run[-1].get("bbox", (0, 0, 0, 0))
                current = fragment.get("bbox", (0, 0, 0, 0))
                gap = (current[0] - previous[2]) if not rtl else (previous[0] - current[2])
                spans = fragment.get("spans") or [{}]
                reference = max(1.0, float(spans[0].get("size", 0.0) or 10.0))
                if gap > reference * _MAX_WORD_GAP_RATIO:
                    ordered.append(run)
                    run = []
            run.append(fragment)
        if run:
            ordered.append(run)

    ordered.sort(
        key=lambda g: (
            min(ln.get("bbox", (0, 0))[1] for ln in g),
            min(ln.get("bbox", (0,))[0] for ln in g),
        )
    )
    return ordered


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

        for fragment_group in _group_fragments_into_visual_lines(
            raw_block.get("lines", [])
        ):
            line_parts: list[str] = []
            previous_bbox: tuple | None = None
            for raw_line in fragment_group:
                # Restore the space that justification turned into a gap. Only
                # when the fragments do not already carry their own spacing,
                # and never across a gap too wide to be word spacing.
                if previous_bbox is not None and line_parts:
                    frag_bbox = raw_line.get("bbox", (0, 0, 0, 0))
                    gap = frag_bbox[0] - previous_bbox[2]
                    reference = max(
                        1.0,
                        float(raw_line.get("spans", [{}])[0].get("size", 0.0) or 10.0),
                    )
                    joined = "".join(line_parts)
                    frag_text = "".join(
                        sp.get("text", "") for sp in raw_line.get("spans", [])
                    )
                    if (
                        gap > reference * _MIN_SPACE_GAP_RATIO
                        and gap <= reference * _MAX_WORD_GAP_RATIO
                        and joined
                        and not joined[-1].isspace()
                        and frag_text
                        and not frag_text[0].isspace()
                    ):
                        line_parts.append(" ")
                previous_bbox = raw_line.get("bbox", (0, 0, 0, 0))
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
