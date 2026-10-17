"""An edited academic volume, typeset the way a Turkish publisher sets one.

Modelled on a real 168-page book whose conversion read badly: every paragraph
that crossed a page was cut in two at the running head, bold section headings
at body size were glued to the paragraph after them, the printed contents came
through with its leader dots, and the bibliography was merged and split at
random. The text is flowed by MuPDF's own layout engine, so page breaks fall
mid-paragraph on full justified lines exactly as they do in print.

Each paragraph opens with "alfaN" and closes with "omegaN", so a test can tell
whether any paragraph was split or merged wherever the breaks happened to land.
"""

from __future__ import annotations

from pathlib import Path

import fitz

PAGE = fitz.Rect(0, 0, 396, 612)
TEXT_AREA = fitz.Rect(51, 72, 400, 540)
TITLE = "MÜHENDİSLİKTE YENİ YAKLAŞIMLAR"
RUNNING_HEAD = "Mühendislikte Yeni Yaklaşımlar"

_WORDS = (
    "veri yapıları bilgisayar biliminin temel yapı taşlarından biridir ve yazılım "
    "geliştirme sürecinin önemli bir parçasını oluşturur bu çalışmada farklı yöntemler "
    "karşılaştırılmış ve elde edilen sonuçlar ayrıntılı olarak değerlendirilmiştir"
).split()

CHAPTERS = (
    ("BÖLÜM 1", "VERİ YAPILARI ÜZERİNE BİR İNCELEME", "Ayşe YILMAZ"),
    ("BÖLÜM 2", "RÜZGÂR ENERJİSİ VE DENİZ ÜSTÜ TÜRBİNLER", "Mehmet KAYA"),
)
LONG_SECTION = "1.1. Veri Yapılarının Bellek Kullanımı Üzerindeki Etkileri"
PARAGRAPHS_PER_SECTION = 3
REFERENCES = (
    "Cormen, T. H., Leiserson, C. E., Rivest, R. L., & Stein, C. (2009). Introduction "
    "to Algorithms. MIT Press, Cambridge, Massachusetts, United States of America",
    "Goodrich, M. T., Tamassia, R., & Goldwasser, M. H. (2014). Data Structures and "
    "Algorithms in Java. Wiley, Hoboken, New Jersey. https://doi.org/10.1000/example.2014",
    "Knuth, D. E. (1997). The Art of Computer Programming, Volume 1: Fundamental "
    "Algorithms. Addison-Wesley, Reading, Massachusetts.",
)


def _paragraph(number: int, words: int = 120) -> str:
    body = " ".join(_WORDS[(number + i) % len(_WORDS)] for i in range(words))
    return f"alfa{number} {body} omega{number}."


def paragraph_count() -> int:
    return len(CHAPTERS) * 2 * PARAGRAPHS_PER_SECTION


_CSS = """
p { font-size: 11pt; text-align: justify; text-indent: 28pt; margin: 0 0 3pt 0; line-height: 1.35; }
.title { font-size: 26pt; font-weight: bold; text-align: center; text-indent: 0; margin-top: 160pt; }
.small { font-size: 9pt; text-align: center; text-indent: 0; margin: 0 0 2pt 0; }
.toc-head { font-weight: bold; text-indent: 0; margin: 10pt 0 2pt 0; }
.toc-line { font-style: italic; text-indent: 0; margin: 0 0 6pt 0; }
.division { font-size: 14pt; font-weight: bold; text-align: right; text-indent: 0; margin-top: 120pt; }
.chapter-title { font-size: 12pt; font-weight: bold; text-align: right; text-indent: 0; margin: 4pt 0 6pt 0; }
.byline { text-align: right; text-indent: 0; margin: 0 0 30pt 0; }
.section { font-size: 12pt; font-weight: bold; text-indent: 0; margin: 12pt 0 8pt 0; }
.reference { text-indent: -24pt; padding-left: 24pt; text-align: justify; margin: 0 0 3pt 0; }
.break { page-break-before: always; }
"""


def _html() -> str:
    parts = [f'<p class="title">{TITLE}</p>']
    parts.append(
        '<p class="small break">Copyright © 2024 by Example Press. All rights reserved. '
        "No part of this publication may be reproduced without permission.</p>"
        '<p class="small">ISBN: 978-0-00-000000-0</p>'
    )
    parts.append('<p class="toc-head break">İÇİNDEKİLER</p>')
    for index, (division, title, author) in enumerate(CHAPTERS):
        parts.append(f'<p class="toc-head">{division}<br/>{title}</p>')
        parts.append(f'<p class="toc-line">{author} {"." * 60} {5 + index * 6}</p>')
    number = 0
    for chapter_index, (division, title, author) in enumerate(CHAPTERS):
        parts.append(f'<p class="division break">{division}</p>')
        parts.append(f'<p class="chapter-title">{title}</p>')
        if chapter_index == 0:
            parts.append(f'<p class="byline" style="margin:0">{author}<sup>1</sup></p>')
            parts.append('<p class="byline">Ali DEMİR<sup>2</sup></p>')
        else:
            parts.append(f'<p class="byline">{author}</p>')
        sections = ["GİRİŞ", LONG_SECTION] if chapter_index == 0 else ["GİRİŞ", "SONUÇ"]
        for section in sections:
            parts.append(f'<p class="section">{section}</p>')
            for _ in range(PARAGRAPHS_PER_SECTION):
                number += 1
                parts.append(f"<p>{_paragraph(number)}</p>")
        parts.append('<p class="section">KAYNAKÇA</p>')
        for reference in REFERENCES:
            parts.append(f'<p class="reference">{reference}</p>')
    return "".join(parts)


def build_edited_volume(path: Path) -> Path:
    story = fitz.Story(html=_html(), user_css=_CSS)
    writer = fitz.DocumentWriter(str(path))
    more = 1
    while more:
        device = writer.begin_page(PAGE)
        more, _ = story.place(TEXT_AREA)
        story.draw(device)
        writer.end_page()
    writer.close()

    doc = fitz.open(str(path))
    # Running heads alternate sides with the folio, as in print; the title and
    # copyright pages carry none.
    for index in range(2, doc.page_count):
        page = doc[index]
        folio = index - 1
        head = f"{folio} | {RUNNING_HEAD}" if folio % 2 else f"{RUNNING_HEAD} | {folio}"
        page.insert_htmlbox(
            fitz.Rect(51, 36, 400, 52),
            f'<p style="font-size:9pt;font-style:italic;text-align:{"left" if folio % 2 else "right"}">{head}</p>',
        )
    # The first chapter's opening page carries two author notes, stacked in
    # one block, the first long enough to wrap.
    opener = next(
        i
        for i in range(doc.page_count)
        if CHAPTERS[0][1] in doc[i].get_text().replace("\n", " ")
        and "İÇİNDEKİLER" not in doc[i].get_text()
    )
    doc[opener].insert_htmlbox(
        fitz.Rect(51, 520, 400, 580),
        '<p style="font-size:8.5pt;text-align:left;margin:0">'
        "1 Örnek Üniversitesi, Mühendislik Fakültesi, Bilgisayar Mühendisliği Bölümü, "
        "Ankara, Türkiye. ayse@example.edu.tr<br/>"
        "2 Örnek Üniversitesi, Fen Fakültesi, Ankara, Türkiye.</p>",
    )
    doc.set_metadata({"title": "ÖNK", "author": ""})
    output = path.with_suffix(".tmp.pdf")
    doc.save(str(output))
    doc.close()
    output.replace(path)
    return path
