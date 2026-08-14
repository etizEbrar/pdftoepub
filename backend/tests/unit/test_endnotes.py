from app.models.document import BlockRole, StructuralNode
from app.pipeline.endnotes import (
    classify_endnote_sections,
    find_endnote_sections,
    link_endnote_references,
)
from app.pipeline.footnotes import MARKER_CLOSE, MARKER_OPEN


def _heading(node_id: str, text: str, level: int = 1, page: int = 1) -> StructuralNode:
    return StructuralNode(node_id=node_id, role=BlockRole.HEADING, text=text, level=level, page=page)


def _para(node_id: str, text: str, page: int = 1) -> StructuralNode:
    return StructuralNode(node_id=node_id, role=BlockRole.PARAGRAPH, text=text, page=page)


def _list_item(node_id: str, text: str, page: int = 1) -> StructuralNode:
    return StructuralNode(node_id=node_id, role=BlockRole.LIST_ITEM, text=text, page=page)


def _ref(marker: str) -> str:
    return f"{MARKER_OPEN}{marker}{MARKER_CLOSE}"


def _book_with_endnotes() -> list[StructuralNode]:
    return [
        _heading("h1", "Chapter 1: Beginnings", 1, page=1),
        _para("p1", f"A first claim{_ref('1')} in chapter one.", page=1),
        _para("p2", f"A second claim{_ref('2')} in chapter one.", page=1),
        _heading("h2", "Chapter 2: Developments", 1, page=2),
        _para("p3", f"A first claim{_ref('1')} in chapter two.", page=2),
        _heading("hn", "Notes", 1, page=3),
        _heading("hc1", "Chapter 1", 3, page=3),
        _list_item("e1", "1. First note for chapter one.", page=3),
        _list_item("e2", "2. Second note for chapter one.", page=3),
        _heading("hc2", "Chapter 2", 3, page=3),
        _list_item("e3", "1. First note for chapter two.", page=3),
    ]


def test_finds_a_collected_notes_section():
    nodes = _book_with_endnotes()
    sections = find_endnote_sections(nodes)
    assert len(sections) == 1
    start, end = sections[0]
    assert nodes[start].text == "Notes"
    assert end == len(nodes)


def test_chapter_subheadings_do_not_close_the_notes_section():
    nodes = _book_with_endnotes()
    (start, end), = find_endnote_sections(nodes)
    # "Chapter 1"/"Chapter 2" inside the notes are scope markers, not the end.
    assert end - start > 3


def test_classifies_numbered_entries_as_endnotes_with_chapter_scope():
    nodes = _book_with_endnotes()
    count = classify_endnote_sections(nodes)
    assert count == 3

    endnotes = [n for n in nodes if n.role == BlockRole.ENDNOTE]
    assert [n.endnote_number for n in endnotes] == ["1", "2", "1"]
    assert [n.endnote_chapter for n in endnotes] == ["1", "1", "2"]
    # The marker is peeled off the body text, not left duplicated in it.
    assert endnotes[0].text == "First note for chapter one."


def test_section_heading_is_retagged_so_it_can_open_its_own_chapter():
    nodes = _book_with_endnotes()
    classify_endnote_sections(nodes)
    assert nodes[5].role == BlockRole.ENDNOTE_SECTION_HEADING


def test_links_references_to_the_right_chapter_scoped_endnote():
    nodes = _book_with_endnotes()
    classify_endnote_sections(nodes)
    linked = link_endnote_references(nodes)
    assert linked == 3

    chapter_one_ref = nodes[1]
    chapter_two_ref = nodes[4]
    # Both cite note "1", but they must resolve to *different* notes.
    assert "{{NOTEREF:e1:" in chapter_one_ref.text
    assert "{{NOTEREF:e3:" in chapter_two_ref.text


def test_every_linked_endnote_gets_return_navigation():
    nodes = _book_with_endnotes()
    classify_endnote_sections(nodes)
    link_endnote_references(nodes)
    for note in [n for n in nodes if n.role == BlockRole.ENDNOTE]:
        assert note.footnote_backrefs, f"endnote {note.endnote_number} has no way back"


def test_unmatched_reference_is_left_for_the_caller_not_mislinked():
    nodes = [
        _heading("h1", "Chapter 1", 1),
        _para("p1", f"A claim{_ref('9')} with no matching note."),
        _heading("hn", "Notes", 1),
        _list_item("e1", "1. The only note."),
    ]
    classify_endnote_sections(nodes)
    link_endnote_references(nodes)
    # Marker 9 has no note: it must not be attached to note 1.
    assert "{{NOTEREF" not in nodes[1].text


def test_endnotes_are_not_confused_with_footnotes():
    nodes = _book_with_endnotes()
    classify_endnote_sections(nodes)
    assert not any(n.role == BlockRole.FOOTNOTE for n in nodes)
    assert all(n.footnote_number is None for n in nodes if n.role == BlockRole.ENDNOTE)


def test_long_endnote_with_emphasis_and_citation_survives_intact():
    long_text = (
        "1. See especially the discussion in *Volume II*, pages 45-88, where the "
        "author revisits the argument at length and cites Smith (2019), Jones "
        "(2020), and the collected letters of the period."
    )
    nodes = [
        _heading("h1", "Chapter 1", 1),
        _para("p1", f"A claim{_ref('1')}."),
        _heading("hn", "Notes", 1),
        _list_item("e1", long_text),
    ]
    classify_endnote_sections(nodes)
    link_endnote_references(nodes)
    note = next(n for n in nodes if n.role == BlockRole.ENDNOTE)
    assert "Volume II" in note.text
    assert "Smith (2019)" in note.text
    assert note.text.startswith("See especially")
