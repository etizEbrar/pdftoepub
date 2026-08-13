from app.pipeline.hyphenation import join_lines_with_hyphenation_repair


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
