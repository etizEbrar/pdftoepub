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

# The same technique for inline typography. Emphasis belongs to a *run of
# spans*, not to a whole block, so carrying it as node-level flags loses every
# italicised phrase inside an otherwise roman paragraph. These pass through
# hyphenation repair and paragraph merging as ordinary characters and become
# <strong>/<em> in the renderer.
BOLD_OPEN = ""
BOLD_CLOSE = ""
ITALIC_OPEN = ""
ITALIC_CLOSE = ""
EMPHASIS_SENTINELS = (BOLD_OPEN, BOLD_CLOSE, ITALIC_OPEN, ITALIC_CLOSE)

_MARKER_TEXT_RE = re.compile(r"^[\d*†‡§¶#]{1,3}$")
MARKER_SCAN_RE = re.compile(f"{MARKER_OPEN}(.*?){MARKER_CLOSE}")
_FOOTNOTE_PREFIX_RE = re.compile(r"^\s*([\d*†‡§¶#]{1,3})[.\)]?\s+(.*)$", re.DOTALL)

_SUPERSCRIPT_SIZE_RATIO = 0.75

# A reference marker that OCR glued onto the end of the preceding word:
# "Mystical shit!1", "o meşhur hareketleri2". Scanned books lose the
# superscript flag and the size difference, so the digit survives only as a
# suffix. Requires at least three letters before it so that "No. 8" or a year
# cannot match, and the digits must not run on into a longer number.
_GLUED_MARKER_RE = re.compile(r"(?<=[^\W\d_]{3})([!?.,;:»\"'\)]?)(\d{1,2})(?=[\s­]|$)")

# A superscript marker sitting alone after a word, separated by a space.
_DETACHED_MARKER_RE = re.compile(r"(?<=[^\W\d_]{3}[.!?»\"'\)]) (\d{1,2})(?=[\s­]|$)")


def _is_reference_candidate(span, body_size: float) -> bool:
    if not span.text.strip():
        return False
    if not _MARKER_TEXT_RE.match(span.text.strip()):
        return False
    if span.is_superscript:
        return True
    return bool(body_size) and span.font_size <= body_size * _SUPERSCRIPT_SIZE_RATIO


def collect_note_numbers_by_page(
    blocks: list[Block], body_size: float
) -> dict[int, set[str]]:
    """Numbers of footnote bodies present on each page.

    This is the evidence gate for glued-marker detection: a digit welded to a
    word only becomes a reference when a note with that number actually exists
    nearby. Without it, every "1966" or "No. 8" in the prose would turn into a
    link to nothing.
    """
    by_page: dict[int, set[str]] = {}
    for block in blocks:
        if block.kind != "text" or not block.text.strip():
            continue
        if not _looks_like_note_body_block(block, body_size):
            continue
        match = _FOOTNOTE_PREFIX_RE.match(block.text.strip())
        if match:
            by_page.setdefault(block.page, set()).add(match.group(1))
    return by_page


def _looks_like_note_body_block(block: Block, body_size: float) -> bool:
    """Geometry test for a footnote body: small type low on the page."""
    if not block.font_size or not body_size:
        return False
    return (
        block.font_size < body_size * 0.92
        and block.bbox[1] > block.page_height * 0.66
    )


def mark_reference_candidates(
    blocks: list[Block],
    body_size: float,
    note_numbers_by_page: dict[int, set[str]] | None = None,
) -> None:
    """Rebuild each text block's `.text` from its spans, wrapping anything that
    looks like a footnote reference marker in sentinel delimiters.

    Two detectors run. The first is span-level (superscript flag or noticeably
    smaller type), which is what a born-digital PDF provides. The second
    recovers markers that OCR welded onto the preceding word, and fires only
    when a footnote body carrying that exact number sits on the same page or
    the next — so a marker is never invented where no note exists.
    """
    note_numbers_by_page = note_numbers_by_page or {}

    for block in blocks:
        if block.kind != "text" or not block.spans:
            continue

        # A note body opens with its own number, which is set in the same small
        # type as the note. Wrapping that as a reference would make the note
        # point at itself and destroy the number the linker matches on, so note
        # bodies are left untouched entirely.
        if _looks_like_note_body_block(block, body_size):
            continue

        text = _rebuild_block_text(block, body_size)

        # Glued markers only where a matching note body is actually present.
        available = note_numbers_by_page.get(block.page, set()) | note_numbers_by_page.get(
            block.page + 1, set()
        )
        if available:
            text = _wrap_glued_markers(text, available)

        block.text = text


def strip_emphasis_sentinels(text: str) -> str:
    """Remove inline-emphasis sentinels, for callers that pattern-match text."""
    for sentinel in EMPHASIS_SENTINELS:
        text = text.replace(sentinel, "")
    return text


def _has_mixed_emphasis(block: Block) -> bool:
    styles = {(s.bold, s.italic) for s in block.spans if s.text.strip()}
    return len(styles) > 1


def _rebuild_block_text(block: Block, body_size: float) -> str:
    """Rebuild a block's text from its spans, marking reference candidates and
    emphasis runs.

    Emphasis is emitted per *run* of consecutive same-styled spans rather than
    per span, so an italic phrase spanning several spans becomes one <em>
    instead of a string of adjacent ones.

    Sentinels are only planted when a block actually mixes styles. A uniformly
    styled block is already described by the node's own bold/italic flags, and
    marking it up here would inject invisible characters into text that later
    stages pattern-match on — which silently broke endnote-section detection.
    """
    emit_emphasis = _has_mixed_emphasis(block)
    pieces: list[str] = []
    open_bold = open_italic = False

    def close_styles() -> None:
        nonlocal open_bold, open_italic
        if open_italic:
            pieces.append(ITALIC_CLOSE)
            open_italic = False
        if open_bold:
            pieces.append(BOLD_CLOSE)
            open_bold = False

    for span in block.spans:
        is_marker = _is_reference_candidate(span, body_size)
        # A marker carries no emphasis of its own; it becomes a link.
        want_bold = emit_emphasis and span.bold and not is_marker
        want_italic = emit_emphasis and span.italic and not is_marker

        if open_italic and not want_italic:
            pieces.append(ITALIC_CLOSE)
            open_italic = False
        if open_bold and not want_bold:
            pieces.append(BOLD_CLOSE)
            open_bold = False
        if want_bold and not open_bold:
            pieces.append(BOLD_OPEN)
            open_bold = True
        if want_italic and not open_italic:
            pieces.append(ITALIC_OPEN)
            open_italic = True

        if is_marker:
            pieces.append(f"{MARKER_OPEN}{span.text}{MARKER_CLOSE}")
        else:
            pieces.append(span.text)

        if span.line_break_after:
            # Styles never straddle a line break, so readers can't be left with
            # an unbalanced run if the lines are later regrouped.
            close_styles()
            pieces.append("\n")

    close_styles()
    return "".join(pieces).strip("\n")


def _wrap_glued_markers(text: str, available_numbers: set[str]) -> str:
    """Wrap digits welded to a word when a note with that number exists."""

    def replace_glued(match: re.Match) -> str:
        punctuation, digits = match.group(1), match.group(2)
        if digits not in available_numbers:
            return match.group(0)
        return f"{punctuation}{MARKER_OPEN}{digits}{MARKER_CLOSE}"

    def replace_detached(match: re.Match) -> str:
        digits = match.group(1)
        if digits not in available_numbers:
            return match.group(0)
        return f"{MARKER_OPEN}{digits}{MARKER_CLOSE}"

    text = _GLUED_MARKER_RE.sub(replace_glued, text)
    return _DETACHED_MARKER_RE.sub(replace_detached, text)


_MULTILINE_ROLES = {
    BlockRole.FOOTNOTE,
    BlockRole.ENDNOTE,
    BlockRole.QUOTE,
    BlockRole.LIST_ITEM,
    BlockRole.HEADING,
    BlockRole.CAPTION,
}


def _flatten_remaining_multiline_text(nodes: list[StructuralNode]) -> None:
    """PARAGRAPH nodes get hyphenation-aware line joining via
    paragraphs.reconstruct_paragraphs; every other multi-line role (a footnote
    body, a quote, a list item, a wrapped heading) still carries its raw
    block-internal "\\n"s and needs the same repair before rendering."""
    for node in nodes:
        if node.role in _MULTILINE_ROLES and "\n" in node.text:
            node.text = join_lines_with_hyphenation_repair(node.text.split("\n"))


def link_references(
    nodes: list[StructuralNode], leave_unmatched: bool = False
) -> tuple[list[StructuralNode], int]:
    """Match sentinel-wrapped reference markers in body text to FOOTNOTE-role
    nodes on the same (or immediately following) page, per spec sections 18-19.

    Returns the updated node list (footnote nodes get their marker text peeled
    off into `footnote_number`; content nodes get their sentinels replaced with
    `{{NOTEREF:<footnote_node_id>:<ref_id>}}` placeholders for the EPUB builder)
    and the count of successfully linked references.

    `leave_unmatched=True` keeps unresolved markers wrapped in their sentinels
    so a later pass — endnote linking — still gets a chance to claim them. The
    orchestrator uses that; callers who run footnote linking alone keep the
    default and get plain superscripts immediately.
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
                if leave_unmatched:
                    return match.group(0)  # keep the sentinel for endnote linking
                # No matching footnote body found — render as plain superscript
                # text rather than a broken link (zero-hallucination fallback).
                return f"{{{{SUP:{marker}}}}}"
            ref_counter += 1
            ref_id = f"fnref_{target.node_id}_{ref_counter}"
            node.footnote_targets.append(target.node_id)
            target.footnote_backrefs.append(ref_id)
            linked += 1
            return f"{{{{NOTEREF:{target.node_id}:{ref_id}:{marker}}}}}"

        node.text = MARKER_SCAN_RE.sub(_replace, node.text)

    if not leave_unmatched:
        _flatten_remaining_multiline_text(nodes)
    return nodes, linked


def finalize_unmatched_markers(nodes: list[StructuralNode]) -> int:
    """Turn any reference markers still unclaimed after footnote *and* endnote
    linking into plain superscripts, then repair multi-line text.

    This is the zero-hallucination endpoint: a marker whose note we never found
    is shown as it appeared in the source rather than linked to a guess.
    """
    unmatched = 0

    def _replace(match: re.Match) -> str:
        nonlocal unmatched
        unmatched += 1
        return f"{{{{SUP:{match.group(1)}}}}}"

    for node in nodes:
        if MARKER_OPEN in node.text:
            node.text = MARKER_SCAN_RE.sub(_replace, node.text)
        if node.verse_lines:
            node.verse_lines = [MARKER_SCAN_RE.sub(_replace, line) for line in node.verse_lines]

    _flatten_remaining_multiline_text(nodes)
    return unmatched
