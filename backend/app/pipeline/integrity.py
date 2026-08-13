from __future__ import annotations

from dataclasses import dataclass

from app.models.document import BlockRole, DocumentModel

_FURNITURE_ROLES = {BlockRole.HEADER, BlockRole.FOOTER, BlockRole.PAGE_NUMBER}


@dataclass
class IntegrityResult:
    source_word_count: int
    epub_word_count: int
    ratio: float


def compute_integrity(document: DocumentModel, epub_word_count: int) -> IntegrityResult:
    """Compare source vs. EPUB word counts, explicitly allowing for intentionally
    removed page furniture (spec section 36) rather than penalizing its removal.
    """
    source_total = sum(len(b.text.split()) for b in document.blocks if b.kind == "text")
    furniture_words = sum(len(n.text.split()) for n in document.nodes if n.role in _FURNITURE_ROLES)
    expected = max(0, source_total - furniture_words)

    ratio = 1.0 if expected == 0 else min(epub_word_count / expected, 1.0)
    return IntegrityResult(source_word_count=expected, epub_word_count=epub_word_count, ratio=ratio)
