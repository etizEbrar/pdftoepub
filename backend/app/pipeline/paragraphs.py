from __future__ import annotations

from app.models.document import BlockRole, StructuralNode
from app.pipeline.hyphenation import join_lines_with_hyphenation_repair
from app.pipeline.structure import TERMINAL_PUNCT


def _continues(prev_last_line: str, next_first_line: str) -> tuple[bool, float]:
    """Decide whether `next_first_line` is a wrapped continuation of the paragraph
    ending in `prev_last_line`, per spec section 13: use surrounding text, not the
    mere presence of a PDF line/page break.

    Primary signal: the previous line doesn't end a sentence. A lowercase next
    line reinforces confidence but isn't required — capitalized proper nouns can
    legitimately start a wrapped (non-paragraph-initial) line.
    """
    prev_stripped = prev_last_line.rstrip()
    next_stripped = next_first_line.lstrip()
    if not prev_stripped or not next_stripped:
        return False, 0.0
    if prev_stripped[-1] in TERMINAL_PUNCT:
        return False, 0.0
    reinforced = next_stripped[0].islower()
    return True, (0.9 if reinforced else 0.7)


def reconstruct_paragraphs(nodes: list[StructuralNode]) -> list[StructuralNode]:
    """Merge consecutive PARAGRAPH nodes (which may span PDF blocks, columns, and
    pages) into full logical paragraphs, repairing hyphenation across the joins."""
    result: list[StructuralNode] = []
    run_lines: list[str] = []
    run_source_ids: list[str] = []
    run_confidence = 1.0
    run_page: int | None = None

    def flush() -> None:
        nonlocal run_lines, run_source_ids, run_confidence, run_page
        if run_lines:
            text = join_lines_with_hyphenation_repair(run_lines)
            result.append(
                StructuralNode(
                    node_id=f"para_{run_source_ids[0]}",
                    role=BlockRole.PARAGRAPH,
                    text=text,
                    confidence=run_confidence,
                    source_block_ids=list(run_source_ids),
                    page=run_page,
                )
            )
        run_lines, run_source_ids, run_confidence, run_page = [], [], 1.0, None

    for node in nodes:
        if node.role != BlockRole.PARAGRAPH:
            flush()
            result.append(node)
            continue

        node_lines = node.text.split("\n")
        if run_lines:
            merges, confidence = _continues(run_lines[-1], node_lines[0] if node_lines else "")
        else:
            merges, confidence = False, 1.0

        if merges:
            run_lines.extend(node_lines)
            run_source_ids.extend(node.source_block_ids)
            run_confidence = min(run_confidence, confidence, node.confidence)
        else:
            flush()
            run_lines = list(node_lines)
            run_source_ids = list(node.source_block_ids)
            run_confidence = node.confidence
            run_page = node.page

    flush()
    return result
