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
    line_break_after: bool = False


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


@dataclass
class DocumentModel:
    source_filename: str
    analysis: PDFAnalysis
    blocks: list[Block] = field(default_factory=list)
    nodes: list[StructuralNode] = field(default_factory=list)
    images: dict[str, dict] = field(default_factory=dict)  # ref -> {path, page, bbox}
    metadata: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
