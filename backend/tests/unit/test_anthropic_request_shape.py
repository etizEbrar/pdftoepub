"""What actually crosses the wire to Anthropic.

The privacy policy makes specific promises about this: the uncertain fragment
and the lines either side of it, each capped at a few hundred characters, and
never the PDF, a whole page, the complete document or any identifier. Those
promises are published, so they are held here by tests rather than by prose.

No network call is made. The client is replaced with a recorder, which is the
only way to assert on a payload without an API key.
"""

from __future__ import annotations

import json

import pytest

from app.models.document import BlockRole
from app.pipeline.ai.provider import AIReviewRequest


class _RecordingMessages:
    def __init__(self, reply: str, fail: bool = False):
        self.reply = reply
        self.fail = fail
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("network is down")

        class _Block:
            type = "text"
            text = self.reply

        class _Response:
            content = [_Block()]

        return _Response()


class _RecordingClient:
    def __init__(self, reply: str = "[]", fail: bool = False):
        self.messages = _RecordingMessages(reply, fail)


def _provider(reply: str = "[]", fail: bool = False):
    from app.pipeline.ai.anthropic_provider import AnthropicProvider

    p = AnthropicProvider.__new__(AnthropicProvider)
    p._client = _RecordingClient(reply, fail)
    p._model = "claude-haiku-4-5-20251001"
    return p


def _request(n: int = 1, text: str = "BÖLÜM 4", before: str = "", after: str = ""):
    return [
        AIReviewRequest(
            block_id=f"b{i}",
            text=text,
            candidate_role=BlockRole.PARAGRAPH,
            candidate_confidence=0.55,
            context_before=before,
            context_after=after,
        )
        for i in range(n)
    ]


class TestOnlyTheFragmentLeaves:
    def test_the_payload_carries_the_fragment_and_nothing_larger(self):
        p = _provider()
        p.review(_request(1, text="BÖLÜM 4", before="…önceki satır", after="sonraki satır…"))

        sent = json.loads(p._client.messages.calls[0]["messages"][0]["content"])
        assert len(sent) == 1
        assert set(sent[0]) == {
            "block_id", "candidate_role", "candidate_confidence",
            "context_before", "text", "context_after",
        }, f"unexpected fields on the wire: {sorted(sent[0])}"

    def test_a_long_fragment_is_truncated_before_it_is_sent(self):
        """A whole page pasted into one block must not become a whole page sent."""
        from app.pipeline.ai.anthropic_provider import _MAX_TEXT_CHARS

        page = "x" * 20_000
        p = _provider()
        p.review(_request(1, text=page, before=page, after=page))

        sent = json.loads(p._client.messages.calls[0]["messages"][0]["content"])[0]
        for field in ("text", "context_before", "context_after"):
            assert len(sent[field]) <= _MAX_TEXT_CHARS, f"{field} was not capped"

    def test_no_identifier_filename_or_path_is_sent(self):
        p = _provider()
        p.review(_request(3))
        body = p._client.messages.calls[0]["messages"][0]["content"]
        for leak in ("@", "/Users/", ".pdf", "job_id", "upload", "device", "ip"):
            assert leak not in body, f"{leak!r} reached the request body"

    def test_requests_are_batched_rather_than_sent_one_by_one(self):
        from app.pipeline.ai.anthropic_provider import _BATCH_SIZE

        p = _provider()
        p.review(_request(_BATCH_SIZE * 2 + 1))
        assert len(p._client.messages.calls) == 3
        first = json.loads(p._client.messages.calls[0]["messages"][0]["content"])
        assert len(first) == _BATCH_SIZE


class TestTheModelIsNotAskedToEdit:
    def test_the_system_prompt_forbids_rewriting(self):
        p = _provider()
        p.review(_request(1))
        system = p._client.messages.calls[0]["system"].lower()
        for forbidden in ("rewrite", "correct", "translate", "complete", "summarize"):
            assert forbidden in system, f"the prompt does not forbid {forbidden}"
        assert "not an editor" in system

    def test_the_configured_model_is_the_one_called(self):
        p = _provider()
        p.review(_request(1))
        assert p._client.messages.calls[0]["model"] == "claude-haiku-4-5-20251001"


class TestFailureIsSurvivable:
    def test_a_network_failure_yields_no_opinions_rather_than_raising(self):
        """A conversion must finish on the deterministic result."""
        p = _provider(fail=True)
        assert p.review(_request(4)) == []

    def test_a_non_json_reply_is_discarded(self):
        p = _provider(reply="Sure! Here is the answer: heading.")
        assert p.review(_request(2)) == []

    def test_an_invented_role_is_ignored(self):
        p = _provider(reply=json.dumps([
            {"block_id": "b0", "role": "chapter_title_supreme", "level": 1, "confidence": 0.9}
        ]))
        assert p.review(_request(1)) == []

    def test_a_well_formed_reply_is_accepted(self):
        p = _provider(reply=json.dumps([
            {"block_id": "b0", "role": "heading", "level": 2, "confidence": 0.88}
        ]))
        opinions = p.review(_request(1))
        assert len(opinions) == 1
        assert opinions[0].role is BlockRole.HEADING
        assert opinions[0].level == 2
