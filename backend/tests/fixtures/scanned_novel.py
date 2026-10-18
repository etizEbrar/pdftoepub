"""A scanned novel with its scanner's OCR text layer, the way a real one arrives.

Modelled on a 327-page Turkish novel whose conversion read badly: the page
image behind every page went into the EPUB as a picture, page numbers set as
"• 12 •" and a letter-spaced running head stayed in the text, each chapter
opened on its drop cap as a paragraph of its own and on its ornament read as a
letter in 75-point type, and the display titles came through as "BİL6İ5AYAR".
"""

from __future__ import annotations

from pathlib import Path

import fitz

PAGE = fitz.Rect(0, 0, 383, 573)
TEXT = fitz.Rect(47, 60, 340, 530)
RUNNING_HEADS = ("KÜÇÜK KASABA", "KÜÇ ÜK KASABA", "K Ü Ç Ü K KASABA")
BOOK_TITLE = "KÜÇÜK KASABA"
# What the scanner read, and what was printed.
CHAPTERS = (
    ("ADAM VE BİL6İSAYAR", "ADAM VE BİLGİSAYAR"),
    ("ADAM VE KEDİ", "ADAM VE KEDİ"),
    ("ADAM VE TREN", "ADAM VE TREN"),
)
FIRST_WORDS = "Ove elli dokuz yaşında"

_SENTENCES = (
    "Ove her sabah bilgisayar dükkânının önünden geçer ve kedi ile karşılaşırdı.",
    "Komşuları onun huysuz bir adam olduğunu düşünse de Ove kurallara uyardı.",
    "Tren istasyonunda bekleyen insanlar saatlerine bakıp söylenirdi.",
    "Bilgisayar almak için gittiği dükkânda satış görevlisi ona baktı.",
)


def _paragraph(index: int, sentences: int = 5) -> str:
    return " ".join(_SENTENCES[(index + i) % len(_SENTENCES)] for i in range(sentences))


def _background(page: fitz.Page) -> None:
    """The page as the scanner saw it: white paper and a smudge."""
    scan = fitz.Pixmap(fitz.csGRAY, fitz.IRect(0, 0, 383, 573), False)
    scan.clear_with(250)
    scan.set_rect(fitz.IRect(175, 70, 205, 95), (30,))
    page.insert_image(page.rect, pixmap=scan)


_BODY_CSS = "p{font-size:10.5pt;text-align:justify;text-indent:20pt;margin:0;line-height:1.4}"


def _put(page: fitz.Page, rect: fitz.Rect, html: str, css: str | None = None) -> None:
    """Set text at its true size: MuPDF would otherwise shrink it to fit the box."""
    spare, _ = page.insert_htmlbox(rect, html, css=css or "p{margin:0}", scale_low=1)
    assert spare >= 0, f"text does not fit {rect}: {html[:40]}"


def build_scanned_novel(path: Path) -> Path:
    doc = fitz.open()

    cover = doc.new_page(width=PAGE.width, height=PAGE.height)
    art = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 383, 573), False)
    art.clear_with(180)
    art.set_rect(fitz.IRect(40, 40, 340, 300), (30, 60, 120))
    cover.insert_image(cover.rect, pixmap=art)

    title_page = doc.new_page(width=PAGE.width, height=PAGE.height)
    _put(title_page, fitz.Rect(20, 180, 363, 260), f"<p style='font-size:30pt;text-align:center'>{BOOK_TITLE}</p>")

    folio = 0
    paragraph = 0
    for number, (read, _printed) in enumerate(CHAPTERS, start=1):
        opener = doc.new_page(width=PAGE.width, height=PAGE.height)
        _background(opener)
        folio += 1
        _put(opener, fitz.Rect(141, 40, 241, 70), f"<p style='font-size:15pt;text-align:center'>{number}</p>")
        # The ornament under the number, read by the scanner as a letter.
        _put(opener, fitz.Rect(141, 62, 241, 160), "<p style='font-size:70pt;text-align:center'>a</p>")
        _put(opener, fitz.Rect(20, 165, 363, 200), f"<p style='font-size:18pt;text-align:center'>{read}</p>")
        _put(opener, fitz.Rect(47, 228, 77, 278), "<p style='font-size:32pt'>O</p>")
        _put(opener, fitz.Rect(70, 236, 340, 256), "<p style='font-size:10.5pt'>,ve elli dokuz yaşında.</p>")
        _put(opener, fitz.Rect(47, 262, 340, 530), f"<p>{_paragraph(paragraph)}</p>", css=_BODY_CSS)
        paragraph += 1
        _put(opener, fitz.Rect(141, 540, 241, 562), f"<p style='font-size:8.5pt;text-align:center'>• {folio} •</p>")

        for _ in range(2):
            page = doc.new_page(width=PAGE.width, height=PAGE.height)
            _background(page)
            folio += 1
            head = RUNNING_HEADS[folio % len(RUNNING_HEADS)]
            _put(page, fitz.Rect(40, 20, 343, 40), f"<p style='font-size:8.5pt;text-align:center'>{head}</p>")
            body = "".join(f"<p>{_paragraph(paragraph + i)}</p>" for i in range(3))
            paragraph += 3
            _put(page, TEXT, body, css=_BODY_CSS)
            spaced = " ".join(str(folio))
            _put(page, fitz.Rect(141, 540, 241, 562), f"<p style='font-size:8.5pt;text-align:center'>• {spaced} *</p>")

    doc.set_metadata({"title": "", "author": ""})
    doc.save(str(path))
    doc.close()
    return path
