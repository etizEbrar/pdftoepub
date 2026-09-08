"""Kindle compatibility and footnote-marker resolution.

A real 348-page book linked one note in six. Its markers were not the bare
digits the matcher understood, and no amount of correct linking logic could
help while the two sides were compared in different forms.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from app.models.document import BlockRole, StructuralNode
from app.pipeline.footnotes import (
    _FOOTNOTE_PREFIX_RE,
    _SUPERSCRIPT_DIGITS,
    MARKER_CLOSE,
    MARKER_OPEN,
    link_references,
    normalise_marker,
)


class TestMarkerIdentity:
    """A marker's identity is the number, not the brackets around it."""

    @pytest.mark.parametrize(
        "written,identity",
        [
            ("1", "1"), ("[1]", "1"), ("(1)", "1"), ("{1}", "1"),
            ("1.", "1"), ("1)", "1"), ("¹", "1"), ("²", "2"), ("³", "3"),
            ("12", "12"), ("(12)", "12"), ("[12]", "12"),
            ("*", "*"), ("**", "**"), ("†", "†"), ("‡", "‡"),
        ],
    )
    def test_every_common_marker_style_reduces_to_its_number(self, written, identity):
        assert normalise_marker(written) == identity

    @pytest.mark.parametrize("text", ["1984 was", "hello", "(see 1)", "2024", "", "note"])
    def test_ordinary_prose_is_not_a_marker(self, text):
        assert normalise_marker(text) is None

    @pytest.mark.parametrize(
        "body",
        ["1 Açıklama.", "[1] Açıklama.", "(1) Açıklama.", "¹ Açıklama.",
         "1. Açıklama.", "1) Açıklama."],
    )
    def test_note_bodies_in_every_style_yield_the_same_number(self, body):
        m = _FOOTNOTE_PREFIX_RE.match(body.translate(_SUPERSCRIPT_DIGITS))
        assert m is not None, f"{body!r} was not recognised as a note body"
        assert normalise_marker(m.group(1)) == "1"


class TestBracketedReferencesLink:
    """The end-to-end failure: a reference and its note in bracketed form."""

    @staticmethod
    def _nodes(ref_marker: str, note_text: str):
        body = StructuralNode(
            node_id="p1", role=BlockRole.PARAGRAPH,
            text=f"Bir iddia{MARKER_OPEN}{ref_marker}{MARKER_CLOSE} ve devamı.",
            source_block_ids=["b1"], page=4,
        )
        note = StructuralNode(
            node_id="n1", role=BlockRole.FOOTNOTE, text=note_text,
            source_block_ids=["b2"], page=4,
        )
        return [body, note]

    @pytest.mark.parametrize(
        "ref,note",
        [
            ("[1]", "[1] Kaynak açıklaması."),
            ("(1)", "(1) Kaynak açıklaması."),
            ("¹", "¹ Kaynak açıklaması."),
            ("1", "1 Kaynak açıklaması."),
            ("[1]", "1 Kaynak açıklaması."),   # mixed styles across the book
            ("¹", "1. Kaynak açıklaması."),
            ("*", "* Kaynak açıklaması."),
        ],
    )
    def test_the_reference_finds_its_note(self, ref, note):
        nodes, linked = link_references(self._nodes(ref, note))
        assert linked == 1, f"{ref!r} did not link to {note!r}"
        assert "{{NOTEREF:" in nodes[0].text

    def test_the_marker_is_displayed_as_the_book_set_it(self):
        """Matching is normalised; what the reader sees is not."""
        nodes, _ = link_references(self._nodes("[1]", "[1] Kaynak."))
        assert ":[1]}}" in nodes[0].text, nodes[0].text

    def test_a_reference_with_no_note_is_not_invented(self):
        nodes, linked = link_references(self._nodes("[7]", "[1] Başka bir not."))
        assert linked == 0
        assert "{{NOTEREF:" not in nodes[0].text
        assert "{{SUP:[7]}}" in nodes[0].text, "the unmatched marker was not preserved"


class TestKindleNavigation:
    """Amazon's ingestion still reads NCX; EPUB 3 readers use nav.xhtml."""

    @pytest.fixture(scope="class")
    def epub(self, tmp_path_factory) -> Path:
        from app.jobs import store
        from app.models.job import ConversionMode, Job
        from app.pipeline.orchestrator import _run_pipeline_sync
        from tests.fixtures import corpus

        pdf = corpus.build_turkish_novel(tmp_path_factory.mktemp("k") / "t.pdf")
        job = Job(job_id="kindle-nav", source_filename=pdf.name,
                  mode=ConversionMode.MAXIMUM_ACCURACY, upload_path=str(pdf))
        store.save_job(job)
        try:
            _run_pipeline_sync(job)
            assert job.epub_path
            return Path(job.epub_path)
        finally:
            store.delete_job("kindle-nav")

    def test_both_navigation_documents_are_present(self, epub):
        with zipfile.ZipFile(epub) as zf:
            names = zf.namelist()
        assert "OEBPS/nav.xhtml" in names, "EPUB 3 navigation missing"
        assert "OEBPS/toc.ncx" in names, "EPUB 2 navigation missing — Kindle needs it"

    def test_the_ncx_is_declared_and_referenced_from_the_spine(self, epub):
        with zipfile.ZipFile(epub) as zf:
            opf = zf.read("OEBPS/content.opf").decode()
        assert 'media-type="application/x-dtbncx+xml"' in opf, "NCX not in the manifest"
        assert 'toc="ncx"' in opf, "the spine does not point at the NCX"

    def test_the_ncx_lists_every_chapter_in_order(self, epub):
        with zipfile.ZipFile(epub) as zf:
            ncx = zf.read("OEBPS/toc.ncx").decode()
            opf = zf.read("OEBPS/content.opf").decode()
        assert ncx.startswith("<?xml"), "NCX must be well-formed XML"
        assert "﻿" not in ncx, "a BOM would break strict parsers"
        chapters = opf.count('media-type="application/xhtml+xml"') - 1  # minus nav
        assert ncx.count("<navPoint") == chapters, "NCX and spine disagree on chapters"
        orders = [int(p.split('playOrder="')[1].split('"')[0])
                  for p in ncx.split("<navPoint")[1:]]
        assert orders == sorted(orders) == list(range(1, len(orders) + 1))

    def test_the_ncx_is_parseable_xml(self, epub):
        from xml.etree import ElementTree

        with zipfile.ZipFile(epub) as zf:
            ElementTree.fromstring(zf.read("OEBPS/toc.ncx"))
