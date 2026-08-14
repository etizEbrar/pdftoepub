from pathlib import Path

import fitz
import pytest

from app.core.config import settings
from app.models.document import PageTextKind
from app.pipeline.ocr.classify import classify_document, classify_page, pages_needing_ocr
from app.pipeline.ocr.engine import resolve_languages, tesseract_available
from app.pipeline.ocr.page_ocr import ocr_page, rotate_pixmap, unrotate_bbox

requires_tesseract = pytest.mark.skipif(
    not tesseract_available(), reason="tesseract is not installed on this machine"
)

SCAN_LINES = ["Hello scanned world.", "Second line of text here.", "A third line follows."]


def _make_scanned_pdf(path: Path, rotate: int = 0) -> Path:
    source = fitz.open()
    page = source.new_page(width=612, height=792)
    y = 120
    for line in SCAN_LINES:
        page.insert_text((80, y), line, fontsize=16)
        y += 34
    pix = page.get_pixmap(dpi=200)
    source.close()

    out = fitz.open()
    out_page = out.new_page(width=612, height=792)
    out_page.insert_image(out_page.rect, pixmap=pix, rotate=rotate)
    out.save(str(path))
    out.close()
    return path


def _make_native_pdf(path: Path) -> Path:
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 100), "This page has a real text layer with plenty of characters.", fontsize=11)
    page.insert_text((72, 130), "It must classify as NATIVE and never reach Tesseract.", fontsize=11)
    doc.save(str(path))
    doc.close()
    return path


# --- classification (the gate that keeps OCR cheap) -----------------------

def test_native_page_classifies_as_native(tmp_path: Path):
    doc = fitz.open(str(_make_native_pdf(tmp_path / "native.pdf")))
    assert classify_page(doc[0]) == PageTextKind.NATIVE
    doc.close()


def test_scanned_page_classifies_as_scanned(tmp_path: Path):
    doc = fitz.open(str(_make_scanned_pdf(tmp_path / "scan.pdf")))
    assert classify_page(doc[0]) == PageTextKind.SCANNED
    doc.close()


def test_blank_page_classifies_as_empty(tmp_path: Path):
    doc = fitz.open()
    doc.new_page(width=612, height=792)
    doc.save(str(tmp_path / "blank.pdf"))
    doc.close()
    reopened = fitz.open(str(tmp_path / "blank.pdf"))
    assert classify_page(reopened[0]) == PageTextKind.EMPTY
    reopened.close()


def test_only_scanned_and_mixed_pages_are_routed_to_ocr(tmp_path: Path):
    native = _make_native_pdf(tmp_path / "n.pdf")
    scanned = _make_scanned_pdf(tmp_path / "s.pdf")

    merged = fitz.open()
    merged.insert_pdf(fitz.open(str(native)))
    merged.insert_pdf(fitz.open(str(scanned)))
    merged.save(str(tmp_path / "merged.pdf"))
    merged.close()

    doc = fitz.open(str(tmp_path / "merged.pdf"))
    kinds = classify_document(doc)
    assert kinds[1] == PageTextKind.NATIVE
    assert kinds[2] == PageTextKind.SCANNED
    assert pages_needing_ocr(kinds) == [2]
    doc.close()


# --- rotation geometry (pure functions, no Tesseract needed) --------------

def test_unrotate_bbox_is_identity_at_zero_degrees():
    bbox = (10.0, 20.0, 30.0, 40.0)
    assert unrotate_bbox(bbox, 0, 100, 200) == bbox


def test_unrotate_bbox_round_trips_through_every_quarter_turn():
    """A box mapped back from rotated space must land inside the original page."""
    original_w, original_h = 400.0, 600.0
    for rotation in (90, 180, 270):
        swaps = rotation % 180 == 90
        rotated_w, rotated_h = (original_h, original_w) if swaps else (original_w, original_h)
        box = (10.0, 20.0, 60.0, 50.0)
        x0, y0, x1, y1 = unrotate_bbox(box, rotation, rotated_w, rotated_h)
        assert x0 < x1 and y0 < y1, f"degenerate box at {rotation}"
        assert -1 <= x0 and x1 <= original_w + 1, f"x out of page at {rotation}"
        assert -1 <= y0 and y1 <= original_h + 1, f"y out of page at {rotation}"


def test_rotate_pixmap_swaps_axes_on_quarter_turns():
    doc = fitz.open()
    page = doc.new_page(width=400, height=600)
    pix = page.get_pixmap(dpi=72)
    doc.close()

    assert rotate_pixmap(pix, 0).width == pix.width
    rotated = rotate_pixmap(pix, 90)
    assert (rotated.width, rotated.height) == (pix.height, pix.width)
    half = rotate_pixmap(pix, 180)
    assert (half.width, half.height) == (pix.width, pix.height)


# --- language handling ----------------------------------------------------

@requires_tesseract
def test_missing_language_packs_degrade_instead_of_failing():
    resolved = resolve_languages("eng+notareallanguage")
    assert "notareallanguage" not in resolved
    assert "eng" in resolved


# --- real OCR -------------------------------------------------------------

@requires_tesseract
def test_ocr_reads_a_scanned_page_with_real_confidence(tmp_path: Path):
    doc = fitz.open(str(_make_scanned_pdf(tmp_path / "scan.pdf")))
    outcome = ocr_page(doc[0], 0)
    doc.close()

    assert outcome.reliable
    assert outcome.word_count > 0
    assert outcome.mean_confidence > settings.ocr_min_region_confidence
    text = " ".join(b.text.replace("\n", " ") for b in outcome.blocks)
    assert "Hello scanned world" in text


@requires_tesseract
def test_ocr_output_carries_pdf_space_geometry(tmp_path: Path):
    doc = fitz.open(str(_make_scanned_pdf(tmp_path / "scan.pdf")))
    page = doc[0]
    page_width, page_height = page.rect.width, page.rect.height
    outcome = ocr_page(page, 0)
    doc.close()

    assert outcome.blocks
    for block in outcome.blocks:
        x0, y0, x1, y1 = block.bbox
        assert 0 <= x0 < x1 <= page_width + 1
        assert 0 <= y0 < y1 <= page_height + 1
        assert block.source == "ocr"
        assert block.ocr_confidence is not None


@requires_tesseract
@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_ocr_recovers_text_from_any_page_rotation(tmp_path: Path, rotation: int):
    """Tesseract's own orientation detection cannot recover 180-degree pages, so
    the pipeline re-OCRs at each orientation and keeps the best-scoring one."""
    doc = fitz.open(str(_make_scanned_pdf(tmp_path / f"rot{rotation}.pdf", rotate=rotation)))
    outcome = ocr_page(doc[0], 0)
    doc.close()

    text = " ".join(b.text.replace("\n", " ") for b in outcome.blocks)
    assert "Hello scanned world" in text, f"rotation {rotation} produced: {text[:80]!r}"
    assert outcome.reliable


@requires_tesseract
def test_unreadable_scan_is_reported_unreliable_rather_than_invented(tmp_path: Path):
    """A blank scan must yield no text and be flagged for image fallback."""
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    blank = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 1200, 1600), False)
    blank.clear_with(255)
    page.insert_image(page.rect, pixmap=blank)
    doc.save(str(tmp_path / "blank_scan.pdf"))
    doc.close()

    reopened = fitz.open(str(tmp_path / "blank_scan.pdf"))
    outcome = ocr_page(reopened[0], 0)
    reopened.close()

    assert outcome.reliable is False
    assert not outcome.blocks
