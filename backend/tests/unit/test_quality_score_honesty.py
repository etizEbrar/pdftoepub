"""The headline score must not contradict the engine's own findings.

A real 168-page book converted with eight dangling reference markers and
eighty-six passages the repairer refused to touch, and reported 100.0/100 with
needs_review=True at the same time. The score was computed before the review
findings existed and never revised.
"""

from __future__ import annotations

from app.pipeline.quality import (
    _NEEDS_REVIEW_CEILING,
    _apply_review_penalties,
)


class _Build:
    def __init__(self, unmatched=0, footnotes=0, endnotes=0, fn_linked=0, en_linked=0):
        self.unmatched_marker_count = unmatched
        self.footnote_count = footnotes
        self.endnote_count = endnotes
        self.footnote_linked_count = fn_linked
        self.endnote_linked_count = en_linked


class _Analysis:
    def __init__(self, pages):
        self.page_count = pages


class _Doc:
    def __init__(self, pages):
        self.analysis = _Analysis(pages)


def test_a_flagged_conversion_cannot_report_a_perfect_score():
    score = _apply_review_penalties(
        100.0, build=_Build(), document=_Doc(168),
        suspicious_passages=0, needs_review=True,
    )
    assert score <= _NEEDS_REVIEW_CEILING
    assert score < 100.0, "a conversion flagged for review reported as flawless"


def test_a_clean_conversion_keeps_its_score():
    score = _apply_review_penalties(
        99.4, build=_Build(footnotes=3, fn_linked=3), document=_Doc(12),
        suspicious_passages=0, needs_review=False,
    )
    assert score == 99.4


def test_dangling_markers_reduce_the_score():
    clean = _apply_review_penalties(
        100.0, build=_Build(), document=_Doc(168),
        suspicious_passages=0, needs_review=False,
    )
    dangling = _apply_review_penalties(
        100.0, build=_Build(unmatched=8), document=_Doc(168),
        suspicious_passages=0, needs_review=False,
    )
    assert dangling < clean


def test_unlinked_notes_reduce_the_score():
    linked = _apply_review_penalties(
        100.0, build=_Build(footnotes=10, fn_linked=10), document=_Doc(100),
        suspicious_passages=0, needs_review=False,
    )
    unlinked = _apply_review_penalties(
        100.0, build=_Build(footnotes=10, fn_linked=2), document=_Doc(100),
        suspicious_passages=0, needs_review=False,
    )
    assert unlinked < linked


def test_penalties_scale_with_the_length_of_the_book():
    """Ten dangling markers matter more in a pamphlet than in a long book."""
    short = _apply_review_penalties(
        100.0, build=_Build(unmatched=10), document=_Doc(10),
        suspicious_passages=0, needs_review=False,
    )
    long = _apply_review_penalties(
        100.0, build=_Build(unmatched=10), document=_Doc(500),
        suspicious_passages=0, needs_review=False,
    )
    assert short < long


def test_the_score_never_leaves_the_zero_to_hundred_range():
    worst = _apply_review_penalties(
        20.0, build=_Build(unmatched=999, footnotes=50, fn_linked=0),
        document=_Doc(5), suspicious_passages=999, needs_review=True,
    )
    assert 0.0 <= worst <= 100.0
