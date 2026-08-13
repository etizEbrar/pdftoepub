from __future__ import annotations

import re
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

from app.models.document import BlockRole, DocumentModel, StructuralNode
from app.pipeline.epub.css import DEFAULT_STYLESHEET
from app.pipeline.epub.render import footnote_anchor_id, render_inline
from app.pipeline.structure import BULLET_RE, NUMBERED_RE

EXCLUDED_ROLES = {BlockRole.HEADER, BlockRole.FOOTER, BlockRole.PAGE_NUMBER}
_HEADING_SPLIT_ROLE = BlockRole.HEADING


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


def slugify(text: str, fallback: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or fallback


def split_into_chapters(nodes: list[StructuralNode]) -> list[Chapter]:
    """Split by detected document structure, not PDF pages (spec section 30).

    Uses the top-most heading level actually present as the chapter boundary:
    level 1 if any exist, else level 2, else the whole book is one chapter.
    """
    heading_levels = {n.level for n in nodes if n.role == _HEADING_SPLIT_ROLE and n.level}
    split_level = 1 if 1 in heading_levels else (2 if 2 in heading_levels else None)

    chapters: list[Chapter] = []
    current: Chapter | None = None
    front_matter: list[StructuralNode] = []

    for node in nodes:
        starts_chapter = (
            split_level is not None and node.role == _HEADING_SPLIT_ROLE and node.level == split_level
        )
        if starts_chapter:
            if current is None and front_matter:
                chapters.append(Chapter(filename="", title="Front Matter", nodes=front_matter))
            title = node.text.strip() or f"Chapter {len(chapters) + 1}"
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


def render_chapter_body(
    chapter: Chapter,
    current_filename: str,
    node_chapter_map: dict[str, str],
    images: dict[str, dict],
) -> str:
    def resolve_note_href(footnote_node_id: str) -> str:
        target_file = node_chapter_map.get(footnote_node_id)
        anchor = footnote_anchor_id(footnote_node_id)
        if target_file and target_file != current_filename:
            return f"{target_file}#{anchor}"
        return f"#{anchor}"

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

        if node.role == BlockRole.LIST_ITEM:
            marker_type = _list_marker_type(node.text)
            if list_type and marker_type != list_type:
                flush_list()
            list_type = marker_type
            content = render_inline(_strip_marker(node.text), resolve_note_href)
            list_buffer.append(f"<li>{content}</li>")
            continue

        flush_list()

        if node.role == BlockRole.HEADING:
            level = min(max(node.level or 4, 1), 4)
            content = render_inline(node.text, resolve_note_href)
            parts.append(f'<h{level} id="{xml_escape(node.node_id)}">{content}</h{level}>')
        elif node.role == BlockRole.QUOTE:
            content = render_inline(node.text, resolve_note_href)
            parts.append(f"<blockquote><p>{content}</p></blockquote>")
        elif node.role == BlockRole.FOOTNOTE:
            content = render_inline(node.text, resolve_note_href)
            backref = node.footnote_backrefs[0] if node.footnote_backrefs else None
            back_link = f' <a href="#{xml_escape(backref)}">↩</a>' if backref else ""
            marker = xml_escape(node.footnote_number or "")
            parts.append(
                f'<aside epub:type="footnote" id="{footnote_anchor_id(node.node_id)}">'
                f"<p>{marker}. {content}{back_link}</p></aside>"
            )
        else:  # PARAGRAPH and any unclassified text role
            content = render_inline(node.text, resolve_note_href)
            if not content.strip():
                continue
            if node.bold:
                content = f"<strong>{content}</strong>"
            if node.italic:
                content = f"<em>{content}</em>"
            parts.append(f"<p>{content}</p>")

    flush_list()
    return "\n".join(parts)


def _chapter_xhtml(title: str, body: str, lang: str) -> str:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="{xml_escape(lang)}">
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


def _nav_xhtml(chapters: list[Chapter], lang: str, title: str) -> str:
    items = []
    for ch in chapters:
        top_headings = [n for n in ch.nodes if n.role == BlockRole.HEADING]
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
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="{xml_escape(lang)}">
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
) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    manifest_items = [
        '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
        '<item id="css" href="css/style.css" media-type="text/css"/>',
    ]
    spine_items = []
    for i, ch in enumerate(chapters, start=1):
        item_id = f"chap{i:03d}"
        manifest_items.append(
            f'<item id="{item_id}" href="text/{xml_escape(ch.filename)}" media-type="application/xhtml+xml"/>'
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
<spine>
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


def build_epub(document: DocumentModel, output_path: Path, title: str, author: str | None, language: str) -> BuildResult:
    """Assemble a valid, reflowable EPUB3 package from the reconstructed document
    model (spec sections 27-30). Zero JavaScript, conservative CSS, semantic
    XHTML — no absolute positioning or PDF-page-shaped fixed layouts."""
    renderable = [n for n in document.nodes if n.role not in EXCLUDED_ROLES]
    chapters = split_into_chapters(renderable)
    node_chapter_map = _build_node_chapter_map(chapters)
    cover_ref = _find_cover_ref(document)
    identifier = f"urn:uuid:{uuid.uuid4()}"
    lang = language or "en"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", _container_xml())
        zf.writestr("OEBPS/css/style.css", DEFAULT_STYLESHEET)

        for ch in chapters:
            body = render_chapter_body(ch, ch.filename, node_chapter_map, document.images)
            zf.writestr(f"OEBPS/text/{ch.filename}", _chapter_xhtml(ch.title, body, lang))

        for ref, img in document.images.items():
            src_path = Path(img["path"])
            if src_path.exists():
                zf.writestr(f"OEBPS/images/{ref}.{img['ext']}", src_path.read_bytes())

        zf.writestr("OEBPS/nav.xhtml", _nav_xhtml(chapters, lang, title))
        zf.writestr(
            "OEBPS/content.opf",
            _content_opf(chapters, document.images, title, author, lang, identifier, cover_ref),
        )

    heading_count = sum(1 for n in renderable if n.role == BlockRole.HEADING)
    footnote_count = sum(1 for n in document.nodes if n.role == BlockRole.FOOTNOTE)
    footnote_linked = sum(1 for n in document.nodes if n.footnote_targets)
    image_count = sum(1 for n in renderable if n.role == BlockRole.IMAGE)
    list_item_count = sum(1 for n in renderable if n.role == BlockRole.LIST_ITEM)
    _content_roles = {
        BlockRole.PARAGRAPH,
        BlockRole.HEADING,
        BlockRole.QUOTE,
        BlockRole.LIST_ITEM,
        BlockRole.FOOTNOTE,
    }
    word_count = sum(len(n.text.split()) for n in renderable if n.role in _content_roles)

    return BuildResult(
        output_path=output_path,
        chapter_count=len(chapters),
        heading_count=heading_count,
        footnote_count=footnote_count,
        footnote_linked_count=footnote_linked,
        image_count=image_count,
        list_item_count=list_item_count,
        table_count=0,
        word_count=word_count,
        cover_image_ref=cover_ref,
    )
