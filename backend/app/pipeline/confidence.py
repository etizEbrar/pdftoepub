from __future__ import annotations

from app.core.config import settings
from app.models.document import BlockRole, StructuralNode
from app.pipeline.ai.provider import AIProvider, AIReviewRequest, AIStructuralOpinion

_NOT_REVIEWABLE = {BlockRole.IMAGE, BlockRole.HEADER, BlockRole.FOOTER, BlockRole.PAGE_NUMBER}
_CONTEXT_CHARS = 200


def collect_review_candidates(nodes: list[StructuralNode]) -> list[AIReviewRequest]:
    """Every structural decision below the confidence floor becomes one review
    request — and only those (spec: confidence < 0.70 is eligible for AI;
    never send the full book or every page)."""
    requests: list[AIReviewRequest] = []
    for i, node in enumerate(nodes):
        if node.role in _NOT_REVIEWABLE or node.confidence >= settings.ai_confidence_threshold:
            continue
        before = nodes[i - 1].text[-_CONTEXT_CHARS:] if i > 0 else ""
        after = nodes[i + 1].text[:_CONTEXT_CHARS] if i < len(nodes) - 1 else ""
        requests.append(
            AIReviewRequest(
                block_id=node.node_id,
                text=node.text,
                candidate_role=node.role,
                candidate_confidence=node.confidence,
                context_before=before,
                context_after=after,
            )
        )
    return requests


def apply_ai_opinions(nodes: list[StructuralNode], opinions: list[AIStructuralOpinion]) -> int:
    by_id = {n.node_id: n for n in nodes}
    applied = 0
    for opinion in opinions:
        node = by_id.get(opinion.block_id)
        if node is None or opinion.confidence <= node.confidence:
            continue  # never let a less-confident opinion override the deterministic result
        node.role = opinion.role
        if opinion.level is not None:
            node.level = opinion.level
        node.confidence = opinion.confidence
        applied += 1
    return applied


def run_ai_review(nodes: list[StructuralNode], provider: AIProvider) -> tuple[int, int]:
    """Returns (blocks_sent_for_review, blocks_changed_by_review)."""
    requests = collect_review_candidates(nodes)
    if not requests:
        return 0, 0
    opinions = provider.review(requests)
    applied = apply_ai_opinions(nodes, opinions)
    return len(requests), applied
