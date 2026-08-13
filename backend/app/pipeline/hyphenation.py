from __future__ import annotations

_HYPHEN_CHARS = "-‐‑"  # ASCII hyphen + Unicode hyphen/non-breaking hyphen.
# Deliberately excludes en dash (–) and em dash (—): those are never
# line-wrap artifacts and must never be touched.


def join_lines_with_hyphenation_repair(lines: list[str]) -> str:
    """Join a paragraph's wrapped source lines into one string, undoing hyphenation
    that PDF line-wrapping introduced (spec section 14) while leaving genuine
    hyphenated words alone.

    Heuristic: a trailing hyphen is treated as a line-wrap artifact only when both
    the character before it and the first character of the next line are lowercase
    letters — the pattern produced by justified/wrapped body text. This is a known
    trade-off: a real compound word that happens to break exactly at its own hyphen
    (e.g. "self-\\nesteem") will also be merged. Dictionary-based disambiguation is
    out of scope for this heuristic; when in doubt this still favors the far more
    common case (wrapped single words) over the rarer one.
    """
    if not lines:
        return ""
    result = lines[0]
    for raw_next in lines[1:]:
        next_line = raw_next.lstrip()
        if not next_line:
            continue
        if (
            result
            and result[-1] in _HYPHEN_CHARS
            and len(result) >= 2
            and result[-2].isalpha()
            and next_line[0].isalpha()
            and next_line[0].islower()
        ):
            result = result[:-1] + next_line
            continue
        if result and not result.endswith((" ", "\n")):
            result += " "
        result += next_line
    return result
