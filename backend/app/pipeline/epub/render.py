from __future__ import annotations

import re
from collections.abc import Callable
from xml.sax.saxutils import escape as xml_escape

from app.pipeline import footnotes

_PLACEHOLDER_RE = re.compile(r"\{\{(NOTEREF|SUP):([^}]*)\}\}")

# Inline emphasis sentinels planted while rebuilding block text from spans.
_EMPHASIS_TAGS = {
    footnotes.BOLD_OPEN: "<strong>",
    footnotes.BOLD_CLOSE: "</strong>",
    footnotes.ITALIC_OPEN: "<em>",
    footnotes.ITALIC_CLOSE: "</em>",
}
_EMPHASIS_RE = re.compile("|".join(re.escape(s) for s in _EMPHASIS_TAGS))
# A soft hyphen that survived line joining sits mid-word and means nothing once
# the text reflows.
_SOFT_HYPHEN = "\u00ad"  # invisible; written escaped so it survives editing


def footnote_anchor_id(footnote_node_id: str) -> str:
    return f"fn_{footnote_node_id}"


def _escape_with_emphasis(text: str) -> str:
    """XML-escape a run while turning emphasis sentinels into real tags.

    Escaping happens per segment *between* sentinels, so the tags we emit are
    never themselves escaped and no author text can smuggle markup through.
    """
    text = text.replace(_SOFT_HYPHEN, "")
    if not any(sentinel in text for sentinel in _EMPHASIS_TAGS):
        return xml_escape(text)

    out: list[str] = []
    last = 0
    open_tags: list[str] = []
    for match in _EMPHASIS_RE.finditer(text):
        out.append(xml_escape(text[last : match.start()]))
        tag = _EMPHASIS_TAGS[match.group(0)]
        if tag.startswith("</"):
            # Only close what is actually open, so a stray sentinel can't emit
            # unbalanced markup and break XHTML validity.
            if open_tags and open_tags[-1] == tag[2:-1]:
                open_tags.pop()
                out.append(tag)
        else:
            open_tags.append(tag[1:-1])
            out.append(tag)
        last = match.end()
    out.append(xml_escape(text[last:]))
    while open_tags:
        out.append(f"</{open_tags.pop()}>")
    return "".join(out)


def render_inline(text: str, resolve_note_href: Callable[[str], str]) -> str:
    """Escape plain text for XHTML while expanding the NOTEREF/SUP placeholders
    left by footnotes.py into real inline markup.

    `resolve_note_href(footnote_node_id)` returns the href (possibly chapter-file-
    qualified, e.g. "chapter-002.xhtml#fn_...") for a footnote that may live in a
    different chapter file than the reference itself.
    """
    parts: list[str] = []
    last = 0
    for m in _PLACEHOLDER_RE.finditer(text):
        parts.append(_escape_with_emphasis(text[last : m.start()]))
        kind = m.group(1)
        args = m.group(2).split(":")
        if kind == "NOTEREF":
            footnote_node_id, ref_id, marker = args
            href = resolve_note_href(footnote_node_id)
            parts.append(
                f'<a epub:type="noteref" class="noteref" href="{xml_escape(href)}" '
                f'id="{xml_escape(ref_id)}">{xml_escape(marker)}</a>'
            )
        elif kind == "SUP":
            (marker,) = args
            parts.append(f"<sup>{xml_escape(marker)}</sup>")
        last = m.end()
    parts.append(_escape_with_emphasis(text[last:]))
    return "".join(parts)
