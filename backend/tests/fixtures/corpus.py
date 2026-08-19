"""Synthetic but realistic PDF fixtures covering the document types in the spec.

These are generated rather than checked in as binaries so the suite stays small,
reproducible, and free of third-party copyrighted material. Each builder aims at
the *structural* characteristics of its document class (column geometry, note
apparatus, verse ragging, script direction), which is what the pipeline reasons
about — not at literary realism.
"""

from __future__ import annotations

from pathlib import Path

import fitz
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

PAGE_W, PAGE_H = LETTER

_UNICODE_FONT_PATH = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"
_UNICODE_FONT = "ArialUnicode"
_unicode_font_registered = False


def unicode_font_available() -> bool:
    """True when a font covering Arabic/Hebrew/Turkish is installed."""
    return Path(_UNICODE_FONT_PATH).exists()


def _ensure_unicode_font() -> str:
    """Register a font with Arabic/Hebrew/Turkish coverage, falling back to
    Helvetica (Latin only) when it isn't present on this machine."""
    global _unicode_font_registered
    if not unicode_font_available():
        return "Helvetica"
    if not _unicode_font_registered:
        pdfmetrics.registerFont(TTFont(_UNICODE_FONT, _UNICODE_FONT_PATH))
        _unicode_font_registered = True
    return _UNICODE_FONT


def _header_footer(c: canvas.Canvas, page_num: int, title: str, font: str = "Helvetica") -> None:
    c.setFont(font, 9)
    c.drawCentredString(PAGE_W / 2, PAGE_H - 0.5 * inch, title)
    c.drawCentredString(PAGE_W / 2, 0.5 * inch, str(page_num))


# --------------------------------------------------------------------------
# A. Turkish novel — Turkish diacritics, chapters, running furniture, footnote
# --------------------------------------------------------------------------

TURKISH_PARAGRAPHS = [
    "Şehrin üzerine çöken sis, sabahın ilk ışıklarıyla birlikte yavaşça",
    "dağılmaya başladı. Güneş, çatıların ardından yükselirken sokaklar",
    "yeniden canlanıyordu. Çocuklar okula giderken güldüler.",
]


def build_turkish_novel(path: Path) -> Path:
    font = _ensure_unicode_font()
    c = canvas.Canvas(str(path), pagesize=LETTER)
    c.setTitle("Sisin Ardındaki Şehir")
    c.setAuthor("Ayşe Yılmaz")
    title = "Sisin Ardındaki Şehir"

    for page in range(1, 4):
        _header_footer(c, page, title, font)
        y = PAGE_H - 1.3 * inch
        c.setFont(font, 20)
        c.drawString(1 * inch, y, f"Bölüm {page}: Başlangıç")
        y -= 0.45 * inch
        c.setFont(font, 11)
        for line in TURKISH_PARAGRAPHS:
            c.drawString(1 * inch, y, line)
            y -= 0.24 * inch
        y -= 0.2 * inch
        c.drawString(1 * inch, y, "Bu cümle bir dipnota atıfta bulunur")
        c.setFont(font, 7)
        c.drawString(3.5 * inch, y + 0.05 * inch, "1")
        c.setFont(font, 11)
        c.drawString(3.62 * inch, y, "ve devam eder.")

        # Distinct note text per page, as in a real book.
        c.setFont(font, 8)
        c.drawString(1 * inch, 0.85 * inch, f"1 Bölüm {page} için kaynak açıklaması.")
        c.showPage()

    c.save()
    return path


# --------------------------------------------------------------------------
# B. Two-column academic paper
# --------------------------------------------------------------------------

def build_two_column_academic(path: Path) -> Path:
    c = canvas.Canvas(str(path), pagesize=LETTER)
    c.setTitle("On Columnar Reading Order")
    c.setAuthor("R. Researcher")

    left_x, right_x = 0.85 * inch, 4.45 * inch
    col_width_lines = [
        "This left column contains the opening",
        "argument of the paper and continues",
        "for several lines before the reader",
        "reaches the bottom of the column.",
    ]
    right_lines = [
        "The right column continues the same",
        "argument and must be read only after",
        "the left column has been finished by",
        "the reconstruction engine.",
    ]

    for page in range(1, 3):
        _header_footer(c, page, "On Columnar Reading Order")
        if page == 1:
            c.setFont("Helvetica-Bold", 18)
            c.drawCentredString(PAGE_W / 2, PAGE_H - 1.2 * inch, "On Columnar Reading Order")

        y_start = PAGE_H - 1.9 * inch
        c.setFont("Helvetica-Bold", 13)
        c.drawString(left_x, y_start, f"{page}. Section Heading")

        y = y_start - 0.32 * inch
        c.setFont("Helvetica", 10)
        for line in col_width_lines:
            c.drawString(left_x, y, line)
            y -= 0.22 * inch
        c.drawString(left_x, y, "A cited claim appears here")
        c.setFont("Helvetica", 7)
        c.drawString(left_x + 2.05 * inch, y + 0.05 * inch, "1")
        c.setFont("Helvetica", 10)

        y = y_start - 0.32 * inch
        for line in right_lines:
            c.drawString(right_x, y, line)
            y -= 0.22 * inch

        c.setFont("Helvetica", 8)
        c.drawString(left_x, 0.85 * inch, "1 Reference for the cited claim above.")
        c.showPage()

    c.save()
    return path


# --------------------------------------------------------------------------
# C. Footnote-heavy academic book — multiple notes per page
# --------------------------------------------------------------------------

def build_footnote_heavy(path: Path) -> Path:
    c = canvas.Canvas(str(path), pagesize=LETTER)
    c.setTitle("A Study in Annotation")
    c.setAuthor("H. Scholar")

    for page in range(1, 4):
        _header_footer(c, page, "A Study in Annotation")
        c.setFont("Helvetica-Bold", 18)
        c.drawString(1 * inch, PAGE_H - 1.3 * inch, f"Chapter {page}: Sources")

        y = PAGE_H - 1.9 * inch
        c.setFont("Helvetica", 11)
        base = (page - 1) * 3
        for i in range(3):
            marker = str(base + i + 1)
            c.drawString(1 * inch, y, f"Claim number {i + 1} on this page requires support")
            c.setFont("Helvetica", 7)
            c.drawString(4.72 * inch, y + 0.05 * inch, marker)
            c.setFont("Helvetica", 11)
            c.drawString(4.85 * inch, y, "and continues.")
            y -= 0.34 * inch

        c.setFont("Helvetica", 8)
        note_y = 1.25 * inch
        for i in range(3):
            marker = str(base + i + 1)
            c.drawString(1 * inch, note_y, f"{marker} Source citation number {marker}, page {page}.")
            note_y -= 0.16 * inch
        c.showPage()

    c.save()
    return path


# --------------------------------------------------------------------------
# D. Scanned book — real text rendered to raster, optionally rotated
# --------------------------------------------------------------------------

SCANNED_LINES = [
    "The Recovered Manuscript",
    "",
    "This page exists only as a scanned image and has no",
    "embedded text layer whatsoever. Optical character",
    "recognition is the only way to read these words.",
    "",
    "A second paragraph follows the first one here.",
]


def build_scanned_book(path: Path, rotate: int = 0, pages: int = 2) -> Path:
    """Render text to a raster, then embed that raster as the only page content."""
    out = fitz.open()
    for page_index in range(pages):
        source = fitz.open()
        src_page = source.new_page(width=PAGE_W, height=PAGE_H)
        y = 120
        for line in SCANNED_LINES:
            if line:
                size = 20 if line == SCANNED_LINES[0] and page_index == 0 else 13
                src_page.insert_text((80, y), line, fontsize=size)
            y += 30
        src_page.insert_text((80, y + 20), f"Page {page_index + 1} of the scan.", fontsize=13)
        pix = src_page.get_pixmap(dpi=200)
        source.close()

        page = out.new_page(width=PAGE_W, height=PAGE_H)
        page.insert_image(page.rect, pixmap=pix, rotate=rotate)
    out.save(str(path))
    out.close()
    return path


# --------------------------------------------------------------------------
# E. Mixed native + scanned pages in one document
# --------------------------------------------------------------------------

def build_mixed_native_and_scanned(path: Path) -> Path:
    out = fitz.open()

    native = out.new_page(width=PAGE_W, height=PAGE_H)
    native.insert_text((72, 100), "Chapter One: Native Text", fontsize=20)
    native.insert_text((72, 140), "This page has a genuine embedded text layer that", fontsize=11)
    native.insert_text((72, 158), "must be extracted deterministically without OCR.", fontsize=11)

    source = fitz.open()
    src_page = source.new_page(width=PAGE_W, height=PAGE_H)
    src_page.insert_text((80, 120), "Chapter Two: Scanned Text", fontsize=20)
    src_page.insert_text((80, 170), "This page is an image and requires OCR to read.", fontsize=14)
    src_page.insert_text((80, 200), "It follows a page that did not need OCR at all.", fontsize=14)
    pix = src_page.get_pixmap(dpi=200)
    source.close()

    scanned = out.new_page(width=PAGE_W, height=PAGE_H)
    scanned.insert_image(scanned.rect, pixmap=pix)

    out.save(str(path))
    out.close()
    return path


# --------------------------------------------------------------------------
# F. Table-heavy document — ruled grid so geometry detection has real lines
# --------------------------------------------------------------------------

def build_table_document(path: Path) -> Path:
    c = canvas.Canvas(str(path), pagesize=LETTER)
    c.setTitle("Quarterly Figures")

    _header_footer(c, 1, "Quarterly Figures")
    c.setFont("Helvetica-Bold", 18)
    c.drawString(1 * inch, PAGE_H - 1.3 * inch, "Results")

    c.setFont("Helvetica", 10)
    c.drawString(1 * inch, PAGE_H - 1.75 * inch, "Table 1. Revenue by region and quarter.")

    headers = ["Region", "Q1", "Q2", "Q3"]
    rows = [
        ["North", "120", "135", "150"],
        ["South", "98", "104", "119"],
        ["East", "76", "88", "91"],
        ["West", "141", "150", "162"],
    ]

    x0, y0 = 1 * inch, PAGE_H - 2.1 * inch
    col_w, row_h = 1.4 * inch, 0.32 * inch
    n_rows = len(rows) + 1

    # Ruled grid: PyMuPDF's table finder keys off these vector lines.
    c.setLineWidth(0.75)
    for r in range(n_rows + 1):
        y = y0 - r * row_h
        c.line(x0, y, x0 + col_w * len(headers), y)
    for col in range(len(headers) + 1):
        x = x0 + col * col_w
        c.line(x, y0, x, y0 - row_h * n_rows)

    c.setFont("Helvetica-Bold", 10)
    for col, head in enumerate(headers):
        c.drawString(x0 + col * col_w + 6, y0 - row_h + 10, head)
    c.setFont("Helvetica", 10)
    for r, row in enumerate(rows, start=1):
        for col, value in enumerate(row):
            c.drawString(x0 + col * col_w + 6, y0 - (r + 1) * row_h + 10, value)

    c.setFont("Helvetica", 11)
    c.drawString(1 * inch, y0 - row_h * (n_rows + 2), "The table above summarizes regional revenue.")
    c.showPage()
    c.save()
    return path


# --------------------------------------------------------------------------
# G. Formula-heavy document
# --------------------------------------------------------------------------

def build_formula_document(path: Path) -> Path:
    font = _ensure_unicode_font()
    c = canvas.Canvas(str(path), pagesize=LETTER)
    c.setTitle("Notes on Mechanics")

    _header_footer(c, 1, "Notes on Mechanics", font)
    c.setFont(font, 18)
    c.drawString(1 * inch, PAGE_H - 1.3 * inch, "Chapter 1: Energy")

    c.setFont(font, 11)
    c.drawString(1 * inch, PAGE_H - 1.8 * inch, "The mass-energy equivalence is written as follows.")

    # Simple relation the transcriber can represent faithfully in MathML.
    c.setFont(font, 13)
    c.drawCentredString(PAGE_W / 2, PAGE_H - 2.3 * inch, "E = mc2")
    c.setFont(font, 10)
    c.drawRightString(PAGE_W - 1 * inch, PAGE_H - 2.3 * inch, "(1.1)")

    c.setFont(font, 11)
    c.drawString(1 * inch, PAGE_H - 2.8 * inch, "A more involved expression appears below.")

    # Genuinely complex: must become an image, never guessed MathML.
    c.setFont(font, 14)
    c.drawCentredString(PAGE_W / 2, PAGE_H - 3.4 * inch, "∫₀^∞ e^(−x²) dx = √π ⁄ 2")
    c.setFont(font, 10)
    c.drawRightString(PAGE_W - 1 * inch, PAGE_H - 3.4 * inch, "(1.2)")

    c.setFont(font, 11)
    c.drawString(1 * inch, PAGE_H - 3.9 * inch, "Both equations are numbered for later reference.")
    c.showPage()
    c.save()
    return path


# --------------------------------------------------------------------------
# H. Endnote-heavy document — collected notes section, chapter-scoped numbering
# --------------------------------------------------------------------------

def build_endnote_document(path: Path) -> Path:
    c = canvas.Canvas(str(path), pagesize=LETTER)
    c.setTitle("The Collected Argument")
    c.setAuthor("E. Author")

    for chapter in (1, 2):
        _header_footer(c, chapter, "The Collected Argument")
        c.setFont("Helvetica-Bold", 20)
        c.drawString(1 * inch, PAGE_H - 1.3 * inch, f"Chapter {chapter}: The Argument")
        y = PAGE_H - 1.9 * inch
        c.setFont("Helvetica", 11)
        for i in (1, 2):
            c.drawString(1 * inch, y, f"A claim in chapter {chapter} that needs a note")
            c.setFont("Helvetica", 7)
            c.drawString(4.62 * inch, y + 0.05 * inch, str(i))
            c.setFont("Helvetica", 11)
            c.drawString(4.74 * inch, y, "and continues on.")
            y -= 0.4 * inch
        c.showPage()

    # Collected notes at the back, restarting numbering per chapter.
    _header_footer(c, 3, "The Collected Argument")
    c.setFont("Helvetica-Bold", 20)
    c.drawString(1 * inch, PAGE_H - 1.3 * inch, "Notes")
    y = PAGE_H - 1.85 * inch
    for chapter in (1, 2):
        c.setFont("Helvetica-Bold", 13)
        c.drawString(1 * inch, y, f"Chapter {chapter}")
        y -= 0.3 * inch
        c.setFont("Helvetica", 10)
        for i in (1, 2):
            c.drawString(
                1 * inch, y, f"{i}. Endnote {i} for chapter {chapter}, with a full citation."
            )
            y -= 0.26 * inch
        y -= 0.12 * inch
    c.showPage()
    c.save()
    return path


# --------------------------------------------------------------------------
# I. Poetry / verse
# --------------------------------------------------------------------------

POEM = [
    ("Because I could not stop for Death", 0),
    ("He kindly stopped for me", 1),
    ("The Carriage held but just Ourselves", 0),
    ("And Immortality", 1),
]
POEM_TWO = [
    ("We slowly drove he knew no haste", 0),
    ("And I had put away", 1),
    ("My labor and my leisure too", 0),
    ("For His Civility", 1),
]


def build_poetry_document(path: Path) -> Path:
    c = canvas.Canvas(str(path), pagesize=LETTER)
    c.setTitle("Selected Verse")
    c.setAuthor("A. Poet")

    _header_footer(c, 1, "Selected Verse")
    c.setFont("Helvetica-Bold", 20)
    c.drawString(1 * inch, PAGE_H - 1.3 * inch, "Selected Verse")

    y = PAGE_H - 2.0 * inch
    c.setFont("Helvetica", 12)
    for line, indent in POEM:
        c.drawString(1 * inch + indent * 0.28 * inch, y, line)
        y -= 0.26 * inch

    y -= 0.3 * inch
    for line, indent in POEM_TWO:
        c.drawString(1 * inch + indent * 0.28 * inch, y, line)
        y -= 0.26 * inch

    y -= 0.4 * inch
    c.setFont("Helvetica", 11)
    c.drawString(
        1 * inch, y, "This closing paragraph is ordinary prose that runs to the right margin"
    )
    y -= 0.2 * inch
    c.drawString(
        1 * inch, y, "of the page and therefore must not be mistaken for verse by the engine."
    )
    c.showPage()
    c.save()
    return path


# --------------------------------------------------------------------------
# J/K. RTL and mixed RTL/LTR
# --------------------------------------------------------------------------

ARABIC_LINES = [
    "هذا نص عربي يستخدم لاختبار اتجاه الكتابة من اليمين إلى اليسار.",
    "يجب أن يحافظ المحرك على الترتيب المنطقي للحروف والكلمات.",
]
HEBREW_LINE = "זהו טקסט בעברית לבדיקת כיוון הכתיבה."
MIXED_LINE = "النص العربي مع English words و 2024 أرقام."


def build_rtl_document(path: Path) -> Path:
    font = _ensure_unicode_font()
    c = canvas.Canvas(str(path), pagesize=LETTER)
    c.setTitle("وثيقة عربية")

    c.setFont(font, 20)
    c.drawRightString(PAGE_W - 1 * inch, PAGE_H - 1.3 * inch, "الفصل الأول")

    y = PAGE_H - 1.9 * inch
    c.setFont(font, 12)
    for line in ARABIC_LINES:
        c.drawRightString(PAGE_W - 1 * inch, y, line)
        y -= 0.3 * inch

    y -= 0.2 * inch
    c.drawRightString(PAGE_W - 1 * inch, y, HEBREW_LINE)
    c.showPage()
    c.save()
    return path


def build_mixed_direction_document(path: Path) -> Path:
    font = _ensure_unicode_font()
    c = canvas.Canvas(str(path), pagesize=LETTER)
    c.setTitle("Mixed Direction Document")

    c.setFont(font, 20)
    c.drawString(1 * inch, PAGE_H - 1.3 * inch, "Mixed Direction Chapter")

    y = PAGE_H - 1.9 * inch
    c.setFont(font, 12)
    c.drawString(1 * inch, y, "This paragraph is written in English and reads left to right.")
    y -= 0.35 * inch
    c.drawRightString(PAGE_W - 1 * inch, y, ARABIC_LINES[0])
    y -= 0.35 * inch
    c.drawRightString(PAGE_W - 1 * inch, y, MIXED_LINE)
    y -= 0.35 * inch
    c.drawString(1 * inch, y, "A final English paragraph closes the chapter here.")
    c.showPage()
    c.save()
    return path


# --------------------------------------------------------------------------
# L. Large native-text book (performance: must never trigger OCR)
# --------------------------------------------------------------------------

def build_large_book(path: Path, pages: int = 520) -> Path:
    """A long, purely native-text book. Used to prove a big book stays
    deterministic and never pays for OCR."""
    doc = fitz.open()
    for page_index in range(pages):
        page = doc.new_page(width=PAGE_W, height=PAGE_H)
        page.insert_text((PAGE_W / 2 - 60, 40), "The Long Book", fontsize=9)
        if page_index % 40 == 0:
            page.insert_text((72, 100), f"Chapter {page_index // 40 + 1}", fontsize=20)
            y = 150
        else:
            y = 100
        for line in range(28):
            page.insert_text(
                (72, y + line * 16),
                f"Page {page_index + 1} line {line + 1}: ordinary body text for the long book.",
                fontsize=10,
            )
        page.insert_text((PAGE_W / 2, PAGE_H - 40), str(page_index + 1), fontsize=9)
    doc.save(str(path))
    doc.close()
    return path


# --------------------------------------------------------------------------
# M. Scanned novel carrying its own OCR text layer
#
# Reproduces the *structure* of a real 348-page Turkish paperback that exposed
# several defects, using entirely invented prose. Characteristics that mattered:
#   - a full-page background scan image on every page, plus a complete embedded
#     text layer (so OCR must not re-read the book)
#   - almost no typographic variation in body text
#   - verso/recto alternating running heads
#   - page numbers whose digits OCR splits with a space ("4 1")
#   - soft hyphens (U+00AD) at justified line breaks
#   - chapter numbers set on their own line above the chapter title
#   - a handful of real footnotes, one with its marker welded to a word
# --------------------------------------------------------------------------

# Latin-only prose set in a built-in font: the structural properties under test
# (soft hyphens, split page numbers, alternating heads, welded note markers) are
# script-independent, and embedding a full Unicode face would add ~15MB to a
# fixture the suite rebuilds on every run.
_SCAN_BODY_SENTENCES = [
    "In the first hours of morning the streets stood empty and the wind blew",
    "softly past the windows stirring the curtains a little every time that",
    "it passed. A door closed somewhere far away and then the silence came",
    "back and settled in again. Nobody hurried at this hour and nobody spoke.",
]


def build_scanned_novel_with_text_layer(
    path: Path, pages: int = 46, chapter_pages: tuple[int, ...] = (6, 22, 36)
) -> Path:
    """A scanned-looking novel that already carries a usable text layer."""
    doc = fitz.open()

    # Small flat pixmap scaled to the page: the structural signal that matters
    # is full-page image coverage, not resolution, and a large raster would
    # make this fixture tens of megabytes.
    background = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 80, 112), False)
    background.clear_with(246)
    # Insert the same compressed PNG bytes on every page so the file stores one
    # image object rather than 46 copies of a raw pixmap.
    background_png = background.tobytes("png")
    background_xref = 0

    font = fitz.Font("helv")
    chapter_titles = {chapter_pages[0]: "Kurban", chapter_pages[1]: "Ben", chapter_pages[2]: "Bir"}
    note_pages = {12: "1", 28: "2"}

    for index in range(pages):
        page_no = index + 1
        page = doc.new_page(width=396, height=561)
        if index == 0:
            page.insert_image(page.rect, stream=background_png)
            background_xref = page.get_images(full=True)[0][0]
        else:
            # Reuse the already-embedded image rather than storing it again.
            page.insert_image(page.rect, xref=background_xref)
        writer = fitz.TextWriter(page.rect)

        # Alternating running head: title on one side, author on the other.
        # Chapter-opening pages carry no running head, as books conventionally
        # set them — and as the book this reproduces does.
        if page_no not in chapter_titles:
            head = "Seyir" if page_no % 2 == 0 else "Author Name"
            writer.append(fitz.Point(180, 20), head, font=font, fontsize=6.1)

        if page_no in chapter_titles:
            # Chapter number alone above the title, both in display type.
            writer.append(fitz.Point(190, 46), str(chapter_pages.index(page_no) + 1),
                          font=font, fontsize=28.9)
            writer.append(fitz.Point(150, 100), chapter_titles[page_no], font=font, fontsize=28.9)
            # Chapter epigraph, as in the book this reproduces: it is what keeps
            # an opening page above the "essentially empty" threshold.
            writer.append(
                fitz.Point(96, 140),
                "\"Everything is so because they are so . . .\"",
                font=font,
                fontsize=9.45,
            )
        else:
            y = 48
            for repeat in range(6):
                for line_index, sentence in enumerate(_SCAN_BODY_SENTENCES):
                    text = sentence
                    # Soft hyphen at a justified break, as a scanner emits.
                    if line_index == 1:
                        text = text[:-3] + "­"
                    writer.append(fitz.Point(28, y), text, font=font, fontsize=8.85)
                    y += 14.5
                y += 4
                if y > 480:
                    break

            if page_no in note_pages:
                marker = note_pages[page_no]
                # Marker welded to the preceding word, the way OCR emits it.
                writer.append(
                    fitz.Point(28, y), f"This claim rests upon a documented source{marker}",
                    font=font, fontsize=8.85,
                )
                writer.append(
                    fitz.Point(28, 505), f"{marker} The source note appears here in smaller type.",
                    font=font, fontsize=5.4,
                )

        # Page number with a space between digits, as OCR splits it.
        spaced = " ".join(str(page_no)) if page_no >= 10 else str(page_no)
        writer.append(fitz.Point(190, 543), spaced, font=font, fontsize=6.0)
        writer.write_text(page)

    doc.save(str(path), deflate=True, garbage=4)
    doc.close()
    return path


# --------------------------------------------------------------------------
# N. Turkish novel carrying a defective OCR text layer
#
# Encodes the defect profile measured from a real 348-page Turkish paperback,
# using invented prose. Each defect below was counted in that book:
#   - diacritics dropped by the scanner ("için" -> "icin")
#   - Turkish minimal pairs that must NOT be "corrected" (sakin/sakın)
#   - "rn" misread as "m" ("yaşamım" -> "yaşarnım")
#   - words split by a stray space ("Sırma" -> "S ırma")
#   - a space before punctuation, and a missing space after it
#   - literary ellipses, both spaced (". . .") and plain ("...")
#   - fi/fl ligatures
# --------------------------------------------------------------------------

# Sentences repeated enough to establish this document's vocabulary, the way a
# real book repeats its own words.
_TR_CORPUS_SENTENCES = [
    # "için" and "değil" are among the commonest words in Turkish prose; the
    # real book carried them 540 and 285 times against a single mis-scan each.
    "Bunu senin için yaptım ve her şey için teşekkür ederim.",
    "Onun için geldim, senin için kaldım, bizim için bekledim.",
    "Bu iş değil, bu bir yaşam biçimi değil mi diye sordum.",
    "Kolay değil, hiç değil, asla değil diye tekrarladı.",
    "Yaşamım boyunca hep aynı şeyi düşündüm ve yaşamım değişti.",
    "Sırma bana baktı ve Sırma gülümsedi, sonra Sırma gitti.",
    "Nefes almak için durdum, nefes verdim, yine nefes aldım.",
]
# The other half of each Turkish minimal pair, at a realistic frequency: common
# enough to tempt a frequency-only corrector, not so common that the ratio test
# alone would save us. These appear on a few pages, not every page.
_TR_MINIMAL_PAIR_COUNTERPARTS = [
    "Sakın oraya gitme dedi bana.",
    "Kapıyı açıyorum ve içeri giriyorum.",
    "O kişi geldi ve bekledi.",
]
# Words whose correct forms the corpus establishes, paired with the way the
# scanner mangled them on one page.
_TR_DEFECTS = [
    ("Bunu senin icin yaptım.", "dropped cedilla: icin -> için"),
    ("Bu is degil dedi bana.", "dropped diacritics: degil -> değil"),
    ("Yaşarnım boyunca böyle oldu.", "rn misread as m"),
    ("Sonra S ırma içeri girdi.", "stray space inside a word"),
    ("Durdum ve n efes aldım.", "stray space inside a word"),
]
# Sentences that must survive untouched: real Turkish words a frequency-only
# corrector would happily replace with a different real word.
_TR_MUST_NOT_CHANGE = [
    "Çok sakin bir adam olduğunu düşündüm.",   # sakin (calm) vs sakın (beware)
    "Ona çok acıyorum, gerçekten üzgünüm.",     # acıyorum (I pity) vs açıyorum
    "Kışı burada geçirmek istiyorum artık.",    # kışı (its winter) vs kişi
]


def build_turkish_ocr_novel(path: Path, pages: int = 30) -> Path:
    """A Turkish novel whose text layer carries realistic OCR damage."""
    doc = fitz.open()
    font_path = _UNICODE_FONT_PATH if unicode_font_available() else None
    font = fitz.Font(fontfile=font_path) if font_path else fitz.Font("helv")

    for index in range(pages):
        page_no = index + 1
        page = doc.new_page(width=396, height=561)
        writer = fitz.TextWriter(page.rect)
        # Body text starts below the header band (12% of page height). Starting
        # higher would put identical prose in the running-head zone on every
        # page, where furniture detection would rightly strip it.
        y = 95.0

        # Alternating running head, omitted on the opening page.
        if page_no > 1:
            head = "Seyir" if page_no % 2 == 0 else "Yazar"
            writer.append(fitz.Point(180, 20), head, font=font, fontsize=6.1)

        if page_no == 1:
            writer.append(fitz.Point(150, 60), "1", font=font, fontsize=28.9)
            writer.append(fitz.Point(120, 110), "Başlangıç", font=font, fontsize=28.9)
            y = 170.0

        # Vocabulary-establishing prose on every page.
        for sentence in _TR_CORPUS_SENTENCES:
            writer.append(fitz.Point(28, y), sentence, font=font, fontsize=8.85)
            y += 15

        if page_no == 3:
            for damaged, _why in _TR_DEFECTS:
                writer.append(fitz.Point(28, y), damaged, font=font, fontsize=8.85)
                y += 15
        if page_no % 4 == 0:
            for line in _TR_MINIMAL_PAIR_COUNTERPARTS:
                writer.append(fitz.Point(28, y), line, font=font, fontsize=8.85)
                y += 15
        if page_no == 5:
            for keep in _TR_MUST_NOT_CHANGE:
                writer.append(fitz.Point(28, y), keep, font=font, fontsize=8.85)
                y += 15
        if page_no == 7:
            # Punctuation damage plus legitimate literary ellipses.
            for line in (
                "Merhaba , nasılsın ?",
                "Bir,iki,üç diye saydı.",
                "Ne yapacağımı bilmiyorum...",
                "Belki de . . . belki hiç.",
                "Gerçekten mi??",
            ):
                writer.append(fitz.Point(28, y), line, font=font, fontsize=8.85)
                y += 15
        if page_no == 9:
            # Ligatures and a line-break hyphen, both as a scanner emits them.
            writer.append(fitz.Point(28, y), "Ofis dosyası ﬁrmanın eﬂatun raporu.", font=font, fontsize=8.85)
            y += 15
            writer.append(fitz.Point(28, y), "Uzun bir cümlenin ya­", font=font, fontsize=8.85)
            y += 15
            writer.append(fitz.Point(28, y), "şam boyu süren etkisi vardır.", font=font, fontsize=8.85)
            y += 15
            # A real hyphenated word that must never be merged.
            writer.append(fitz.Point(28, y), "Türk-Amerikan ilişkileri ve e-posta adresi.", font=font, fontsize=8.85)
            y += 15

        spaced = " ".join(str(page_no)) if page_no >= 10 else str(page_no)
        writer.append(fitz.Point(190, 543), spaced, font=font, fontsize=6.0)
        writer.write_text(page)

    doc.save(str(path), deflate=True, garbage=4)
    doc.close()
    return path


BUILDERS = {
    "turkish_novel": build_turkish_novel,
    "two_column_academic": build_two_column_academic,
    "footnote_heavy": build_footnote_heavy,
    "scanned_book": build_scanned_book,
    "mixed_native_scanned": build_mixed_native_and_scanned,
    "table_document": build_table_document,
    "formula_document": build_formula_document,
    "endnote_document": build_endnote_document,
    "poetry_document": build_poetry_document,
    "rtl_document": build_rtl_document,
    "mixed_direction": build_mixed_direction_document,
}


def build_all(directory: Path) -> dict[str, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    built = {}
    for name, builder in BUILDERS.items():
        target = directory / f"{name}.pdf"
        builder(target)
        built[name] = target
    return built


if __name__ == "__main__":
    out = Path(__file__).parent / "corpus"
    for name, target in build_all(out).items():
        print(f"wrote {name}: {target.stat().st_size} bytes")
