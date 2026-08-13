from app.models.document import BlockRole, StructuralNode
from app.pipeline.ai.local_provider import LocalProvider
from app.pipeline.ai.none_provider import NoneProvider
from app.pipeline.ai.provider import get_provider
from app.pipeline.confidence import collect_review_candidates, run_ai_review


def test_default_provider_is_none_and_never_used_by_config_default():
    from app.core.config import settings

    assert settings.ai_provider == "none"


def test_get_provider_none_makes_no_network_claim():
    provider = get_provider("none")
    assert provider.name == "none"
    assert provider.requires_network is False


def test_get_provider_falls_back_to_local_when_anthropic_key_missing():
    provider = get_provider("anthropic", anthropic_api_key=None)
    assert provider.name == "local"


def test_none_provider_returns_no_opinions_ever():
    provider = NoneProvider()
    high_ambiguity_request = collect_review_candidates(
        [StructuralNode(node_id="n1", role=BlockRole.PARAGRAPH, text="?", confidence=0.1)]
    )
    assert provider.review(high_ambiguity_request) == []


def test_high_confidence_nodes_are_never_sent_for_review():
    nodes = [StructuralNode(node_id="n1", role=BlockRole.HEADING, text="Chapter One", confidence=0.95)]
    requests = collect_review_candidates(nodes)
    assert requests == []


def test_low_confidence_nodes_are_sent_for_review():
    nodes = [StructuralNode(node_id="n1", role=BlockRole.HEADING, text="Ambiguous", confidence=0.5)]
    requests = collect_review_candidates(nodes)
    assert len(requests) == 1
    assert requests[0].block_id == "n1"


def test_run_ai_review_with_none_provider_is_a_true_no_op():
    nodes = [StructuralNode(node_id="n1", role=BlockRole.HEADING, text="Ambiguous", confidence=0.5)]
    reviewed, changed = run_ai_review(nodes, NoneProvider())
    assert reviewed == 1  # it was eligible
    assert changed == 0  # but nothing changed — no opinion was ever formed
    assert nodes[0].confidence == 0.5


def test_local_provider_never_calls_network_and_can_demote_sentence_like_heading():
    provider = LocalProvider()
    assert provider.requires_network is False
    nodes = [
        StructuralNode(
            node_id="n1",
            role=BlockRole.HEADING,
            text="This reads like a full sentence, not a title.",
            confidence=0.5,
        )
    ]
    reviewed, changed = run_ai_review(nodes, provider)
    assert reviewed == 1
    assert changed == 1
    assert nodes[0].role == BlockRole.PARAGRAPH


def test_ai_opinion_never_overrides_a_more_confident_deterministic_result():
    from app.pipeline.ai.provider import AIStructuralOpinion
    from app.pipeline.confidence import apply_ai_opinions

    node = StructuralNode(node_id="n1", role=BlockRole.PARAGRAPH, text="text", confidence=0.95)
    weak_opinion = AIStructuralOpinion(block_id="n1", role=BlockRole.HEADING, level=1, confidence=0.4)
    applied = apply_ai_opinions([node], [weak_opinion])
    assert applied == 0
    assert node.role == BlockRole.PARAGRAPH  # untouched
