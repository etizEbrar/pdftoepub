from __future__ import annotations

from app.models.document import Block


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
