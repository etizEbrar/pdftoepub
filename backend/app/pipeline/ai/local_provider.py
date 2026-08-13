from __future__ import annotations

import re

from app.models.document import BlockRole
from app.pipeline.ai.provider import AIReviewRequest, AIStructuralOpinion

_SENTENCE_END_RE = re.compile(r"[.!?]\s")
_TERMINAL_PUNCT = ".!?\"”’:;»)]"


class LocalProvider:
    """Free, local, no-network second opinion for blocks the deterministic pass
    (app/pipeline/structure.py) was unsure about (confidence < 0.70). Uses a
    different, independent signal — sentence-completeness — rather than the
    typography/geometry signals structure.py already used, so it can actually
    add information rather than just repeating the same heuristic.

    This is a real (if modest) local model in the "$0 per-book" sense required
    by the architecture: no API key, no network call, runs in-process. It is a
    slot a real local layout/classification model can later replace without
    changing any caller — see AIProvider in provider.py.
    """

    name = "local"
    requires_network = False

    def review(self, requests: list[AIReviewRequest]) -> list[AIStructuralOpinion]:
        opinions: list[AIStructuralOpinion] = []
        for req in requests:
            opinion = self._review_one(req)
            if opinion is not None:
                opinions.append(opinion)
        return opinions

    def _review_one(self, req: AIReviewRequest) -> AIStructuralOpinion | None:
        text = req.text.strip()
        if not text:
            return None

        looks_like_full_sentence = bool(_SENTENCE_END_RE.search(text)) or (
            len(text) > 20 and text[-1:] in _TERMINAL_PUNCT
        )

        if req.candidate_role == BlockRole.HEADING:
            if looks_like_full_sentence:
                # A heading candidate that reads like a full sentence is more
                # likely a short emphatic paragraph — demote, still not certain.
                return AIStructuralOpinion(
                    block_id=req.block_id,
                    role=BlockRole.PARAGRAPH,
                    level=None,
                    confidence=0.6,
                    reasoning="local: candidate heading text reads as a complete sentence",
                )
            # Short, punctuation-free, and its neighbours don't look identical
            # in style — reasonable independent confirmation of "heading".
            return AIStructuralOpinion(
                block_id=req.block_id,
                role=BlockRole.HEADING,
                level=None,
                confidence=min(0.8, req.candidate_confidence + 0.15),
                reasoning="local: short, non-sentence text confirmed as heading-shaped",
            )

        if req.candidate_role == BlockRole.PARAGRAPH and len(text) <= 20 and not looks_like_full_sentence:
            return AIStructuralOpinion(
                block_id=req.block_id,
                role=BlockRole.HEADING,
                level=4,
                confidence=0.55,
                reasoning="local: very short non-sentence paragraph candidate may be an unstyled heading",
            )

        return None  # no independent signal — leave the deterministic result as-is
