from __future__ import annotations

import json

from app.core.logging import get_logger
from app.models.document import BlockRole
from app.pipeline.ai.provider import AIReviewRequest, AIStructuralOpinion

logger = get_logger(__name__)

_BATCH_SIZE = 8
_MAX_TEXT_CHARS = 400  # only the ambiguous block + a little context, never full pages
_VALID_ROLES = {r.value for r in BlockRole}

_SYSTEM_PROMPT = (
    "You classify short fragments of already-extracted book text by structural role. "
    "You are NOT an editor: never rewrite, correct, translate, complete, or summarize any text. "
    "Respond with a JSON array only. Each element: "
    '{"block_id": string, "role": one of ' + json.dumps(sorted(_VALID_ROLES)) + ", "
    '"level": integer 1-4 or null, "confidence": number 0-1}. '
    "Nothing else — no prose, no markdown fences, no extra keys."
)


def _chunks(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


class AnthropicProvider:
    """Optional, off-by-default cloud provider. Only ever receives the specific
    ambiguous block(s) plus a little surrounding context — never the full book
    or every page (spec cost-control rules) — and is only ever consulted for
    blocks the deterministic pass scored below the confidence threshold.
    """

    name = "anthropic"
    requires_network = True

    def __init__(self, api_key: str, model: str = "claude-haiku-4-5-20251001"):
        import anthropic

        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def review(self, requests: list[AIReviewRequest]) -> list[AIStructuralOpinion]:
        opinions: list[AIStructuralOpinion] = []
        for batch in _chunks(requests, _BATCH_SIZE):
            try:
                opinions.extend(self._review_batch(batch))
            except Exception:
                # An AI provider failure must never break a conversion — the
                # deterministic result for this batch simply stands.
                logger.exception("anthropic review batch failed; falling back to deterministic result")
        return opinions

    def _review_batch(self, batch: list[AIReviewRequest]) -> list[AIStructuralOpinion]:
        payload = [
            {
                "block_id": r.block_id,
                "candidate_role": r.candidate_role.value,
                "candidate_confidence": r.candidate_confidence,
                "context_before": r.context_before[:_MAX_TEXT_CHARS],
                "text": r.text[:_MAX_TEXT_CHARS],
                "context_after": r.context_after[:_MAX_TEXT_CHARS],
            }
            for r in batch
        ]
        response = self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": json.dumps(payload)}],
        )
        raw_text = "".join(block.text for block in response.content if getattr(block, "type", None) == "text")
        return self._parse(raw_text)

    def _parse(self, raw_text: str) -> list[AIStructuralOpinion]:
        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError:
            logger.warning("anthropic response was not valid JSON; discarding")
            return []

        opinions: list[AIStructuralOpinion] = []
        for item in data if isinstance(data, list) else []:
            try:
                role = item["role"]
                if role not in _VALID_ROLES:
                    continue
                opinions.append(
                    AIStructuralOpinion(
                        block_id=str(item["block_id"]),
                        role=BlockRole(role),
                        level=item.get("level"),
                        confidence=max(0.0, min(1.0, float(item.get("confidence", 0.5)))),
                        reasoning="anthropic",
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        return opinions
