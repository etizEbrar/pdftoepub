from __future__ import annotations

from app.pipeline.ai.provider import AIReviewRequest, AIStructuralOpinion


class NoneProvider:
    """The default. Never makes a network call, never forms an opinion — the
    deterministic pipeline result always stands. This is what "AI-optional"
    means in practice: this class is what runs for every conversion unless a
    user explicitly turns something else on."""

    name = "none"
    requires_network = False

    def review(self, requests: list[AIReviewRequest]) -> list[AIStructuralOpinion]:
        return []
