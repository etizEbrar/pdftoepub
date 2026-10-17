from __future__ import annotations

import re

from app.models.document import Block
from app.pipeline.footnotes import strip_all_sentinels

# "Editörden……………1", "Prof. Dr. Elif ORHAN .......... 5": a run of leader
# dots carrying the eye to a page number at the end of the line.
_LEADER_LINE_RE = re.compile(r"(?:[.…·•‧∙⋅_]\s*){4,}\s*\d{1,4}\s*$")
_TOC_TITLE_RE = re.compile(
    r"^\s*(?:i̇çi̇ndeki̇ler|içindekiler|İÇİNDEKİLER|ICINDEKILER|contents|table of contents"
    r"|inhalt|inhaltsverzeichnis|sommaire|table des matières|índice|indice|sommario"
    r"|المحتويات|فهرس)\s*(?:tablosu)?\s*$",
    re.IGNORECASE,
)
# Leader lines a page must carry to be read as contents by themselves. One or
# two can be a price list or a form; a contents page lists the book.
_MIN_LEADER_LINES = 3


def _lines(block: Block) -> list[str]:
    return [ln for ln in strip_all_sentinels(block.text).split("\n") if ln.strip()]


def is_toc_title(text: str) -> bool:
    return bool(_TOC_TITLE_RE.match(" ".join(text.split())))


def detect_toc_pages(text_blocks: list[Block]) -> set[int]:
    """Pages that carry the book's printed table of contents.

    A printed contents page is a list of page numbers for a book that no
    longer has pages. Read as prose, its entries were merged into paragraphs
    trailing rows of leader dots, and its chapter titles were taken for
    headings of the contents page itself.
    """
    leader_lines: dict[int, int] = {}
    titled: set[int] = set()
    for block in text_blocks:
        for line in _lines(block):
            if _LEADER_LINE_RE.search(line):
                leader_lines[block.page] = leader_lines.get(block.page, 0) + 1
            if is_toc_title(line):
                titled.add(block.page)

    pages = {
        page
        for page, count in leader_lines.items()
        if count >= _MIN_LEADER_LINES or (page in titled and count >= 1)
    }
    # Contents that run on to the next page keep their leaders there, but
    # often too few of them to qualify on their own.
    for page, count in leader_lines.items():
        if page - 1 in pages and count >= 1:
            pages.add(page)
    return pages


def entry_text(text: str) -> str:
    """An entry's words without its leader dots and page number."""
    lines = [_LEADER_LINE_RE.sub("", ln).rstrip() for ln in text.split("\n")]
    return " ".join(" ".join(ln.split()) for ln in lines if ln.strip())
