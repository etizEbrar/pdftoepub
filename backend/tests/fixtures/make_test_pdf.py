"""Generates synthetic test PDFs with reportlab so the pipeline and its tests
don't depend on a real copyrighted book. These deliberately exercise: headings
at multiple levels, wrapped/hyphenated paragraphs spanning a page boundary, a
bulleted and a numbered list, a footnote reference with its matching footnote,
a running header/footer with page numbers, and an embedded image.
"""

from __future__ import annotations

from pathlib import Path

import fitz
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas


def _draw_header_footer(c: canvas.Canvas, page_num: int, title: str) -> None:
    width, height = LETTER
    c.setFont("Helvetica", 9)
    c.drawCentredString(width / 2, height - 0.5 * inch, title)
    c.drawCentredString(width / 2, 0.5 * inch, str(page_num))


def build_simple_book(path: Path) -> Path:
    width, height = LETTER
    c = canvas.Canvas(str(path), pagesize=LETTER)
    title = "The Sample Chronicle"
    c.setTitle(title)
    c.setAuthor("A. Test Author")

    # Page 1: title page + a near-full-page image (cover candidate)
    _draw_header_footer(c, 1, title)
    c.setFont("Helvetica-Bold", 28)
    c.drawCentredString(width / 2, height - 2 * inch, title)
    c.setFillColorRGB(0.6, 0.6, 0.85)
    c.rect(0.75 * inch, 1 * inch, width - 1.5 * inch, height - 3.5 * inch, fill=1, stroke=0)
    c.setFillColorRGB(0, 0, 0)
    c.showPage()

    # Page 2: Chapter 1 heading + wrapped paragraph with hyphenation artifact
    # and a footnote reference.
    _draw_header_footer(c, 2, title)
    c.setFont("Helvetica-Bold", 20)
    c.drawString(1 * inch, height - 1.3 * inch, "Chapter 1: Beginnings")

    c.setFont("Helvetica", 11)
    y = height - 1.8 * inch
    c.drawString(1 * inch, y, "This is the first paragraph of the book. It contains a demon-")
    y -= 0.22 * inch
    c.drawString(1 * inch, y, "stration of hyphenation repair across a wrapped line and it")
    y -= 0.22 * inch
    c.drawString(1 * inch, y, "keeps going so the reader can see reconstruction at work.")
    y -= 0.22 * inch
    c.drawString(1 * inch, y, "This sentence has an important claim")
    c.setFont("Helvetica", 7)
    c.drawString(3.55 * inch, y + 0.05 * inch, "1")
    c.setFont("Helvetica", 11)
    c.drawString(3.68 * inch, y, "requiring a citation.")

    y -= 0.5 * inch
    c.setFont("Helvetica-Bold", 15)
    c.drawString(1 * inch, y, "A Section Heading")
    y -= 0.3 * inch
    c.setFont("Helvetica", 11)
    c.drawString(1 * inch, y, "A short paragraph under the section heading, for structure testing.")

    y -= 0.5 * inch
    c.setFont("Helvetica", 11)
    c.drawString(1 * inch, y, "• First bullet item in an unordered list")
    y -= 0.22 * inch
    c.drawString(1 * inch, y, "• Second bullet item in the same list")
    y -= 0.4 * inch
    c.drawString(1 * inch, y, "1. First numbered item")
    y -= 0.22 * inch
    c.drawString(1 * inch, y, "2. Second numbered item")

    # Footnote at bottom of page (above the running footer/page number).
    c.setFont("Helvetica", 8)
    c.drawString(1 * inch, 0.85 * inch, "1 This is the footnote text explaining the citation above.")
    c.showPage()

    # Page 3: paragraph continuing across the page 2/3 boundary (no terminal
    # punctuation at end of page 2's last paragraph line simulated via a
    # second chapter) + Chapter 2 heading, to test chapter splitting + TOC.
    _draw_header_footer(c, 3, title)
    c.setFont("Helvetica-Bold", 20)
    c.drawString(1 * inch, height - 1.3 * inch, "Chapter 2: Continuation")
    c.setFont("Helvetica", 11)
    y = height - 1.8 * inch
    c.drawString(1 * inch, y, "Chapter two begins here with an ordinary paragraph of body text")
    y -= 0.22 * inch
    c.drawString(1 * inch, y, "that should be reconstructed as a single flowing paragraph node.")
    y -= 0.4 * inch
    c.setFont("Helvetica-Oblique", 11)
    c.drawString(1.3 * inch, y, "A quoted aside, indented and italicized for emphasis.")
    c.showPage()

    c.save()
    return path


def build_encrypted_pdf(path: Path) -> Path:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "This page is password protected.")
    doc.save(str(path), encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="secret", owner_pw="owner")
    doc.close()
    return path


def build_scanned_pdf(path: Path) -> Path:
    """A PDF with a full-page raster image and no text layer at all — the
    shape our pipeline must recognize as SCANNED and decline (OCR is not yet
    implemented) rather than silently emitting an empty book."""
    scratch_img = path.parent / "_scan_source.png"
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 600, 800), False)
    pix.clear_with(255)
    pix.save(str(scratch_img))

    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_image(page.rect, filename=str(scratch_img))
    doc.save(str(path))
    doc.close()
    scratch_img.unlink()
    return path


def build_corrupted_pdf(path: Path) -> Path:
    path.write_bytes(b"%PDF-1.4\nthis is not a real pdf body, just garbage bytes.")
    return path


if __name__ == "__main__":
    build_simple_book(Path(__file__).parent / "simple_book.pdf")
    print("wrote simple_book.pdf")
