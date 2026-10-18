"""A scanned novel's OCR text layer, read as a book.

Each case is a defect a real 327-page Turkish novel shipped with. Its PDF was
a scan with a text layer from the scanner's OCR: every printed line a block of
its own, the page itself an image behind the text, chapter openings set with a
number, an ornament, a display-type title and a drop cap.
"""

from __future__ import annotations

from pathlib import Path

import fitz

from app.models.document import Block, BlockRole, Span, StructuralNode
from app.pipeline import analyze, headers_footers, images, openers, structure, textrepair
from app.pipeline.epub.builder import Chapter, _raise_chapter_headings
from app.pipeline.paragraphs import _continues, _Geometry
from app.pipeline.verse import detect_verse

PAGE_W, PAGE_H = 383.0, 573.0
LEFT, RIGHT = 47.0, 340.0
BODY = 10.5


def _block(block_id, lines, page=1, size=BODY):
    """`lines` is a list of (text, x0, y0, x1) or (text, x0, y0, x1, size)."""
    spans = []
    for line in lines:
        text, x0, y0, x1 = line[:4]
        line_size = line[4] if len(line) > 4 else size
        spans.append(
            Span(
                text=text,
                bbox=(x0, y0, x1, y0 + line_size * 1.05),
                font="Sylfaen",
                font_size=line_size,
                bold=False,
                italic=False,
                baseline=y0 + line_size,
                line_break_after=True,
            )
        )
    return Block(
        block_id=block_id,
        page=page,
        page_width=PAGE_W,
        page_height=PAGE_H,
        bbox=(
            min(s.bbox[0] for s in spans),
            min(s.bbox[1] for s in spans),
            max(s.bbox[2] for s in spans),
            max(s.bbox[3] for s in spans),
        ),
        kind="text",
        text="\n".join(line[0] for line in lines),
        spans=spans,
        font="Sylfaen",
        font_size=max(s.font_size for s in spans),
    )


def _prose(page, words, start=1, count=6, y=300.0):
    """Ordinary body lines that put the given words into the book's vocabulary."""
    return [
        _block(f"p{page}_prose{i}", [(f"{words} satır {i} burada yazıyor", LEFT, y + i * 16, RIGHT)], page=page)
        for i in range(start, start + count)
    ]


# --- page furniture ---------------------------------------------------------


def _furniture_pages(head_for, folio_for, pages=range(1, 11)):
    blocks_by_page = {}
    for page in pages:
        blocks_by_page[page] = [
            _block(f"p{page}_head", [(head_for(page), 114, 27, 269, 8.5)], page=page),
            _block(f"p{page}_body", [(f"Sayfa {page} için kendine özgü bir metin.", LEFT, 200, RIGHT)], page=page),
            _block(f"p{page}_folio", [(folio_for(page), 180, 550, 202, 8.5)], page=page),
        ]
    return blocks_by_page


def test_page_numbers_dressed_in_ornaments_are_page_numbers():
    ornaments = ["• {} •", "• {}-", "{} *", ". {} .", "•{} •", "* {} •"]

    def folio(page):
        spaced = " ".join(str(page + 100))
        return ornaments[page % len(ornaments)].format(spaced)

    furniture = headers_footers.detect_furniture(_furniture_pages(lambda p: "ROMAN", folio))
    for page in range(1, 11):
        assert furniture.get(f"p{page}_folio") == BlockRole.PAGE_NUMBER, folio(page)
        assert f"p{page}_body" not in furniture


def test_a_letter_spaced_running_head_is_one_head_however_ocr_spaced_it():
    spellings = ["HAYATA RÖVEŞATA ÇEKEN ADAM", "HAYATA RÖVEŞATA ÇEK EN ADAM", "HAYATA RÖVEŞATA Ç E K E N ADAM"]
    furniture = headers_footers.detect_furniture(
        _furniture_pages(lambda p: spellings[p % 3], lambda p: str(p))
    )
    for page in range(1, 11):
        assert furniture.get(f"p{page}_head") == BlockRole.HEADER


def test_a_running_head_misread_on_one_page_is_still_the_head():
    def head(page):
        return "FREDRIGK BACKMAN" if page == 6 else "FREDRIK BACKMAN"

    furniture = headers_footers.detect_furniture(_furniture_pages(head, lambda p: str(p)))
    assert furniture.get("p6_head") == BlockRole.HEADER


# --- chapter openings -------------------------------------------------------


def _opening(page, number_lines, title, first_line, cap=None, extra=()):
    """A chapter opening: number/ornament lines above a display title, then text."""
    blocks = []
    if number_lines:
        blocks.append(_block(f"p{page}_num", number_lines, page=page))
    blocks.append(_block(f"p{page}_title", [(line, 90, 155 + i * 24, 290, 18.0) for i, line in enumerate(title)], page=page))
    if cap:
        blocks.append(_block(f"p{page}_cap", [(cap, LEFT, 243, 65, 32.0)], page=page))
    blocks.append(_block(f"p{page}_first", [(first_line, 66 if cap else LEFT + 20, 244, RIGHT)], page=page))
    blocks.extend(extra)
    blocks.extend(_prose(page, "Ove ve Sonja bilgisayar ile bazı şeyler"))
    return blocks


def _run_openings(blocks_by_page):
    removed, report = openers.repair_openings(blocks_by_page, {}, BODY)
    by_id = {b.block_id: b for blocks in blocks_by_page.values() for b in blocks}
    return removed, report, by_id


def test_a_drop_cap_rejoins_its_word_and_its_debris_is_dropped():
    blocks_by_page = {7: _opening(7, None, ["OVE DENEN ADAM"], ", ve elli dokuz yaşında.", cap="O")}
    removed, report, by_id = _run_openings(blocks_by_page)
    assert by_id["p7_first"].text == "Ove elli dokuz yaşında."
    assert "p7_cap" in removed
    assert report.drop_caps == 1


def test_a_drop_cap_that_is_a_word_of_its_own_stays_one():
    blocks_by_page = {
        7: _opening(7, None, ["OVE DENEN ADAM"], "gün geldiğinde her şey değişti.", cap="O")
        + _prose(7, "o gün o gün", start=10)
    }
    _, _, by_id = _run_openings(blocks_by_page)
    assert by_id["p7_first"].text == "O gün geldiğinde her şey değişti."


def test_a_large_digit_beside_text_is_not_taken_for_a_drop_cap():
    blocks_by_page = {7: _opening(7, None, ["OVE DENEN ADAM"], "madde burada anlatılıyor.", cap="1")}
    removed, _, by_id = _run_openings(blocks_by_page)
    assert "p7_cap" not in removed
    assert by_id["p7_first"].text.startswith("madde")


def test_chapter_numbers_are_checked_against_their_neighbours():
    pages = {
        # "1" with the chapter's ornament read into the same block, in 75-point type.
        10: [("1", 186, 53, 198, 15.5), ("a", 166, 48, 220, 75.7)],
        20: None,  # the scanner missed the number altogether
        30: [("3", 186, 53, 198, 15.5)],
        40: [("M", 186, 53, 198, 15.5)],  # misread
        50: [("5", 186, 53, 198, 15.5)],
    }
    blocks_by_page = {
        page: _opening(page, lines, ["OVE DENEN ADAM", "VE BİR BİLGİSAYAR"], "Ove bir şey söyledi.")
        for page, lines in pages.items()
    }
    removed, report, by_id = _run_openings(blocks_by_page)
    titles = [by_id[f"p{page}_title"].text.split("\n")[0] for page in pages]
    assert titles == [f"{n} OVE DENEN ADAM" for n in (1, 2, 3, 4, 5)]
    assert report.inferred_numbers == 2
    assert {"p10_num", "p30_num", "p40_num", "p50_num"} <= removed


def test_an_ornament_read_as_letters_above_a_title_is_dropped():
    ornament = _block("p9_ornament", [("mrnrnm", 136, 114, 230)], page=9)
    blocks_by_page = {9: _opening(9, None, ["OVE DENEN ADAM"], "Ove geldi.", extra=[ornament])}
    removed, _, _ = _run_openings(blocks_by_page)
    assert "p9_ornament" in removed


def test_an_authors_name_above_a_title_is_not_an_ornament():
    name = _block("p9_name", [("FREDRIK BACKMAN", 120, 60, 260, 17.0)], page=9)
    blocks_by_page = {9: _opening(9, None, ["HAYATA ROVEŞATA", "ÇEKEN ADAM"], "Ove geldi.", extra=[name])}
    removed, _, _ = _run_openings(blocks_by_page)
    assert "p9_name" not in removed


def test_a_chapter_that_lost_its_drop_cap_gets_its_capital_back():
    second = _block("p74_second", [("1 ve Ove de bunu biliyordu.", 65, 259, RIGHT)], page=74)
    blocks_by_page = {
        74: _opening(74, None, ["BİR ZAMANLAR OVE OLAN ADAM"], "^  onja kadere inanırdı.", extra=[second])
    }
    _, report, by_id = _run_openings(blocks_by_page)
    assert by_id["p74_first"].text == "Sonja kadere inanırdı."
    assert by_id["p74_second"].text == "ve Ove de bunu biliyordu."
    assert report.mended_openings == 1


def test_a_dialogue_that_lost_its_drop_cap_gets_its_quotation_mark_back():
    blocks_by_page = {
        238: _opening(238, None, ["OVE DENEN ADAM"], "ahiden nereye gidiyoruz?” diye sordu.")
        + _prose(238, "sahiden sahiden", start=10)
    }
    _, _, by_id = _run_openings(blocks_by_page)
    assert by_id["p238_first"].text == "“Sahiden nereye gidiyoruz?” diye sordu."


def test_a_chapter_opening_with_its_capital_is_left_alone():
    blocks_by_page = {11: _opening(11, None, ["OVE DENEN ADAM"], "O gün Ove erken kalktı.")}
    _, report, by_id = _run_openings(blocks_by_page)
    assert by_id["p11_first"].text == "O gün Ove erken kalktı."
    assert report.mended_openings == 0


def test_digits_misread_in_a_display_title_are_restored_from_the_books_words(monkeypatch, tmp_path):
    monkeypatch.setattr(openers, "tesseract_available", lambda: False)
    title = _block("p7_title", [("OVE DENEN ADAM, BİL6İ5AYAR", 90, 155, 290, 18.0), ("VE BİR 6EY", 90, 179, 290, 18.0)], page=7)
    vocabulary = _prose(7, "Ove denen adam bir bilgisayar ve bir şey") + _prose(8, "bilgisayar şey şey adam")
    corrected = openers.reread_titles([title], lambda page: None, vocabulary + [title], "tur", tmp_path)
    assert title.text == "OVE DENEN ADAM, BİLGİSAYAR\nVE BİR ŞEY"
    assert corrected == 2


def test_a_digit_in_an_unknown_word_is_left_as_printed():
    vocab = textrepair.DocumentVocabulary(_prose(1, "Saab bir araba"))
    assert openers._restore_glyphs("9000i", vocab) == "9000i"
    assert openers._restore_glyphs("MP3", vocab) == "MP3"


# --- prose a scanner cut into lines ------------------------------------------


def test_dialogue_set_line_by_line_is_not_verse():
    lines = [
        ("boğazını temizleyip yeniden konuştu:", LEFT, 473, 218),
        ("“Bir dizüstü bilgisayar?”", 66, 491, 179),
        ("Ove çılgınca başını iki yana sallayıp tehditkâr bir şekilde", 66, 509, RIGHT - 2),
        ("tezgâha doğru eğildi.", LEFT, 525, 144),
    ]
    blocks = [_block(f"p8_b{i}", [line], page=8) for i, line in enumerate(lines)]
    blocks.append(_block("p8_full", [("Satış görevlisi bir an durup sözlerinin adamın idrak sınırlarının", 66, 441, RIGHT)], page=8))
    nodes = [
        StructuralNode(node_id=f"n{i}", role=BlockRole.PARAGRAPH, text=b.text, source_block_ids=[b.block_id], page=8)
        for i, b in enumerate(blocks[:4])
    ]
    assert detect_verse(nodes, {b.block_id: b for b in blocks}) == 0
    assert all(n.role == BlockRole.PARAGRAPH for n in nodes)


def test_a_line_closing_a_quotation_on_a_comma_runs_on():
    merges, _ = _continues("bütün yerlere elektrik döşeyeceğim,”", "dedi sükûnetini bozmadan.")
    assert merges


def _geometry(gap):
    return _Geometry(last_line_full=True, next_indented=False, crosses_boundary=False, uses_indents=True, gap=gap)


def test_a_sentence_ending_on_a_full_line_continues_at_the_margin():
    merges, _ = _continues("anlam veremediği desenler vardı.", "Sağlığı yerinde ve aklı başında", _geometry(0.5))
    assert merges


def test_space_above_the_next_line_still_ends_the_paragraph():
    merges, _ = _continues("anlam veremediği desenler vardı.", "Sağlığı yerinde ve aklı başında", _geometry(1.6))
    assert not merges


def test_dialogue_tag_after_a_question_runs_on():
    merges, _ = _continues("hasmının ne olduğunu bilmiyor musun?”", "diye sordu Parvaneh.", _geometry(0.5))
    assert merges


def test_a_paragraphs_indented_first_line_in_smaller_type_is_not_a_quotation():
    first = _block("p51_b13", [("Ove her şeye hazırlıklıydı. Mezar kazıcılarına ödemeyi yap-", 64, 444, 334, 10.0)], page=51)
    rest = _block("p51_b14", [("mış ve mezarlıkta hemen karısının yanındaki yerini ayırtmış,", LEFT, 460, RIGHT, 10.0)], page=51)
    page = [_block(f"p51_x{i}", [("Ove her zamanki gibi erkenden kalktı ve kapıyı çekti.", LEFT, 100 + i * 16, RIGHT)], page=51) for i in range(12)]
    nodes = structure.classify_blocks(page + [first, rest], {})
    roles = {n.source_block_ids[0]: n.role for n in nodes}
    assert roles["p51_b13"] == BlockRole.PARAGRAPH


def test_space_inside_curly_quotation_marks_is_removed():
    text, _ = textrepair._normalise_text("“ Öğle yemeği!” diye güldü. “Evet. ” dedi.")
    assert text == "“Öğle yemeği!” diye güldü. “Evet.” dedi."


# --- the page behind the text -------------------------------------------------


def _scanned_page(path: Path, photo: bool) -> fitz.Page:
    doc = fitz.open()
    page = doc.new_page(width=PAGE_W, height=PAGE_H)
    scan = fitz.Pixmap(fitz.csGRAY, fitz.IRect(0, 0, 383, 573), False)
    scan.clear_with(255)
    scan.set_rect(fitz.IRect(170, 60, 210, 90), (0,))  # an ornament
    if photo:
        scan.set_rect(fitz.IRect(60, 300, 320, 520), (40,))  # a photograph
    page.insert_image(page.rect, pixmap=scan)
    body = " ".join(["Ove her sabah mahalleyi dolaşır ve her şeyi kontrol ederdi."] * 6)
    page.insert_htmlbox(fitz.Rect(LEFT, 110, RIGHT, 290), f"<p style='font-size:10.5pt'>{body}</p>")
    doc.save(str(path))
    return fitz.open(str(path))[0]


def test_the_scan_behind_a_text_layer_is_not_a_picture(tmp_path):
    from app.pipeline.extract import extract_images, extract_page_blocks

    page = _scanned_page(tmp_path / "scan.pdf", photo=False)
    text_blocks = extract_page_blocks(page, 0)
    (tmp_path / "img").mkdir()
    found = extract_images(page, 0, tmp_path / "img")
    assert len(found) == 1
    kept = images.drop_page_backgrounds(page, 0, found, text_blocks, tmp_path / "img")
    assert kept == []


def test_a_photograph_in_the_scan_is_kept_without_the_page(tmp_path):
    from app.pipeline.extract import extract_images, extract_page_blocks

    page = _scanned_page(tmp_path / "scan.pdf", photo=True)
    text_blocks = extract_page_blocks(page, 0)
    (tmp_path / "img").mkdir()
    found = extract_images(page, 0, tmp_path / "img")
    kept = images.drop_page_backgrounds(page, 0, found, text_blocks, tmp_path / "img")
    assert len(kept) == 1
    x0, y0, x1, y1 = kept[0]["bbox"]
    # The photograph, give or take the probe's grid and a little padding.
    assert 45 <= x0 <= 62 and 285 <= y0 <= 302 and 318 <= x1 <= 336 and 518 <= y1 <= 536
    assert kept[0]["ext"] == "jpg"


# --- the book around the text ------------------------------------------------


def test_the_title_the_opening_pages_agree_on_is_the_books(tmp_path):
    doc = fitz.open()
    for title, size in (("KAVATA ROVEŞATA ÇFKFN ADAM", 26), ("HAYATA RÖVEŞATA ÇEKEN ADAM", 10), ("HAYATA ROVEŞATA ÇEKEN ADAM", 32)):
        page = doc.new_page(width=PAGE_W, height=PAGE_H)
        page.insert_htmlbox(fitz.Rect(40, 150, 340, 300), f"<p style='font-size:{size}pt'>{title}</p>")
    path = tmp_path / "front.pdf"
    doc.save(str(path))
    assert analyze._title_from_pages(fitz.open(str(path))) == "HAYATA ROVEŞATA ÇEKEN ADAM"


def test_each_chapter_file_opens_with_an_h1():
    def heading(node_id, level):
        return StructuralNode(node_id=node_id, role=BlockRole.HEADING, text=node_id, level=level)

    chapters = [
        Chapter(filename="a", title="a", nodes=[heading("1 OVE", 3), heading("Kısım", 4)]),
        Chapter(filename="b", title="b", nodes=[heading("2 OVE", 3)]),
        Chapter(filename="c", title="c", nodes=[heading("3 OVE", 3)]),
    ]
    _raise_chapter_headings(chapters)
    assert [c.nodes[0].level for c in chapters] == [1, 1, 1]
    assert chapters[0].nodes[1].level == 2
