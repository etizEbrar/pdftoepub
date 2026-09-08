from __future__ import annotations

import re
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

from app.pipeline import footnotes as footnotes_module
from app.pipeline import headings as headings_module
from app.models.document import BlockRole, DocumentModel, StructuralNode, TableData, TextDirection
from app.pipeline.epub.css import DEFAULT_STYLESHEET
from app.pipeline.epub.render import footnote_anchor_id, render_inline
from app.pipeline.integrity import TEXT_BEARING_ROLES
from app.pipeline.structure import BULLET_RE, NUMBERED_RE

EXCLUDED_ROLES = {BlockRole.HEADER, BlockRole.FOOTER, BlockRole.PAGE_NUMBER}
_HEADING_SPLIT_ROLE = BlockRole.HEADING
# Roles that carry an endnote apparatus rather than body prose.
_NOTE_ROLES = {BlockRole.FOOTNOTE, BlockRole.ENDNOTE}


@dataclass
class Chapter:
    filename: str
    title: str
    nodes: list[StructuralNode] = field(default_factory=list)


@dataclass
class BuildResult:
    output_path: Path
    chapter_count: int
    heading_count: int
    footnote_count: int
    footnote_linked_count: int
    image_count: int
    list_item_count: int
    table_count: int
    word_count: int
    cover_image_ref: str | None
    endnote_count: int = 0
    endnote_linked_count: int = 0
    verse_count: int = 0
    formula_count: int = 0
    formula_fallback_count: int = 0
    image_fallback_count: int = 0
    unmatched_marker_count: int = 0
    rtl_block_count: int = 0


def slugify(text: str, fallback: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or fallback


_MIN_CHAPTERS_FOR_USEFUL_NAV = 2
# Beyond roughly this many pages, a single "chapter" is not a chapter — it is a
# whole book in one file. Used to reject a split level that technically produces
# two divisions but leaves the reader with no navigation.
_MAX_PAGES_PER_CHAPTER = 60


def _plain_title(text: str) -> str:
    """A heading reduced to what a reader should see in a title or the TOC."""
    cleaned = footnotes_module.strip_all_sentinels(text)
    return " ".join(cleaned.split())


def _division_headings(nodes: list[StructuralNode]) -> list[StructuralNode]:
    """Headings that explicitly name a division — "BÖLÜM 3", "CHAPTER 2"."""
    return [
        n
        for n in nodes
        if n.role == _HEADING_SPLIT_ROLE and headings_module.is_division_heading(n.text)
    ]


def _page_span(nodes: list[StructuralNode]) -> int:
    pages = [n.page for n in nodes if n.page]
    return (max(pages) - min(pages) + 1) if pages else 1


def _choose_split_level(nodes: list[StructuralNode]) -> int | None:
    """Pick the heading level to break chapters at.

    Not simply "level 1": a one-off cover or half-title often occupies the
    largest scale in a book, so splitting strictly on level 1 yields a single
    chapter containing the entire text. The shallowest level that actually
    produces several divisions is the one a reader would recognise as chapters.

    "Several" alone is not enough either. A title set across two lines counts as
    two level-1 headings, which satisfied the old rule and collapsed a 168-page
    book into two files with forty chapter headings buried inside them. A level
    only qualifies if the divisions it produces are chapter-sized.
    """
    counts: dict[int, int] = {}
    for node in nodes:
        if node.role == _HEADING_SPLIT_ROLE and node.level:
            counts[node.level] = counts.get(node.level, 0) + 1
    if not counts:
        return None

    total_pages = _page_span(nodes)
    cumulative = 0
    fallback: int | None = None
    for level in sorted(counts):
        cumulative += counts[level]
        if cumulative < _MIN_CHAPTERS_FOR_USEFUL_NAV:
            continue
        if fallback is None:
            fallback = level
        if total_pages / cumulative <= _MAX_PAGES_PER_CHAPTER:
            return level
    # Nothing gives chapter-sized divisions; the shallowest usable level is
    # still better than one file for the whole book.
    return fallback if fallback is not None else min(counts)


def split_into_chapters(nodes: list[StructuralNode]) -> list[Chapter]:
    """Split by detected document structure, not PDF pages (spec section 30).

    Uses the top-most heading level actually present as the chapter boundary:
    level 1 if any exist, else level 2, else the whole book is one chapter.
    """
    # A book that labels its own divisions has told us which typographic level
    # its chapters live at. Split on that level rather than on the labelled
    # headings alone: books mix styles, setting "BÖLÜM 2" on one chapter and
    # "3" above a title on the next, and splitting only on the labelled ones
    # buries every chapter set in the other style inside its predecessor.
    #
    # Headings numbered like "1.2." are excluded whatever their size — a dotted
    # number says the heading sits beneath something else.
    division_nodes = _division_headings(nodes)
    chapter_level: int | None = None
    if len(division_nodes) >= _MIN_CHAPTERS_FOR_USEFUL_NAV:
        levels = [n.level for n in division_nodes if n.level]
        if levels:
            chapter_level = max(set(levels), key=levels.count)
    split_level = _choose_split_level(nodes) if chapter_level is None else None

    chapters: list[Chapter] = []
    current: Chapter | None = None
    front_matter: list[StructuralNode] = []

    for node in nodes:
        # A collected notes section is a major division of the book and must be
        # reachable from the table of contents, so it opens a chapter of its own
        # regardless of the heading level its typography implied.
        if chapter_level is not None:
            opens_division = (
                node.role == _HEADING_SPLIT_ROLE
                and (node.level or 99) <= chapter_level
                and not headings_module.is_subsection_heading(node.text)
            )
        else:
            opens_division = (
                split_level is not None
                and node.role == _HEADING_SPLIT_ROLE
                and (node.level or 99) <= split_level
            )
        starts_chapter = node.role == BlockRole.ENDNOTE_SECTION_HEADING or opens_division
        if starts_chapter:
            if current is None and front_matter:
                chapters.append(Chapter(filename="", title="Front Matter", nodes=front_matter))
            # The sentinels that carry inline emphasis and note markers are
            # turned into real tags by the inline renderer, but a chapter title
            # goes straight into <title> and the navigation, which never pass
            # through it — so they reached the reader as invisible private-use
            # characters in the tab title and the table of contents.
            title = _plain_title(node.text) or f"Chapter {len(chapters) + 1}"
            current = Chapter(filename="", title=title, nodes=[node])
            chapters.append(current)
        elif current is not None:
            current.nodes.append(node)
        else:
            front_matter.append(node)

    if current is None:
        # No heading ever hit the split level — whole document is one chapter.
        chapters.append(Chapter(filename="", title="", nodes=front_matter))

    used_slugs: set[str] = set()
    for i, ch in enumerate(chapters, start=1):
        base = slugify(ch.title, f"chapter-{i}")
        slug = base
        n = 2
        while slug in used_slugs:
            slug = f"{base}-{n}"
            n += 1
        used_slugs.add(slug)
        ch.filename = f"chapter-{i:03d}-{slug}.xhtml"
        if not ch.title:
            ch.title = f"Chapter {i}"

    return chapters


def _list_marker_type(text: str) -> str:
    return "ol" if NUMBERED_RE.match(text) else "ul"


def _strip_marker(text: str) -> str:
    m = BULLET_RE.match(text) or NUMBERED_RE.match(text)
    return text[m.end() :] if m else text


def _build_node_chapter_map(chapters: list[Chapter]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for ch in chapters:
        for node in ch.nodes:
            mapping[node.node_id] = ch.filename
    return mapping


_NOTEREF_SCAN_RE = re.compile(r"\{\{NOTEREF:([^:}]*):([^:}]*):")


def _build_ref_chapter_map(chapters: list[Chapter]) -> dict[str, str]:
    """Map each reference anchor id to the chapter file that contains it.

    Endnotes are collected at the back of the book, so a note's back-link
    usually points into a *different* chapter file than the note itself. A bare
    "#fnref_..." would then dangle, which EPUBCheck rejects as an undefined
    fragment identifier — so back-links must be file-qualified.
    """
    mapping: dict[str, str] = {}
    for ch in chapters:
        for node in ch.nodes:
            haystacks = [node.text, *node.verse_lines]
            if node.table:
                haystacks.extend(cell.text for cell in node.table.cells)
            for haystack in haystacks:
                for match in _NOTEREF_SCAN_RE.finditer(haystack or ""):
                    mapping[match.group(2)] = ch.filename
    return mapping


def _dir_attribute(node: StructuralNode, base_direction: TextDirection) -> str:
    """Emit dir= only when a node departs from the book's base direction, so an
    Arabic book isn't littered with redundant dir="rtl" on every paragraph."""
    if node.direction == base_direction:
        return ""
    return f' dir="{node.direction.value}"'


def _render_table(node: StructuralNode, resolve_note_href) -> str:
    data: TableData | None = node.table
    if data is None:
        return ""

    by_row: dict[int, list] = {}
    for cell in data.cells:
        by_row.setdefault(cell.row, []).append(cell)

    def render_row(cells, tag: str) -> str:
        rendered = "".join(
            f"<{tag}>{render_inline(c.text, resolve_note_href)}</{tag}>"
            for c in sorted(cells, key=lambda c: c.col)
        )
        return f"<tr>{rendered}</tr>"

    rows_html: list[str] = []
    head_html = ""
    for row_index in sorted(by_row):
        cells = by_row[row_index]
        if data.has_header_row and row_index == 0:
            head_html = f"<thead>{render_row(cells, 'th')}</thead>"
        else:
            rows_html.append(render_row(cells, "td"))

    caption = (
        f"<caption>{render_inline(data.caption, resolve_note_href)}</caption>" if data.caption else ""
    )
    body = f"<tbody>{''.join(rows_html)}</tbody>" if rows_html else ""
    return f"<table>{caption}{head_html}{body}</table>"


def _render_verse(node: StructuralNode, resolve_note_href, dir_attr: str) -> str:
    """Poetry as semantic, reflowable markup.

    Indentation is expressed as a CSS class step rather than a PDF coordinate,
    so the reader can still change font size and margins (spec section 28).
    """
    lines: list[str] = []
    for index, line in enumerate(node.verse_lines):
        indent = node.verse_indents[index] if index < len(node.verse_indents) else 0
        indent_class = f' class="indent-{min(indent, 4)}"' if indent else ""
        content = render_inline(line, resolve_note_href)
        if not content.strip():
            lines.append("<br/>")
            continue
        lines.append(f"<span{indent_class}>{content}</span><br/>")
    return f'<p class="verse"{dir_attr}>{"".join(lines)}</p>'


def _render_image_fallback(node: StructuralNode, images: dict[str, dict]) -> str:
    """A faithful picture of the source region, with a real accessible
    description rather than an empty alt."""
    img = images.get(node.image_ref or "")
    if not img:
        return ""
    filename = f"{node.image_ref}.{img['ext']}"
    alt = xml_escape(node.alt_text or "Region of the source document preserved as an image.")
    return (
        f'<figure class="preserved-region">'
        f'<img src="../images/{xml_escape(filename)}" alt="{alt}"/>'
        f"</figure>"
    )


def render_chapter_body(
    chapter: Chapter,
    current_filename: str,
    node_chapter_map: dict[str, str],
    images: dict[str, dict],
    base_direction: TextDirection = TextDirection.LTR,
    ref_chapter_map: dict[str, str] | None = None,
) -> str:
    ref_chapter_map = ref_chapter_map or {}

    def resolve_note_href(footnote_node_id: str) -> str:
        target_file = node_chapter_map.get(footnote_node_id)
        anchor = footnote_anchor_id(footnote_node_id)
        if target_file and target_file != current_filename:
            return f"{target_file}#{anchor}"
        return f"#{anchor}"

    def resolve_backref_href(ref_id: str) -> str:
        target_file = ref_chapter_map.get(ref_id)
        if target_file and target_file != current_filename:
            return f"{target_file}#{ref_id}"
        return f"#{ref_id}"

    parts: list[str] = []
    list_buffer: list[str] = []
    list_type: str | None = None

    def flush_list() -> None:
        nonlocal list_buffer, list_type
        if list_buffer:
            items = "\n".join(list_buffer)
            parts.append(f"<{list_type}>\n{items}\n</{list_type}>")
        list_buffer, list_type = [], None

    for node in chapter.nodes:
        if node.role in EXCLUDED_ROLES:
            continue

        if node.role == BlockRole.IMAGE:
            flush_list()
            img = images.get(node.image_ref or "")
            if img:
                filename = f"{node.image_ref}.{img['ext']}"
                parts.append(f'<figure><img src="../images/{xml_escape(filename)}" alt=""/></figure>')
            continue

        if node.role == BlockRole.IMAGE_FALLBACK:
            flush_list()
            rendered = _render_image_fallback(node, images)
            if rendered:
                parts.append(rendered)
            continue

        if node.role == BlockRole.TABLE:
            flush_list()
            rendered = _render_table(node, resolve_note_href)
            if rendered:
                parts.append(rendered)
            continue

        if node.role == BlockRole.FORMULA:
            flush_list()
            if node.mathml:
                parts.append(f'<div class="equation">{node.mathml}</div>')
            continue

        if node.role == BlockRole.THEMATIC_BREAK:
            # The source draws a scene change with a row of ornaments; <hr/> is
            # its semantic equivalent and renders as a proper divider instead of
            # the stray dots OCR produced.
            flush_list()
            parts.append('<hr class="scene-break"/>')
            continue

        if node.role == BlockRole.VERSE:
            flush_list()
            parts.append(_render_verse(node, resolve_note_href, _dir_attribute(node, base_direction)))
            continue

        if node.role == BlockRole.LIST_ITEM:
            marker_type = _list_marker_type(node.text)
            if list_type and marker_type != list_type:
                flush_list()
            list_type = marker_type
            content = render_inline(_strip_marker(node.text), resolve_note_href)
            list_buffer.append(f"<li>{content}</li>")
            continue

        flush_list()

        dir_attr = _dir_attribute(node, base_direction)

        if node.role in (BlockRole.HEADING, BlockRole.ENDNOTE_SECTION_HEADING):
            level = min(max(node.level or 4, 1), 4)
            content = render_inline(node.text, resolve_note_href)
            parts.append(
                f'<h{level} id="{xml_escape(node.node_id)}"{dir_attr}>{content}</h{level}>'
            )
        elif node.role == BlockRole.CAPTION:
            content = render_inline(node.text, resolve_note_href)
            parts.append(f'<p class="caption"{dir_attr}>{content}</p>')
        elif node.role == BlockRole.QUOTE:
            content = render_inline(node.text, resolve_note_href)
            parts.append(f"<blockquote{dir_attr}><p>{content}</p></blockquote>")
        elif node.role in _NOTE_ROLES:
            content = render_inline(node.text, resolve_note_href)
            epub_type = "footnote" if node.role == BlockRole.FOOTNOTE else "endnote"
            marker = xml_escape(node.footnote_number or node.endnote_number or "")
            # One back-link per reference, so a note cited twice can return to
            # either place the reader came from.
            back_links = "".join(
                f' <a class="noteback" href="{xml_escape(resolve_backref_href(ref))}">'
                f'↩{"" if len(node.footnote_backrefs) == 1 else str(i + 1)}</a>'
                for i, ref in enumerate(node.footnote_backrefs)
            )
            # The marker is reproduced as the source set it. Appending a full
            # stop would put punctuation in the book that the author never
            # wrote, which is the same defect as inventing an ellipsis.
            prefix = f"{marker} " if marker else ""
            if node.footnote_backrefs:
                parts.append(
                    f'<aside epub:type="{epub_type}" '
                    f'id="{footnote_anchor_id(node.node_id)}"{dir_attr}>'
                    f"<p>{prefix}{content}{back_links}</p></aside>"
                )
            else:
                # Nothing in the text points here. A reading system is allowed
                # to hide epub:type="footnote" content until a noteref
                # activates it, so marking an unreferenced block as a footnote
                # can make it unreachable — which is how sixty pages of a
                # grammar book's answer key came to be tagged as notes that
                # nothing could open. Keep the text visible and let the
                # quality report say it was never linked.
                parts.append(
                    f'<p class="note-unlinked" '
                    f'id="{footnote_anchor_id(node.node_id)}"{dir_attr}>'
                    f"{prefix}{content}</p>"
                )
        else:  # PARAGRAPH and any unclassified text role
            content = render_inline(node.text, resolve_note_href)
            if not content.strip():
                continue
            if node.bold:
                content = f"<strong>{content}</strong>"
            if node.italic:
                content = f"<em>{content}</em>"
            parts.append(f"<p{dir_attr}>{content}</p>")

    flush_list()
    return "\n".join(parts)


def _chapter_xhtml(
    title: str, body: str, lang: str, direction: TextDirection = TextDirection.LTR
) -> str:
    # dir on <html> sets the base direction for the whole document, which is
    # what makes an RTL book lay out correctly while individual LTR runs (Latin
    # citations, numbers) are still resolved by the Unicode bidi algorithm.
    return f"""<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="{xml_escape(lang)}" dir="{direction.value}">
<head>
<meta charset="utf-8"/>
<title>{xml_escape(title)}</title>
<link rel="stylesheet" type="text/css" href="../css/style.css"/>
</head>
<body>
{body}
</body>
</html>
"""


def _nav_xhtml(
    chapters: list[Chapter], lang: str, title: str, direction: TextDirection = TextDirection.LTR
) -> str:
    items = []
    for ch in chapters:
        top_headings = [
            n
            for n in ch.nodes
            if n.role in (BlockRole.HEADING, BlockRole.ENDNOTE_SECTION_HEADING)
        ]
        if top_headings and top_headings[0].text.strip() == ch.title.strip():
            sub = top_headings[1:]
        else:
            sub = []
        entry = f'<li><a href="text/{xml_escape(ch.filename)}">{xml_escape(ch.title)}</a>'
        if sub:
            min_level = min(n.level or 4 for n in sub)
            sub_items = "\n".join(
                f'<li><a href="text/{xml_escape(ch.filename)}#{xml_escape(n.node_id)}">{xml_escape(n.text.strip() or "Untitled section")}</a></li>'
                for n in sub
                if (n.level or 4) <= min_level + 1
            )
            if sub_items:
                entry += f"<ol>\n{sub_items}\n</ol>"
        entry += "</li>"
        items.append(entry)

    toc_items = "\n".join(items)
    return f"""<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="{xml_escape(lang)}" dir="{direction.value}">
<head>
<meta charset="utf-8"/>
<title>{xml_escape(title)}</title>
<link rel="stylesheet" type="text/css" href="css/style.css"/>
</head>
<body>
<nav epub:type="toc" id="toc">
<h1>{xml_escape(title)}</h1>
<ol>
{toc_items}
</ol>
</nav>
<nav epub:type="landmarks" id="landmarks" hidden="">
<ol>
<li><a epub:type="bodymatter" href="text/{xml_escape(chapters[0].filename)}">Start of content</a></li>
</ol>
</nav>
</body>
</html>
"""


def _toc_ncx(chapters: list["Chapter"], title: str, identifier: str) -> str:
    """The EPUB 2 navigation document.

    EPUB 3 replaced NCX with nav.xhtml and EPUBCheck is happy without it, but
    Amazon's ingestion and older Kindle firmware still read NCX, and a book
    without one can arrive on the device with no working table of contents at
    all. It costs one small file to satisfy both, so both are shipped.
    """
    points = []
    for order, ch in enumerate(chapters, start=1):
        points.append(
            f'<navPoint id="navpoint-{order}" playOrder="{order}">'
            f"<navLabel><text>{xml_escape(ch.title)}</text></navLabel>"
            f'<content src="text/{xml_escape(ch.filename)}"/>'
            f"</navPoint>"
        )
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">\n'
        "<head>"
        f'<meta name="dtb:uid" content="{xml_escape(identifier)}"/>'
        '<meta name="dtb:depth" content="1"/>'
        '<meta name="dtb:totalPageCount" content="0"/>'
        '<meta name="dtb:maxPageNumber" content="0"/>'
        "</head>\n"
        f"<docTitle><text>{xml_escape(title)}</text></docTitle>\n"
        "<navMap>" + "".join(points) + "</navMap>\n"
        "</ncx>\n"
    )


def _container_xml() -> str:
    return """<?xml version="1.0" encoding="utf-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
<rootfiles>
<rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
</rootfiles>
</container>
"""


_MEDIA_TYPES = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif"}


def _content_opf(
    chapters: list[Chapter],
    images: dict[str, dict],
    title: str,
    author: str | None,
    language: str,
    identifier: str,
    cover_ref: str | None,
    direction: TextDirection = TextDirection.LTR,
) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    manifest_items = [
        '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
        # The EPUB 2 table of contents, for Amazon's ingestion and older Kindle
        # firmware. Harmless to an EPUB 3 reader, which uses nav.xhtml instead.
        '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>',
        '<item id="css" href="css/style.css" media-type="text/css"/>',
    ]
    spine_items = []
    for i, ch in enumerate(chapters, start=1):
        item_id = f"chap{i:03d}"
        # EPUB3 requires a document embedding MathML to declare it here;
        # EPUBCheck rejects the package otherwise (OPF-014).
        properties = ' properties="mathml"' if any(n.mathml for n in ch.nodes) else ""
        manifest_items.append(
            f'<item id="{item_id}" href="text/{xml_escape(ch.filename)}" '
            f'media-type="application/xhtml+xml"{properties}/>'
        )
        spine_items.append(f'<itemref idref="{item_id}"/>')

    for ref, img in images.items():
        media_type = _MEDIA_TYPES.get(img["ext"], "image/png")
        props = ' properties="cover-image"' if ref == cover_ref else ""
        manifest_items.append(
            f'<item id="img_{xml_escape(ref)}" href="images/{xml_escape(ref)}.{img["ext"]}" '
            f'media-type="{media_type}"{props}/>'
        )

    author_xml = f"<dc:creator>{xml_escape(author)}</dc:creator>" if author else ""
    cover_meta = f'<meta name="cover" content="img_{xml_escape(cover_ref)}"/>' if cover_ref else ""

    return f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="pub-id" xml:lang="{xml_escape(language)}">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
<dc:identifier id="pub-id">{xml_escape(identifier)}</dc:identifier>
<dc:title>{xml_escape(title)}</dc:title>
<dc:language>{xml_escape(language)}</dc:language>
{author_xml}
<meta property="dcterms:modified">{now}</meta>
{cover_meta}
</metadata>
<manifest>
{chr(10).join(manifest_items)}
</manifest>
<spine toc="ncx" page-progression-direction="{direction.value}">
{chr(10).join(spine_items)}
</spine>
</package>
"""


_COVER_MIN_PAGE_COVERAGE = 0.5


def _find_cover_ref(document: DocumentModel) -> str | None:
    """A page-1 image covering most of the page is almost always the cover."""
    page_area = None
    for b in document.blocks:
        if b.page == 1:
            page_area = b.page_width * b.page_height
            break
    for node in document.nodes:
        if node.role != BlockRole.IMAGE or node.page != 1 or not node.image_ref:
            continue
        img = document.images.get(node.image_ref)
        if not img or not page_area:
            continue
        x0, y0, x1, y1 = img["bbox"]
        coverage = ((x1 - x0) * (y1 - y0)) / page_area
        if coverage >= _COVER_MIN_PAGE_COVERAGE:
            return node.image_ref
    return None


def build_epub(
    document: DocumentModel,
    output_path: Path,
    title: str,
    author: str | None,
    language: str,
    direction: TextDirection = TextDirection.LTR,
) -> BuildResult:
    """Assemble a valid, reflowable EPUB3 package from the reconstructed document
    model (spec sections 27-30). Zero JavaScript, conservative CSS, semantic
    XHTML — no absolute positioning or PDF-page-shaped fixed layouts."""
    renderable = [n for n in document.nodes if n.role not in EXCLUDED_ROLES]
    chapters = split_into_chapters(renderable)
    node_chapter_map = _build_node_chapter_map(chapters)
    ref_chapter_map = _build_ref_chapter_map(chapters)
    cover_ref = _find_cover_ref(document)
    identifier = f"urn:uuid:{uuid.uuid4()}"
    lang = language or "en"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", _container_xml())
        zf.writestr("OEBPS/css/style.css", DEFAULT_STYLESHEET)

        for ch in chapters:
            body = render_chapter_body(
                ch, ch.filename, node_chapter_map, document.images, direction, ref_chapter_map
            )
            zf.writestr(
                f"OEBPS/text/{ch.filename}", _chapter_xhtml(ch.title, body, lang, direction)
            )

        for ref, img in document.images.items():
            src_path = Path(img["path"])
            if src_path.exists():
                zf.writestr(f"OEBPS/images/{ref}.{img['ext']}", src_path.read_bytes())

        zf.writestr("OEBPS/nav.xhtml", _nav_xhtml(chapters, lang, title, direction))
        zf.writestr("OEBPS/toc.ncx", _toc_ncx(chapters, title, identifier))
        zf.writestr(
            "OEBPS/content.opf",
            _content_opf(
                chapters, document.images, title, author, lang, identifier, cover_ref, direction
            ),
        )

    heading_count = sum(
        1 for n in renderable if n.role in (BlockRole.HEADING, BlockRole.ENDNOTE_SECTION_HEADING)
    )
    footnote_count = sum(1 for n in document.nodes if n.role == BlockRole.FOOTNOTE)
    footnote_linked = sum(1 for n in document.nodes if n.footnote_targets)
    image_count = sum(1 for n in renderable if n.role == BlockRole.IMAGE)
    list_item_count = sum(1 for n in renderable if n.role == BlockRole.LIST_ITEM)
    rtl_block_count = sum(1 for n in renderable if n.direction == TextDirection.RTL)
    # Must stay in step with integrity._TEXT_BEARING_ROLES. A role counted as
    # expected there but not delivered here reads as lost content: captions were
    # in one set and not the other, and a table fixture's integrity fell to 56%
    # while every word was present in the file.
    _content_roles = set(TEXT_BEARING_ROLES)
    word_count = sum(len(n.text.split()) for n in renderable if n.role in _content_roles)

    return BuildResult(
        output_path=output_path,
        chapter_count=len(chapters),
        heading_count=heading_count,
        footnote_count=footnote_count,
        footnote_linked_count=footnote_linked,
        image_count=image_count,
        list_item_count=list_item_count,
        table_count=sum(1 for n in renderable if n.role == BlockRole.TABLE),
        word_count=word_count,
        cover_image_ref=cover_ref,
        endnote_count=sum(1 for n in document.nodes if n.role == BlockRole.ENDNOTE),
        verse_count=sum(1 for n in renderable if n.role == BlockRole.VERSE),
        formula_count=sum(1 for n in renderable if n.role == BlockRole.FORMULA),
        image_fallback_count=sum(1 for n in renderable if n.role == BlockRole.IMAGE_FALLBACK),
        rtl_block_count=rtl_block_count,
    )
