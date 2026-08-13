from __future__ import annotations

import re

from app.models.document import Block, BlockRole, StructuralNode
from app.pipeline.hyphenation import join_lines_with_hyphenation_repair

# Private-use-area sentinels used to carry candidate footnote markers through
# hyphenation repair and paragraph merging as ordinary characters, so the EPUB
# builder can later turn them into real <a epub:type="noteref"> anchors once
# they've been matched against an actual footnote body (see link_references).
MARKER_OPEN = ""
MARKER_CLOSE = ""

_MARKER_TEXT_RE = re.compile(r"^[\d*†‡§¶#]{1,3}$")
_MARKER_SCAN_RE = re.compile(f"{MARKER_OPEN}(.*?){MARKER_CLOSE}")
_FOOTNOTE_PREFIX_RE = re.compile(r"^\s*([\d*†‡§¶#]{1,3})[.\)]?\s+(.*)$", re.DOTALL)

_SUPERSCRIPT_SIZE_RATIO = 0.75


def _is_reference_candidate(span, body_size: float) -> bool:
    if not span.text.strip():
        return False
    if not _MARKER_TEXT_RE.match(span.text.strip()):
        return False
    if span.is_superscript:
        return True
    return bool(body_size) and span.font_size <= body_size * _SUPERSCRIPT_SIZE_RATIO


def mark_reference_candidates(blocks: list[Block], body_size: float) -> None:
    """Rebuild each text block's `.text` from its spans, wrapping spans that look
    like superscript footnote markers (spec section 18: font size, baseline
    offset, and short numeric/symbol content) in sentinel delimiters."""
    for block in blocks:
        if block.kind != "text" or not block.spans:
            continue
        pieces: list[str] = []
        for span in block.spans:
            if _is_reference_candidate(span, body_size):
                pieces.append(f"{MARKER_OPEN}{span.text}{MARKER_CLOSE}")
            else:
                pieces.append(span.text)
            if span.line_break_after:
                pieces.append("\n")
        block.text = "".join(pieces).strip("\n")


_MULTILINE_ROLES = {BlockRole.FOOTNOTE, BlockRole.QUOTE, BlockRole.LIST_ITEM, BlockRole.HEADING}


def _flatten_remaining_multiline_text(nodes: list[StructuralNode]) -> None:
    """PARAGRAPH nodes get hyphenation-aware line joining via
    paragraphs.reconstruct_paragraphs; every other multi-line role (a footnote
    body, a quote, a list item, a wrapped heading) still carries its raw
    block-internal "\\n"s and needs the same repair before rendering."""
    for node in nodes:
        if node.role in _MULTILINE_ROLES and "\n" in node.text:
            node.text = join_lines_with_hyphenation_repair(node.text.split("\n"))


def link_references(nodes: list[StructuralNode]) -> tuple[list[StructuralNode], int]:
    """Match sentinel-wrapped reference markers in body text to FOOTNOTE-role
    nodes on the same (or immediately following) page, per spec sections 18-19.

    Returns the updated node list (footnote nodes get their marker text peeled
    off into `footnote_number`; content nodes get their sentinels replaced with
    `{{NOTEREF:<footnote_node_id>:<ref_id>}}` placeholders for the EPUB builder)
    and the count of successfully linked references.
    """
    footnotes_by_page: dict[int, dict[str, StructuralNode]] = {}
    for node in nodes:
        if node.role != BlockRole.FOOTNOTE:
            continue
        m = _FOOTNOTE_PREFIX_RE.match(node.text)
        if m:
            node.footnote_number = m.group(1)
            node.text = m.group(2).strip()
        else:
            node.footnote_number = None
        if node.footnote_number and node.page is not None:
            footnotes_by_page.setdefault(node.page, {})[node.footnote_number] = node

    linked = 0
    ref_counter = 0
    skip_roles = {BlockRole.FOOTNOTE, BlockRole.IMAGE, BlockRole.HEADER, BlockRole.FOOTER, BlockRole.PAGE_NUMBER}

    for node in nodes:
        if node.role in skip_roles or MARKER_OPEN not in node.text:
            continue

        def _replace(match: re.Match) -> str:
            nonlocal linked, ref_counter
            marker = match.group(1)
            candidates_pages = [node.page, (node.page or 0) + 1] if node.page is not None else []
            target = None
            for p in candidates_pages:
                target = footnotes_by_page.get(p, {}).get(marker)
                if target:
                    break
            if target is None:
                # No matching footnote body found — render as plain superscript
                # text rather than a broken link (zero-hallucination fallback).
                return f"{{{{SUP:{marker}}}}}"
            ref_counter += 1
            ref_id = f"fnref_{target.node_id}_{ref_counter}"
            node.footnote_targets.append(target.node_id)
            target.footnote_backrefs.append(ref_id)
            linked += 1
            return f"{{{{NOTEREF:{target.node_id}:{ref_id}:{marker}}}}}"

        node.text = _MARKER_SCAN_RE.sub(_replace, node.text)

    _flatten_remaining_multiline_text(nodes)
    return nodes, linked
