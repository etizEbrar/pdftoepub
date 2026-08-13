from __future__ import annotations

import re
from collections.abc import Callable
from xml.sax.saxutils import escape as xml_escape

_PLACEHOLDER_RE = re.compile(r"\{\{(NOTEREF|SUP):([^}]*)\}\}")


def footnote_anchor_id(footnote_node_id: str) -> str:
    return f"fn_{footnote_node_id}"


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
        parts.append(xml_escape(text[last : m.start()]))
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
    parts.append(xml_escape(text[last:]))
    return "".join(parts)
