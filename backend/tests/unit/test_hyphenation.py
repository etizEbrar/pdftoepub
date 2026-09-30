from app.pipeline.hyphenation import (
    HyphenEvidence,
    join_lines_with_hyphenation_repair,
)


def test_repairs_wrapped_word_hyphenation():
    result = join_lines_with_hyphenation_repair(["uluslar-", "arası bir konu"])
    assert result == "uluslararası bir konu"


def test_preserves_en_dash():
    result = join_lines_with_hyphenation_repair(["pages 10", "–12 are relevant"])
    # en dash is not in the hyphen set, so no merge attempt happens on it
    assert "–" in result


def test_does_not_merge_across_uppercase_next_word_when_hyphen_is_not_wordwrap():
    # trailing hyphen after a non-letter should never trigger a merge
    result = join_lines_with_hyphenation_repair(["See page 12-", "Chapter Two begins"])
    assert result == "See page 12- Chapter Two begins"


def test_normal_line_wrap_gets_a_space():
    result = join_lines_with_hyphenation_repair(["This is a line", "that continues normally."])
    assert result == "This is a line that continues normally."


def test_empty_input():
    assert join_lines_with_hyphenation_repair([]) == ""


def test_single_line():
    assert join_lines_with_hyphenation_repair(["Just one line."]) == "Just one line."


class TestDocumentSpellingDecidesTheHyphen:
    """The book already says how it spells the words it breaks.

    Measured on a real 168-page volume: "flux-switching" was set intact six
    times and broken across a line three times, and the three broken ones came
    out "fluxswitching" — one term spelled two ways in one book. "cross-domain"
    and "de-manyetizasyon" lost their hyphens outright. Guessing is avoidable
    here: whichever spelling the document itself uses elsewhere is the answer,
    and no character is invented either way.
    """

    def test_a_compound_the_book_sets_intact_keeps_its_hyphen(self):
        evidence = HyphenEvidence(
            ["flux-switching motor ve flux-switching sargı", "akı anahtarlamalı"]
        )
        joined = join_lines_with_hyphenation_repair(["... flux-", "switching motoru"], evidence)
        assert "flux-switching motoru" in joined
        assert "fluxswitching" not in joined

    def test_a_word_the_book_sets_closed_is_closed(self):
        evidence = HyphenEvidence(["geliyorum dedi", "yarın geliyorum"])
        joined = join_lines_with_hyphenation_repair(["... ge-", "liyorum"], evidence)
        assert "geliyorum" in joined
        assert "ge-liyorum" not in joined

    def test_without_evidence_the_old_heuristic_still_applies(self):
        """A Turkish suffix broken at the margin still closes up."""
        joined = join_lines_with_hyphenation_repair(["... ge-", "liyorum"])
        assert "geliyorum" in joined

    def test_a_hyphen_is_never_left_followed_by_a_space(self):
        """Whatever is decided, "co- invocation" is wrong under every reading."""
        for ev in (None, HyphenEvidence(["co-invocation"]), HyphenEvidence(["coinvocation"])):
            joined = join_lines_with_hyphenation_repair(["... co-", "invocation for"], ev)
            assert "- " not in joined, joined


def test_runs_of_spaces_in_the_source_collapse_to_one():
    """A real book carried 28 double spaces mid-sentence.

    XHTML collapses them on render, so this changes nothing a reader sees; it
    keeps the markup honest and stops runs of spaces surviving inside an
    emphasis span. Only spaces are touched -- no word or mark is altered.
    """
    joined = join_lines_with_hyphenation_repair(["alınacaktır.  YZ’nin", "değeri  haline"])
    assert "alınacaktır. YZ’nin değeri haline" == joined
