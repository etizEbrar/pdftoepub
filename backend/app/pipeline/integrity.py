from __future__ import annotations

from dataclasses import dataclass, field

from app.models.document import BlockRole, DocumentModel

# Page furniture is removed on purpose, so its words are excluded from the
# expected total rather than counted as loss.
_FURNITURE_ROLES = {BlockRole.HEADER, BlockRole.FOOTER, BlockRole.PAGE_NUMBER}

# Roles whose text is genuinely carried into the EPUB as text.
#
# The builder counts delivered words from this same set: if the two disagree, a
# role counted as expected but not as delivered looks exactly like lost content.
TEXT_BEARING_ROLES = {
    BlockRole.PARAGRAPH,
    BlockRole.HEADING,
    BlockRole.ENDNOTE_SECTION_HEADING,
    BlockRole.QUOTE,
    BlockRole.LIST_ITEM,
    BlockRole.FOOTNOTE,
    BlockRole.ENDNOTE,
    BlockRole.VERSE,
    BlockRole.CAPTION,
}

# Roles that preserve their source content as something other than flowing text
# (a rendered image, a table grid, a scene divider drawn as <hr/>). Their words
# leave the text stream legitimately.
_PRESERVED_NON_TEXT_ROLES = {
    BlockRole.IMAGE_FALLBACK,
    BlockRole.TABLE,
    BlockRole.FORMULA,
    BlockRole.THEMATIC_BREAK,
}

# Below this share of expected words surviving, the conversion is flagged for
# review rather than reported as a clean success.
SUSPICIOUS_LOSS_RATIO = 0.90


@dataclass
class IntegrityResult:
    source_word_count: int
    epub_word_count: int
    ratio: float
    native_word_count: int = 0
    ocr_word_count: int = 0
    furniture_word_count: int = 0
    preserved_as_image_word_count: int = 0
    counts_by_role: dict[str, int] = field(default_factory=dict)
    unaccounted_block_ids: list[str] = field(default_factory=list)
    suspicious: bool = False
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "source_word_count": self.source_word_count,
            "epub_word_count": self.epub_word_count,
            "ratio": self.ratio,
            "native_word_count": self.native_word_count,
            "ocr_word_count": self.ocr_word_count,
            "furniture_word_count": self.furniture_word_count,
            "preserved_as_image_word_count": self.preserved_as_image_word_count,
            "counts_by_role": self.counts_by_role,
            "unaccounted_block_count": len(self.unaccounted_block_ids),
            "suspicious": self.suspicious,
            "notes": self.notes,
        }


def compute_integrity(document: DocumentModel, epub_word_count: int) -> IntegrityResult:
    """Account for every source block: rendered as text, deliberately removed as
    page furniture, or preserved as an image/table.

    A block that belongs to none of those categories has silently vanished, and
    that is reported rather than ignored (spec section 8: never silently discard
    content).
    """
    native_words = sum(
        len(b.text.split()) for b in document.blocks if b.kind == "text" and b.source == "native"
    )
    ocr_words = sum(
        len(b.text.split()) for b in document.blocks if b.kind == "text" and b.source == "ocr"
    )
    source_total = native_words + ocr_words

    furniture_words = sum(
        len(n.text.split()) for n in document.nodes if n.role in _FURNITURE_ROLES
    )

    counts_by_role: dict[str, int] = {}
    for node in document.nodes:
        counts_by_role[node.role.value] = counts_by_role.get(node.role.value, 0) + 1

    # Which source blocks made it into some node?
    accounted: set[str] = set()
    preserved_image_words = 0
    for node in document.nodes:
        if node.role in TEXT_BEARING_ROLES or node.role in _FURNITURE_ROLES:
            accounted.update(node.source_block_ids)
        elif node.role in _PRESERVED_NON_TEXT_ROLES:
            accounted.update(node.source_block_ids)
            preserved_image_words += sum(
                len(b.text.split())
                for b in document.blocks
                if b.block_id in node.source_block_ids
            )
        elif node.role == BlockRole.IMAGE:
            accounted.update(node.source_block_ids)

    unaccounted = [
        b.block_id
        for b in document.blocks
        if b.kind == "text" and b.text.strip() and b.block_id not in accounted
    ]

    expected = max(0, source_total - furniture_words - preserved_image_words)
    ratio = 1.0 if expected == 0 else min(epub_word_count / expected, 1.0)

    notes: list[str] = []
    if unaccounted:
        notes.append(
            f"{len(unaccounted)} source text block(s) did not reach the EPUB in any form"
        )
    if ratio < SUSPICIOUS_LOSS_RATIO:
        notes.append(
            f"only {ratio * 100:.1f}% of expected words reached the EPUB"
        )
    if document.warnings:
        notes.extend(document.warnings[:5])

    return IntegrityResult(
        source_word_count=expected,
        epub_word_count=epub_word_count,
        ratio=ratio,
        native_word_count=native_words,
        ocr_word_count=ocr_words,
        furniture_word_count=furniture_words,
        preserved_as_image_word_count=preserved_image_words,
        counts_by_role=counts_by_role,
        unaccounted_block_ids=unaccounted,
        suspicious=bool(unaccounted) or ratio < SUSPICIOUS_LOSS_RATIO,
        notes=notes,
    )
