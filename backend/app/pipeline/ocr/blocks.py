"""Turning recognised words into Blocks, for every OCR source there is.

Tesseract and a client's own OCR engine disagree about almost everything —
coordinate space, confidence scale, whether paragraphs are reported at all —
but they agree on the only thing that matters downstream: a page is lines of
words, and each word has a box. Once a caller has placed its words in PDF
points and grouped them into blocks of lines, the Block it wants is the same
Block, so it is built in one place. Reading order, paragraph reconstruction,
heading detection and the table of contents then cannot tell the sources apart,
which is the property this module exists to guarantee.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models.document import Block, Span, TextDirection


@dataclass
class PlacedWord:
    """One recognised word, already in PDF points with a top-left origin."""

    text: str
    bbox: tuple[float, float, float, float]
    confidence: float


def blocks_from_placed_words(
    grouped: list[list[list[PlacedWord]]],
    page_num: int,
    page_width: float,
    page_height: float,
    id_prefix: str = "ocr",
) -> list[Block]:
    """Build one Block per group.

    `grouped` is blocks -> lines -> words. Lines keep their break so verse,
    tables and heading wrapping see the page's real line structure.
    """
    blocks: list[Block] = []
    for block_index, lines in enumerate(grouped):
        spans: list[Span] = []
        line_texts: list[str] = []
        confidences: list[float] = []
        x0 = y0 = float("inf")
        x1 = y1 = float("-inf")

        for line_words in lines:
            parts: list[str] = []
            for word_index, word in enumerate(line_words):
                # The leading space belongs to the word, so joining the spans
                # reproduces the line exactly and no space is invented at a
                # line start.
                text = word.text if word_index == 0 else f" {word.text}"
                parts.append(text)
                confidences.append(word.confidence)
                x0 = min(x0, word.bbox[0])
                y0 = min(y0, word.bbox[1])
                x1 = max(x1, word.bbox[2])
                y1 = max(y1, word.bbox[3])
                spans.append(
                    Span(
                        text=text,
                        bbox=word.bbox,
                        font="OCR",
                        font_size=round(word.bbox[3] - word.bbox[1], 2),
                        bold=False,
                        italic=False,
                        baseline=round(word.bbox[3], 2),
                        ocr_confidence=word.confidence,
                    )
                )
            if spans:
                spans[-1].line_break_after = True
            line_texts.append("".join(parts))

        if not spans:
            continue

        # Median rather than mean: one oversized initial or a stray mark should
        # not move the size that heading detection reads off this block.
        font_sizes = sorted(s.font_size for s in spans)
        blocks.append(
            Block(
                block_id=f"p{page_num}_{id_prefix}{block_index:03d}",
                page=page_num,
                page_width=page_width,
                page_height=page_height,
                bbox=(x0, y0, x1, y1),
                kind="text",
                text="\n".join(line_texts),
                spans=spans,
                font="OCR",
                font_size=font_sizes[len(font_sizes) // 2],
                baseline=spans[-1].baseline,
                line_id=f"p{page_num}_{id_prefix}l{block_index:03d}000",
                source="ocr",
                ocr_confidence=sum(confidences) / len(confidences),
                direction=TextDirection.LTR,
            )
        )
    return blocks
