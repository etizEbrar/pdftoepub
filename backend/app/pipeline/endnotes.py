from __future__ import annotations

import re

from app.models.document import BlockRole, StructuralNode
from app.pipeline.footnotes import MARKER_OPEN, MARKER_SCAN_RE, strip_emphasis_sentinels

# Headings that open a collected notes section at the back of a book or chapter.
_ENDNOTE_HEADING_RE = re.compile(
    r"^\s*(notes?|endnotes?|notes to (chapter|pages?).*|chapter notes|"
    r"notlar|dipnotlar|sonnotlar|anmerkungen|notas)\s*$",
    re.IGNORECASE,
)
# "Chapter 3" / "Notes to Chapter 3" style subheadings that re-start numbering.
_CHAPTER_SCOPE_RE = re.compile(
    r"^\s*(?:notes\s+to\s+)?(?:chapter|bölüm|kapitel|chapitre)\s+([\dIVXLCivxlc]+)\b.*$",
    re.IGNORECASE,
)
_ENDNOTE_ENTRY_RE = re.compile(r"^\s*([\d]{1,4}|[*†‡§¶#]{1,3})[.)\]]?\s+(.+)$", re.DOTALL)

# Roles that can legitimately contain an inline reference marker.
_REFERENCE_BEARING_ROLES = {
    BlockRole.PARAGRAPH,
    BlockRole.QUOTE,
    BlockRole.LIST_ITEM,
    BlockRole.HEADING,
    BlockRole.VERSE,
}


def _is_endnote_section_heading(node: StructuralNode) -> bool:
    if node.role != BlockRole.HEADING:
        return False
    # Strip inline-emphasis sentinels: a bold "Notes" heading carries them and
    # would otherwise never match.
    return bool(_ENDNOTE_HEADING_RE.match(strip_emphasis_sentinels(node.text).strip()))


def find_endnote_sections(nodes: list[StructuralNode]) -> list[tuple[int, int]]:
    """Return [start, end) index ranges covering collected endnote sections.

    A section runs from a "Notes"-style heading until a heading of the same or
    higher rank that isn't itself part of the notes apparatus.
    """
    sections: list[tuple[int, int]] = []
    index = 0
    while index < len(nodes):
        node = nodes[index]
        if not _is_endnote_section_heading(node):
            index += 1
            continue

        section_level = node.level or 1
        end = len(nodes)
        for lookahead in range(index + 1, len(nodes)):
            candidate = nodes[lookahead]
            if candidate.role != BlockRole.HEADING:
                continue
            if _CHAPTER_SCOPE_RE.match(strip_emphasis_sentinels(candidate.text).strip()):
                continue  # chapter subheading *inside* the notes section
            if (candidate.level or 1) <= section_level:
                end = lookahead
                break
        sections.append((index, end))
        index = end
    return sections


def classify_endnote_sections(nodes: list[StructuralNode]) -> int:
    """Convert paragraphs inside endnote sections into ENDNOTE nodes, recording
    their number and owning chapter. Returns how many entries were identified.

    Only entries that genuinely begin with a marker are converted; running prose
    inside a notes section (an editor's preface to the notes, say) is left as a
    paragraph rather than being forced into a numbering scheme.
    """
    count = 0
    for start, end in find_endnote_sections(nodes):
        nodes[start].role = BlockRole.ENDNOTE_SECTION_HEADING
        current_chapter: str | None = None

        for node in nodes[start + 1 : end]:
            if node.role == BlockRole.HEADING:
                scope = _CHAPTER_SCOPE_RE.match(strip_emphasis_sentinels(node.text).strip())
                if scope:
                    current_chapter = scope.group(1)
                continue
            # A numbered notes list is classified as LIST_ITEM upstream — which
            # is structurally exactly right — so it must be accepted here too.
            if node.role not in (BlockRole.PARAGRAPH, BlockRole.FOOTNOTE, BlockRole.LIST_ITEM):
                continue

            match = _ENDNOTE_ENTRY_RE.match(node.text)
            if not match:
                continue
            node.role = BlockRole.ENDNOTE
            node.endnote_number = match.group(1)
            node.endnote_chapter = current_chapter
            node.text = match.group(2).strip()
            count += 1

    return count


def _chapter_of(node: StructuralNode, chapter_by_node: dict[str, str]) -> str | None:
    return chapter_by_node.get(node.node_id)


def build_chapter_index(nodes: list[StructuralNode]) -> dict[str, str]:
    """Map each node to the ordinal of the top-level chapter containing it, so
    endnote numbering that restarts per chapter resolves to the right note."""
    chapter_by_node: dict[str, str] = {}
    chapter_ordinal = 0
    top_level = min(
        (n.level for n in nodes if n.role == BlockRole.HEADING and n.level), default=1
    )
    for node in nodes:
        if node.role == BlockRole.HEADING and (node.level or 99) == top_level:
            chapter_ordinal += 1
        if chapter_ordinal:
            chapter_by_node[node.node_id] = str(chapter_ordinal)
    return chapter_by_node


def link_endnote_references(nodes: list[StructuralNode]) -> int:
    """Connect inline markers to ENDNOTE bodies and register return navigation.

    Runs *after* footnote linking, so any marker already resolved to a
    same-page footnote is gone by now and the two systems can't collide.
    Markers with no matching endnote stay plain superscripts rather than
    becoming broken links.
    """
    endnotes = [n for n in nodes if n.role == BlockRole.ENDNOTE and n.endnote_number]
    if not endnotes:
        return 0

    by_chapter: dict[str | None, dict[str, StructuralNode]] = {}
    for note in endnotes:
        by_chapter.setdefault(note.endnote_chapter, {}).setdefault(note.endnote_number, note)

    chapter_by_node = build_chapter_index(nodes)
    uses_chapter_scoping = len([k for k in by_chapter if k is not None]) > 0

    linked = 0
    counter = 0

    for node in nodes:
        if node.role not in _REFERENCE_BEARING_ROLES or MARKER_OPEN not in node.text:
            continue

        node_chapter = _chapter_of(node, chapter_by_node)

        def _replace(match: re.Match) -> str:
            nonlocal linked, counter
            marker = match.group(1)
            target = None
            if uses_chapter_scoping and node_chapter is not None:
                target = by_chapter.get(node_chapter, {}).get(marker)
            if target is None:
                target = by_chapter.get(None, {}).get(marker)
            if target is None and not uses_chapter_scoping:
                for scope in by_chapter.values():
                    if marker in scope:
                        target = scope[marker]
                        break
            if target is None:
                return f"{{{{SUP:{marker}}}}}"

            counter += 1
            ref_id = f"enref_{target.node_id}_{counter}"
            node.footnote_targets.append(target.node_id)
            target.footnote_backrefs.append(ref_id)
            linked += 1
            return f"{{{{NOTEREF:{target.node_id}:{ref_id}:{marker}}}}}"

        node.text = MARKER_SCAN_RE.sub(_replace, node.text)

    return linked
