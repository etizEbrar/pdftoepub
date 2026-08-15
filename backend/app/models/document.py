from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class PDFClassification(str, Enum):
    NATIVE_TEXT = "NATIVE_TEXT"
    SCANNED = "SCANNED"
    MIXED = "MIXED"
    IMAGE_HEAVY = "IMAGE_HEAVY"
    UNKNOWN = "UNKNOWN"


class BlockRole(str, Enum):
    UNKNOWN = "unknown"
    TITLE = "title"
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST_ITEM = "list_item"
    FOOTNOTE = "footnote"
    HEADER = "header"
    FOOTER = "footer"
    PAGE_NUMBER = "page_number"
    CAPTION = "caption"
    IMAGE = "image"
    TABLE = "table"
    QUOTE = "quote"
    ENDNOTE = "endnote"
    ENDNOTE_SECTION_HEADING = "endnote_section_heading"
    # A centred row of ornaments ("* * *", "• • •") marking a scene change.
    THEMATIC_BREAK = "thematic_break"
    VERSE = "verse"
    FORMULA = "formula"
    # A source region preserved verbatim as an image because semantic
    # reconstruction wasn't reliable enough to be safe.
    IMAGE_FALLBACK = "image_fallback"


class PageTextKind(str, Enum):
    """How a single page's text should be obtained."""

    NATIVE = "native"  # trustworthy embedded text layer
    SCANNED = "scanned"  # no usable text layer; needs OCR
    MIXED = "mixed"  # partial text layer plus large un-texted image regions
    EMPTY = "empty"  # genuinely blank page


class TextDirection(str, Enum):
    LTR = "ltr"
    RTL = "rtl"


@dataclass
class TableCell:
    text: str
    row: int
    col: int
    row_span: int = 1
    col_span: int = 1
    is_header: bool = False


@dataclass
class TableData:
    """A geometrically reconstructed table. Rendered as semantic XHTML only when
    `confidence` clears settings.table_min_confidence; otherwise the owning node
    is converted to an IMAGE_FALLBACK preserving the original region."""

    rows: int
    cols: int
    cells: list[TableCell] = field(default_factory=list)
    has_header_row: bool = False
    caption: str | None = None
    confidence: float = 0.0
    continues_from_previous_page: bool = False


@dataclass
class Span:
    """A run of text with uniform typography, as reported by the PDF's text layer."""

    text: str
    bbox: tuple[float, float, float, float]
    font: str
    font_size: float
    bold: bool
    italic: bool
    baseline: float
    is_superscript: bool = False
    is_subscript: bool = False
    line_break_after: bool = False
    # OCR provenance: None for spans read from a real text layer, otherwise the
    # mean Tesseract confidence (0-100) for the words making up this span.
    ocr_confidence: float | None = None


@dataclass
class Block:
    """One geometry-anchored text or image block extracted from a PDF page.

    Kept alive, unmodified, from extraction through EPUB generation so every
    rendered node can always be traced back to concrete source geometry.
    """

    block_id: str
    page: int
    page_width: float
    page_height: float
    bbox: tuple[float, float, float, float]
    kind: str  # "text" | "image"
    text: str = ""
    spans: list[Span] = field(default_factory=list)
    font: str | None = None
    font_size: float | None = None
    bold: bool = False
    italic: bool = False
    baseline: float | None = None
    line_id: str | None = None
    image_ref: str | None = None  # key into DocumentModel.images for kind == "image"
    column: int = 0
    order_key: float = 0.0
    # Provenance so integrity accounting can distinguish native from OCR text.
    source: str = "native"  # "native" | "ocr"
    ocr_confidence: float | None = None
    direction: TextDirection = TextDirection.LTR

    def geometry_dict(self) -> dict:
        """The canonical per-spec block/geometry record, text+geometry bound together."""
        return {
            "page": self.page,
            "block_id": self.block_id,
            "text": self.text,
            "bbox": list(self.bbox),
            "font": self.font,
            "font_size": self.font_size,
            "bold": self.bold,
            "italic": self.italic,
            "baseline": self.baseline,
            "line_id": self.line_id,
        }


@dataclass
class StructuralNode:
    """One node of the reconstructed logical document (what becomes EPUB content)."""

    node_id: str
    role: BlockRole
    text: str = ""
    level: int | None = None  # heading level 1-4
    confidence: float = 1.0
    source_block_ids: list[str] = field(default_factory=list)
    bold: bool = False
    italic: bool = False
    footnote_targets: list[str] = field(default_factory=list)  # node_ids of footnotes referenced
    footnote_number: str | None = None  # for role == FOOTNOTE, its marker text (e.g. "1", "*")
    footnote_backrefs: list[str] = field(default_factory=list)  # for role == FOOTNOTE: ref anchor ids pointing here
    image_ref: str | None = None
    page: int | None = None
    # Endnotes reuse the footnote machinery but keep their own identity so the
    # two are never conflated (spec: "do not confuse footnotes and endnotes").
    endnote_number: str | None = None
    endnote_chapter: str | None = None
    # Verse: the meaningful line breaks that must survive into the EPUB, plus
    # per-line indent depth. Empty for every other role.
    verse_lines: list[str] = field(default_factory=list)
    verse_indents: list[int] = field(default_factory=list)
    table: TableData | None = None
    mathml: str | None = None
    direction: TextDirection = TextDirection.LTR
    # Populated when this node was demoted to a preserved image region.
    fallback_reason: str | None = None
    alt_text: str | None = None
    # For headings: size relative to body text, used to derive h1..h4 from the
    # scales the document actually uses rather than absolute point sizes.
    heading_scale: float | None = None
    # Why a structural decision was made, so a low-confidence call stays
    # explainable in the quality report instead of being silently accepted.
    evidence: list[str] = field(default_factory=list)


@dataclass
class PDFAnalysis:
    page_count: int
    classification: PDFClassification
    has_text_layer: bool
    scanned_page_ratio: float
    outline: list[dict] = field(default_factory=list)
    title_guess: str | None = None
    author_guess: str | None = None
    language_guess: str | None = None
    is_encrypted: bool = False
    page_kinds: dict[int, PageTextKind] = field(default_factory=dict)  # 1-based page -> kind
    direction: TextDirection = TextDirection.LTR
    ocr_pages: list[int] = field(default_factory=list)
    mean_ocr_confidence: float | None = None


@dataclass
class DocumentModel:
    source_filename: str
    analysis: PDFAnalysis
    blocks: list[Block] = field(default_factory=list)
    nodes: list[StructuralNode] = field(default_factory=list)
    images: dict[str, dict] = field(default_factory=dict)  # ref -> {path, page, bbox}
    metadata: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
