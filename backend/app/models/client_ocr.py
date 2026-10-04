"""Text a client recognised on its own device, offered in place of Tesseract.

A scanned page costs about 1.8s to OCR on a laptop and about 110s on a 512 MB
shared-CPU container, so a 253-page scanned book is roughly eight hours of
server time. A modern iPhone has hardware for exactly this job and Apple's
Vision framework reads Turkish at its `.accurate` level, offline and free.

So the client may do the reading and send what it found. The division of labour
is deliberate: the client sends *only* text and geometry, and the server still
does every piece of layout reconstruction — lines into blocks, blocks into
paragraphs, headings, footnotes, the table of contents. That logic has to
behave identically whether a page's words came from the PDF's own text layer,
from Tesseract, or from a phone, and it is only tested in one place.

Coordinates are PDF points in the page's own space, x to the right and y
downward from the top-left of the crop box — the same space `Block.bbox` uses,
so nothing downstream can tell the difference.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class ClientOCRWord(BaseModel):
    text: str = Field(min_length=1, max_length=200)
    # x0, y0, x1, y1 in PDF points, top-left origin.
    bbox: tuple[float, float, float, float]
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)

    @field_validator("bbox")
    @classmethod
    def _ordered(cls, v: tuple[float, float, float, float]):
        x0, y0, x1, y1 = v
        if x1 < x0 or y1 < y0:
            raise ValueError("bbox must be (x0, y0, x1, y1) with x1 >= x0 and y1 >= y0")
        return v


class ClientOCRLine(BaseModel):
    """One recognised line. Vision's natural unit is a line, so it is ours."""

    words: list[ClientOCRWord] = Field(min_length=1, max_length=400)
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)


class ClientOCRPage(BaseModel):
    page: int = Field(ge=1)
    lines: list[ClientOCRLine] = Field(default_factory=list, max_length=4000)


class ClientOCR(BaseModel):
    """What a client recognised, for some or all of a document's pages.

    Pages may be omitted: a book is usually part native text and part scan, and
    the client only reads what the server would otherwise have to.
    """

    engine: str = Field(max_length=60, default="unknown")
    pages: list[ClientOCRPage] = Field(default_factory=list, max_length=2000)

    def by_page(self) -> dict[int, ClientOCRPage]:
        # Later entries win, so a retried page replaces an earlier attempt.
        return {p.page: p for p in self.pages if p.lines}
