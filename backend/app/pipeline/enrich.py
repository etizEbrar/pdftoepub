from __future__ import annotations

import re
from pathlib import Path

import fitz

from app.core.config import settings
from app.core.logging import get_logger
from app.models.document import Block, BlockRole, DocumentModel, StructuralNode
from app.pipeline import formulas as formulas_module
from app.pipeline import tables as tables_module
from app.pipeline.footnotes import strip_all_sentinels
from app.pipeline.rasterize import rasterize_region

logger = get_logger(__name__)


def _register_fallback_image(
    document: DocumentModel,
    page: fitz.Page,
    bbox: tuple[float, float, float, float],
    images_dir: Path,
    ref: str,
    photo: bool = False,
) -> str | None:
    region = rasterize_region(page, bbox, images_dir, ref, photo=photo)
    if region is None:
        return None
    document.images[region.ref] = {
        "ref": region.ref,
        "path": str(region.path),
        "ext": region.path.suffix.lstrip("."),
        "page": region.page,
        "bbox": list(region.bbox),
        "is_fallback": True,
        "dpi": region.dpi,
    }
    return region.ref


def apply_tables(
    document: DocumentModel,
    nodes: list[StructuralNode],
    detected: list[tables_module.DetectedTable],
    pages: dict[int, fitz.Page],
    images_dir: Path,
) -> tuple[int, int]:
    """Replace the text nodes a table covers with one TABLE node.

    High-confidence tables become semantic XHTML; low-confidence ones become a
    high-resolution image of the real table, because a wrong table is worse
    than a picture of the right one.

    Returns (semantic_count, image_fallback_count).
    """
    if not detected:
        return 0, 0

    covered_to_table: dict[str, tables_module.DetectedTable] = {}
    for table in detected:
        for block_id in table.covered_block_ids:
            covered_to_table[block_id] = table

    semantic = fallback = 0
    emitted: set[int] = set()
    result: list[StructuralNode] = []

    # A table emits its caption inside <caption>, so a separate caption node
    # holding the same words puts the line on the page twice.
    table_captions = {
        " ".join(t.data.caption.split()) for t in detected if t.data.caption
    }

    # Source blocks whose text a table has absorbed into its own <caption>.
    # Recorded so the integrity account knows those words were delivered by the
    # table rather than lost: the caption block sits outside the table's covered
    # region, so nothing else would attribute it.
    caption_block_ids: dict[str, list[str]] = {}

    # The last semantic table emitted, while nothing but page furniture has
    # followed it: a table that carries on over the page break joins it.
    open_table: StructuralNode | None = None

    for node in nodes:
        owning = next(
            (covered_to_table[bid] for bid in node.source_block_ids if bid in covered_to_table),
            None,
        )
        if owning is None and node.role not in _FURNITURE_ROLES:
            open_table = None
        if owning is None:
            caption_text = " ".join(strip_all_sentinels(node.text).split())
            if node.role is BlockRole.CAPTION and caption_text in table_captions:
                # The table renders this line inside <caption>; keeping the
                # paragraph too would print it on the page twice.
                caption_block_ids.setdefault(caption_text, []).extend(
                    node.source_block_ids
                )
                continue
            result.append(node)
            continue

        table_key = id(owning)
        if table_key in emitted:
            continue  # this table already emitted; drop the duplicate source text

        emitted.add(table_key)
        if (
            open_table is not None
            and open_table.table is not None
            and owning.data.continues_from_previous_page
            and owning.data.cols == open_table.table.cols
            and owning.data.confidence >= settings.table_min_confidence
        ):
            _append_rows(open_table.table, owning.data)
            open_table.source_block_ids.extend(owning.covered_block_ids)
            continue

        table_node = StructuralNode(
            node_id=f"table_{owning.page}_{int(owning.bbox[1])}",
            role=BlockRole.TABLE,
            confidence=owning.data.confidence,
            source_block_ids=list(owning.covered_block_ids),
            page=owning.page,
            table=owning.data,
        )

        if owning.data.confidence >= settings.table_min_confidence:
            table_node.text = owning.data.caption or ""
            if owning.data.caption:
                absorbed = caption_block_ids.get(" ".join(owning.data.caption.split()))
                if absorbed:
                    table_node.source_block_ids.extend(absorbed)
            semantic += 1
        else:
            page = pages.get(owning.page)
            ref = (
                _register_fallback_image(
                    document, page, owning.bbox, images_dir, table_node.node_id
                )
                if page
                else None
            )
            if ref:
                table_node.role = BlockRole.IMAGE_FALLBACK
                table_node.image_ref = ref
                table_node.fallback_reason = (
                    f"table reconstruction confidence {owning.data.confidence:.2f} "
                    f"below {settings.table_min_confidence:.2f}"
                )
                table_node.alt_text = _table_alt_text(owning.data)
                fallback += 1
            else:
                # Rasterization failed — keep the source text rather than lose it.
                result.append(node)
                emitted.discard(table_key)
                continue

        result.append(table_node)
        open_table = table_node if table_node.role == BlockRole.TABLE else None

    nodes[:] = result
    return semantic, fallback


_FURNITURE_ROLES = (BlockRole.HEADER, BlockRole.FOOTER, BlockRole.PAGE_NUMBER)


def _append_rows(table, continuation) -> None:
    """Carry a table's rows on from the previous page into one table."""
    rows = sorted({c.row for c in continuation.cells})
    first = [c.text for c in sorted((c for c in continuation.cells if c.row == rows[0]), key=lambda c: c.col)]
    header = [c.text for c in sorted((c for c in table.cells if c.row == 0), key=lambda c: c.col)]
    # A header repeated at the top of the new page is not data.
    skip = rows[0] if table.has_header_row and first == header else None
    offset = table.rows
    added = 0
    for row in rows:
        if row == skip:
            continue
        for cell in (c for c in continuation.cells if c.row == row):
            cell.row = offset + added
            cell.is_header = False
            table.cells.append(cell)
        added += 1
    table.rows = offset + added


# "Şekil 2: ...", "Figure 3." -- a caption naming a figure, as opposed to a table.
_FIGURE_CAPTION_RE = re.compile(
    r"^\s*(?:şekil|sekil|resim|grafik|harita|diyagram|görsel|gorsel|figure|fig\.|chart|plate)\s*\d",
    re.IGNORECASE,
)
# A label inside a diagram is a few words on a line or two.
_MAX_LABEL_CHARS = 80
_MAX_LABEL_LINES = 3
_FIGURE_PART_ROLES = (BlockRole.IMAGE, BlockRole.TABLE, BlockRole.IMAGE_FALLBACK)
# Not CAPTION: another caption above this one belongs to the figure before it.
_LABEL_ROLES = (BlockRole.PARAGRAPH, BlockRole.QUOTE, BlockRole.HEADING, BlockRole.LIST_ITEM)
# Vector strokes that make a region a drawing rather than stray rules.
_MIN_DIAGRAM_DRAWINGS = 3
_REGION_PADDING_PT = 4.0


def _node_bbox(node: StructuralNode, blocks_by_id: dict[str, Block]):
    boxes = [blocks_by_id[b].bbox for b in node.source_block_ids if b in blocks_by_id]
    if not boxes:
        return None
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )


# Vector strokes nearer than this to one another belong to one drawing.
_DRAWING_JOIN_PT = 18.0
# A drawing ends this close above its caption.
_DRAWING_CAPTION_GAP_PT = 60.0


def _drawing_above(page, caption_box) -> tuple[float, float, float, float] | None:
    """The extent of the vector drawing standing just above a caption.

    Built upward from the strokes nearest the caption, taking in each stroke
    that reaches the drawing so far, so that a rule across the page above it
    or a table further up is not swallowed into the figure.
    """
    try:
        rects = [d["rect"] for d in page.get_drawings() if d.get("rect") is not None]
    except Exception:
        return None
    # Strokes that start above the caption; a chart's frame may reach down
    # behind it. An axis is a line, with no area, and still counts.
    rects = [
        r for r in rects
        if r.y0 < caption_box[1]
        and r.y1 <= caption_box[3] + 2
        and r.width < page.rect.width * 0.95
        and (r.width > 0 or r.height > 0)
    ]
    seed = [r for r in rects if caption_box[1] - r.y1 <= _DRAWING_CAPTION_GAP_PT]
    if len(seed) < _MIN_DIAGRAM_DRAWINGS:
        return None
    x0 = min(r.x0 for r in seed)
    y0 = min(r.y0 for r in seed)
    x1 = max(r.x1 for r in seed)
    y1 = max(r.y1 for r in seed)
    # Take in every stroke that reaches the drawing so far, in any direction:
    # a flowchart's boxes stand beside one another as well as above.
    pending = [r for r in rects if r not in seed]
    grew = True
    while grew:
        grew = False
        for r in list(pending):
            if (
                r.x1 >= x0 - _DRAWING_JOIN_PT
                and r.x0 <= x1 + _DRAWING_JOIN_PT
                and r.y1 >= y0 - _DRAWING_JOIN_PT
                and r.y0 <= y1 + _DRAWING_JOIN_PT
            ):
                x0, y0, x1, y1 = min(x0, r.x0), min(y0, r.y0), max(x1, r.x1), max(y1, r.y1)
                pending.remove(r)
                grew = True
    return (x0, y0, x1, y1)


def _inside(box, region, margin: float = 10.0) -> bool:
    cx = (box[0] + box[2]) / 2
    cy = (box[1] + box[3]) / 2
    return region[0] - margin <= cx <= region[2] + margin and region[1] - margin <= cy <= region[3] + margin


def _within_columns(box, region, margin: float = 10.0) -> bool:
    return box[0] >= region[0] - margin and box[2] <= region[2] + margin


def _is_label(node: StructuralNode) -> bool:
    text = " ".join(strip_all_sentinels(node.text).split())
    lines = [ln for ln in node.text.split("\n") if ln.strip()]
    return (
        node.role in _LABEL_ROLES
        and 0 < len(text) <= _MAX_LABEL_CHARS
        and len(lines) <= _MAX_LABEL_LINES
    )


def apply_composite_figures(
    document: DocumentModel,
    nodes: list[StructuralNode],
    blocks_by_id: dict[str, Block],
    pages,
    images_dir: Path,
) -> int:
    """Keep a diagram assembled from pieces as one picture of the figure.

    A flowchart is boxes and arrows drawn as vectors, small images and text
    labels laid over them. Read piece by piece it came out as a column of
    image fragments with the labels between them as quotations, in no order a
    reader could follow. Everything between the figure's caption and the
    text above it is the figure. Returns the number of figures kept whole.
    """
    kept = 0
    index = 0
    while index < len(nodes):
        caption = nodes[index]
        index += 1
        if caption.role != BlockRole.CAPTION or caption.page is None:
            continue
        if not _FIGURE_CAPTION_RE.match(strip_all_sentinels(caption.text)):
            continue
        caption_box = _node_bbox(caption, blocks_by_id)
        if caption_box is None:
            continue

        page = pages.get(caption.page)
        drawn = _drawing_above(page, caption_box) if page is not None else None

        # Walk back from the caption over the pieces of the figure, stopping
        # at the first thing that is part of the text.
        parts: list[int] = []
        cursor = index - 2
        while cursor >= 0:
            node = nodes[cursor]
            if node.page != caption.page:
                break
            if node.role in (BlockRole.HEADER, BlockRole.FOOTER, BlockRole.PAGE_NUMBER):
                cursor -= 1
                continue
            box = _node_bbox(node, blocks_by_id)
            if box is None or box[1] >= caption_box[1]:
                break
            if drawn is not None and node.role != BlockRole.CAPTION and _inside(box, drawn):
                # Anything set on the drawing is part of it, whatever it was
                # read as: a chart's axis values came out as a footnote and its
                # axis title as a heading, and stopped the walk halfway up.
                parts.append(cursor)
            elif drawn is not None and not _within_columns(box, drawn):
                # Beside the drawing's columns is the text again, however
                # short its line: "sonuçları Şekil 4'de verilmiştir." above a
                # chart was cut into the picture of it.
                break
            elif node.role in _FIGURE_PART_ROLES:
                parts.append(cursor)
            elif _is_label(node) and (
                node.role != BlockRole.HEADING
                or any(nodes[p].role in _FIGURE_PART_ROLES for p in parts)
            ):
                parts.append(cursor)
            else:
                break
            cursor -= 1
        if not parts:
            continue

        boxes = [b for b in (_node_bbox(nodes[p], blocks_by_id) for p in parts) if b]
        images = sum(1 for p in parts if nodes[p].role == BlockRole.IMAGE)
        labels = sum(1 for p in parts if nodes[p].role in _LABEL_ROLES)
        tables = sum(1 for p in parts if nodes[p].role in (BlockRole.TABLE, BlockRole.IMAGE_FALLBACK))
        top = min(b[1] for b in boxes)
        if page is None:
            continue
        drawings = []
        try:
            for drawing in page.get_drawings():
                rect = drawing.get("rect")
                if rect is not None and rect.y0 >= top - 1 and rect.y1 <= caption_box[1] + 1:
                    drawings.append(rect)
        except Exception:
            logger.warning("could not read drawings on page %d", caption.page)
        # One photograph with its caption is an ordinary figure already.
        composite = (
            images >= 2
            or (images >= 1 and labels >= 1)
            or (labels >= 2 and len(drawings) >= _MIN_DIAGRAM_DRAWINGS)
            or (tables >= 1 and (images >= 1 or len(drawings) >= _MIN_DIAGRAM_DRAWINGS))
        )
        if not composite:
            continue

        x0 = min([b[0] for b in boxes] + [r.x0 for r in drawings])
        y0 = min([b[1] for b in boxes] + [r.y0 for r in drawings])
        x1 = max([b[2] for b in boxes] + [r.x1 for r in drawings])
        y1 = max([b[3] for b in boxes] + [r.y1 for r in drawings])
        region = (
            max(0.0, x0 - _REGION_PADDING_PT),
            max(0.0, y0 - _REGION_PADDING_PT),
            min(page.rect.width, x1 + _REGION_PADDING_PT),
            min(caption_box[1], y1 + _REGION_PADDING_PT),
        )
        first = min(parts)
        ref = _register_fallback_image(
            document, page, region, images_dir, f"figure_{caption.page}_{int(region[1])}"
        )
        if ref is None:
            continue
        figure = StructuralNode(
            node_id=f"figure_{caption.page}_{int(region[1])}",
            role=BlockRole.IMAGE_FALLBACK,
            confidence=0.9,
            source_block_ids=[b for p in sorted(parts) for b in nodes[p].source_block_ids],
            page=caption.page,
            image_ref=ref,
            fallback_reason="figure assembled from drawings, images and labels",
            alt_text=" ".join(strip_all_sentinels(caption.text).split()),
        )
        for p in parts:
            if nodes[p].role == BlockRole.IMAGE and nodes[p].image_ref:
                # The pieces are inside the picture now; shipping them as well
                # would only add files nothing refers to.
                document.images.pop(nodes[p].image_ref, None)
        removed = set(parts)
        nodes[:] = [n for i, n in enumerate(nodes) if i not in removed or i == first]
        nodes[first] = figure
        index = next(i for i, n in enumerate(nodes) if n is caption) + 1
        kept += 1
    return kept


def _table_alt_text(data) -> str:
    caption = f"{data.caption}. " if data.caption else ""
    return f"{caption}Table of {data.rows} rows and {data.cols} columns, preserved as an image."


def apply_formulas(
    document: DocumentModel,
    nodes: list[StructuralNode],
    blocks_by_id: dict[str, Block],
    pages: dict[int, fitz.Page],
    images_dir: Path,
) -> tuple[int, int]:
    """Convert equation-like paragraphs into MathML nodes, or preserve them as
    images when semantic reconstruction isn't reliable.

    Returns (mathml_count, image_fallback_count).
    """
    mathml_count = fallback_count = 0

    # HEADING is included deliberately: a numbered display equation is centred,
    # set larger than body text and isolated, so structural scoring reasonably
    # reads it as a heading. The formula detector demands far more specific
    # evidence (math symbols, an equation number, a math font), so letting it
    # examine headings reclaims real equations without stealing real titles.
    considered = {BlockRole.PARAGRAPH, BlockRole.HEADING}
    absorbed: set[int] = set()

    for node in nodes:
        if id(node) in absorbed:
            continue
        if node.role not in considered or len(node.source_block_ids) != 1:
            continue
        block = blocks_by_id.get(node.source_block_ids[0])
        if block is None:
            continue

        candidate = formulas_module.detect_formula(block)
        if candidate is None:
            continue

        if candidate.mathml and candidate.confidence >= settings.formula_min_confidence:
            node.role = BlockRole.FORMULA
            node.mathml = candidate.mathml
            node.confidence = candidate.confidence
            node.text = candidate.text
            mathml_count += 1
            continue

        page = pages.get(node.page or 0)
        if page is None:
            continue
        fragments = _equation_fragments(node, block, nodes, blocks_by_id, absorbed)
        region = block.bbox
        for fragment_block in (blocks_by_id[f.source_block_ids[0]] for f in fragments):
            region = (
                min(region[0], fragment_block.bbox[0]),
                min(region[1], fragment_block.bbox[1]),
                max(region[2], fragment_block.bbox[2]),
                max(region[3], fragment_block.bbox[3]),
            )
        ref = _register_fallback_image(
            document, page, region, images_dir, f"formula_{block.block_id}"
        )
        if ref is None:
            continue
        for fragment in fragments:
            absorbed.add(id(fragment))
            node.source_block_ids.extend(fragment.source_block_ids)
        node.role = BlockRole.IMAGE_FALLBACK
        node.image_ref = ref
        node.confidence = candidate.confidence
        node.fallback_reason = (
            f"formula reconstruction confidence {candidate.confidence:.2f} "
            f"below {settings.formula_min_confidence:.2f}"
        )
        # The alt text quotes the source characters verbatim — it never
        # paraphrases or "explains" the mathematics.
        suffix = f" Equation {candidate.equation_number}." if candidate.equation_number else ""
        node.alt_text = f"Mathematical expression: {candidate.text}.{suffix}"
        fallback_count += 1

    if absorbed:
        nodes[:] = [n for n in nodes if id(n) not in absorbed]
    return mathml_count, fallback_count


# The pieces a typeset equation leaves beside its main line: "P =" to the
# left, the "1" of a fraction above it. Each is a few characters at most.
_MAX_FRAGMENT_CHARS = 8
_FRAGMENT_OVERLAP = 0.3


def _equation_fragments(
    node: StructuralNode,
    block: Block,
    nodes: list[StructuralNode],
    blocks_by_id: dict[str, Block],
    absorbed: set[int],
) -> list[StructuralNode]:
    """Short text blocks on the same line as an equation, which are part of it.

    MuPDF sets a fraction's numerator, and the left-hand side of an equation
    in its own block. Preserving only the block that tripped the detector
    left "1" and "P=" beside a picture of the rest.
    """
    fragments: list[StructuralNode] = []
    for other in nodes:
        if other is node or id(other) in absorbed or other.page != node.page:
            continue
        if other.role not in (BlockRole.PARAGRAPH, BlockRole.QUOTE, BlockRole.HEADING):
            continue
        if len(other.source_block_ids) != 1:
            continue
        other_block = blocks_by_id.get(other.source_block_ids[0])
        if other_block is None:
            continue
        if len("".join(strip_all_sentinels(other.text).split())) > _MAX_FRAGMENT_CHARS:
            continue
        top = max(block.bbox[1], other_block.bbox[1])
        bottom = min(block.bbox[3], other_block.bbox[3])
        shorter = min(block.bbox[3] - block.bbox[1], other_block.bbox[3] - other_block.bbox[1])
        if shorter > 0 and bottom - top >= shorter * _FRAGMENT_OVERLAP:
            fragments.append(other)
    return fragments


def preserve_page_as_image(
    document: DocumentModel,
    page: fitz.Page,
    page_number: int,
    images_dir: Path,
    reason: str,
) -> StructuralNode | None:
    """Whole-page fallback for a scanned page OCR couldn't read confidently."""
    ref = _register_fallback_image(
        document, page, tuple(page.rect), images_dir, f"page_{page_number}_fallback", photo=True
    )
    if ref is None:
        return None
    return StructuralNode(
        node_id=f"pagefallback_{page_number}",
        role=BlockRole.IMAGE_FALLBACK,
        confidence=0.0,
        page=page_number,
        image_ref=ref,
        fallback_reason=reason,
        alt_text=f"Page {page_number} of the source document, preserved as an image because it could not be read reliably.",
    )
