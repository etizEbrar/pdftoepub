from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.models.document import BlockRole


@dataclass(frozen=True)
class AIReviewRequest:
    """One ambiguous block sent for optional review. Deliberately carries only
    the specific block's own text/crop plus a little surrounding context —
    never the whole document (spec: cost control rules, never send every page)."""

    block_id: str
    text: str
    candidate_role: BlockRole
    candidate_confidence: float
    context_before: str = ""
    context_after: str = ""


@dataclass(frozen=True)
class AIStructuralOpinion:
    """The ONLY thing an AI provider is allowed to return: metadata attached to
    an existing block. There is deliberately no field here that can carry
    replacement body text — the AI layer cannot introduce content into the
    document model, only classify what's already been extracted from the PDF.
    """

    block_id: str
    role: BlockRole
    level: int | None
    confidence: float
    reasoning: str = ""


class AIProvider(Protocol):
    """Provider-independent structural-review interface (spec section 32).

    Implementations must never be required for a normal conversion: the whole
    pipeline runs, and produces a valid EPUB, with provider "none" and no
    network calls at all.
    """

    name: str
    requires_network: bool

    def review(self, requests: list[AIReviewRequest]) -> list[AIStructuralOpinion]:
        """Return one opinion per request it could form an opinion on. May
        return fewer than len(requests) — callers must keep the deterministic
        result for anything not covered."""
        ...


def get_provider(name: str, *, anthropic_api_key: str | None = None) -> AIProvider:
    """Resolve the configured provider name to an instance. Falls back to the
    free, local, no-network provider whenever a cloud provider is selected but
    unusable — a normal conversion must never hard-fail on a missing API key.
    """
    from app.core.logging import get_logger
    from app.pipeline.ai.local_provider import LocalProvider
    from app.pipeline.ai.none_provider import NoneProvider

    logger = get_logger(__name__)
    name = (name or "none").lower()

    if name == "none":
        return NoneProvider()
    if name == "local":
        return LocalProvider()
    if name == "anthropic":
        if not anthropic_api_key:
            logger.warning("AI_PROVIDER=anthropic but no ANTHROPIC_API_KEY configured; using local provider")
            return LocalProvider()
        from app.pipeline.ai.anthropic_provider import AnthropicProvider

        return AnthropicProvider(api_key=anthropic_api_key)
    if name in ("openai", "google"):
        logger.warning("AI_PROVIDER=%s is not implemented in this build; using local provider", name)
        return LocalProvider()

    logger.warning("unknown AI_PROVIDER=%s; using none", name)
    return NoneProvider()
