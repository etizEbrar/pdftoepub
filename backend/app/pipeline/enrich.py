from __future__ import annotations

from pathlib import Path

import fitz

from app.core.config import settings
from app.core.logging import get_logger
from app.models.document import Block, BlockRole, DocumentModel, StructuralNode
from app.pipeline import formulas as formulas_module
from app.pipeline import tables as tables_module
from app.pipeline.rasterize import rasterize_region

logger = get_logger(__name__)


def _register_fallback_image(
    document: DocumentModel,
    page: fitz.Page,
    bbox: tuple[float, float, float, float],
    images_dir: Path,
    ref: str,
) -> str | None:
    region = rasterize_region(page, bbox, images_dir, ref)
    if region is None:
        return None
    document.images[region.ref] = {
        "ref": region.ref,
        "path": str(region.path),
        "ext": "png",
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

    for node in nodes:
        owning = next(
            (covered_to_table[bid] for bid in node.source_block_ids if bid in covered_to_table),
            None,
        )
        if owning is None:
            result.append(node)
            continue

        table_key = id(owning)
        if table_key in emitted:
            continue  # this table already emitted; drop the duplicate source text

        emitted.add(table_key)
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

    nodes[:] = result
    return semantic, fallback


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

    for node in nodes:
        if node.role != BlockRole.PARAGRAPH or len(node.source_block_ids) != 1:
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
        ref = _register_fallback_image(
            document, page, block.bbox, images_dir, f"formula_{block.block_id}"
        )
        if ref is None:
            continue
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

    return mathml_count, fallback_count


def preserve_page_as_image(
    document: DocumentModel,
    page: fitz.Page,
    page_number: int,
    images_dir: Path,
    reason: str,
) -> StructuralNode | None:
    """Whole-page fallback for a scanned page OCR couldn't read confidently."""
    ref = _register_fallback_image(
        document, page, tuple(page.rect), images_dir, f"page_{page_number}_fallback"
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
