from __future__ import annotations

import re
from dataclasses import dataclass

from app.models.document import Block, Span
from app.pipeline.epub.xmltext import xml_escape

# Characters that only appear in mathematical settings. Greek letters are
# included, but note that Greek *words* are excluded below — a Greek-language
# document must not be mistaken for an equation.
_MATH_OPERATORS = set("∑∏∫∬∭∮√∞≈≠≤≥±∓×÷⋅∈∉⊂⊃⊆⊇∪∩∀∃∇∂→←↔⇒⇔≡∝⊕⊗∅∴∵")
_GREEK_LETTERS = set("αβγδεζηθικλμνξοπρστυφχψωΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩ")
_SUPERSCRIPT_DIGITS = set("⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿ")
_SUBSCRIPT_DIGITS = set("₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎")
_FRACTION_CHARS = set("½⅓⅔¼¾⅕⅖⅗⅘⅙⅚⅛⅜⅝⅞⁄")

_MATH_FONT_HINTS = ("cmmi", "cmsy", "cmex", "msam", "msbm", "mathjax", "euclid", "symbol", "mathematica")

# "(3.14)" or "(12)" hanging at the right margin is an equation number.
_EQUATION_NUMBER_RE = re.compile(r"^\(\s*[\dA-Za-z]+(?:\.\d+)*\s*\)$")
_EQUATION_NUMBER_RIGHT_MARGIN = 0.62  # fraction of page width

# A single simple relation we can transcribe to MathML without interpretation.
_SIMPLE_RELATION_RE = re.compile(
    r"^\s*([A-Za-z][A-Za-z0-9]{0,3})\s*(=|≈|≠|≤|≥|<|>)\s*([A-Za-z0-9αβγπθλμσ][A-Za-z0-9αβγπθλμσ .+\-*/]{0,40}?)\s*$"
)
_SIMPLE_TERM_RE = re.compile(r"^[A-Za-z0-9αβγπθλμσ]+$")


@dataclass
class FormulaCandidate:
    block_id: str
    page: int
    bbox: tuple[float, float, float, float]
    text: str
    confidence: float
    equation_number: str | None
    mathml: str | None


def _math_symbol_ratio(text: str) -> float:
    """Share of characters that are unambiguously mathematical.

    ASCII relations are deliberately excluded here — "=" alone is far too weak
    a signal, and counting it would let ordinary prose drift into the formula
    path. It is picked up instead by the relation-parse evidence in
    detect_formula, which only fires on a fully parsed expression.
    """
    stripped = [c for c in text if not c.isspace()]
    if not stripped:
        return 0.0
    math_chars = sum(
        1
        for c in stripped
        if c in _MATH_OPERATORS
        or c in _GREEK_LETTERS
        or c in _SUPERSCRIPT_DIGITS
        or c in _SUBSCRIPT_DIGITS
        or c in _FRACTION_CHARS
    )
    return math_chars / len(stripped)


def _math_font_share(spans: list[Span]) -> float:
    """Share of the block's characters set in a mathematics font.

    A share, not a yes or no: an author's name carrying one footnote star in
    the symbol font -- "Ashish Vaswani∗" -- was enough to turn every name on
    a paper's title page into a picture of an equation.
    """
    total = sum(len(s.text.strip()) for s in spans)
    if not total:
        return 0.0
    in_math = sum(
        len(s.text.strip())
        for s in spans
        if any(hint in (s.font or "").lower() for hint in _MATH_FONT_HINTS)
    )
    return in_math / total


# Prose that carries some mathematics -- "We used the Adam optimizer with
# β1 = 0.9" -- is prose. Kept as text it reads, reflows and can be searched;
# as a picture of a paragraph it does none of that.
_PROSE_MIN_WORDS = 15
_PROSE_WORD_SHARE = 0.6
_PROSE_WORD_RE = re.compile(r"^[^\W\d_]{3,}[.,;:!?)]*$")


def _reads_as_prose(text: str) -> bool:
    tokens = text.split()
    if len(tokens) < _PROSE_MIN_WORDS:
        return False
    words = sum(1 for t in tokens if _PROSE_WORD_RE.match(t.strip("(\"“”'")))
    return words / len(tokens) >= _PROSE_WORD_SHARE


def _looks_like_greek_prose(text: str) -> bool:
    """Guard against classifying Greek-language text as mathematics: real Greek
    prose has long runs of Greek letters and spaces between words, whereas an
    equation uses isolated Greek symbols among operators."""
    greek_runs = re.findall(r"[α-ωΑ-Ω]{4,}", text)
    return len(greek_runs) >= 2


def _extract_equation_number(block: Block) -> str | None:
    """An equation number is a short parenthesised token sitting alone at the
    right margin of the block's line."""
    for span in block.spans:
        candidate = span.text.strip()
        if not _EQUATION_NUMBER_RE.match(candidate):
            continue
        if span.bbox[0] >= block.page_width * _EQUATION_NUMBER_RIGHT_MARGIN:
            return candidate
    text = block.text.strip()
    tail = text.rsplit(None, 1)[-1] if text else ""
    if _EQUATION_NUMBER_RE.match(tail):
        return tail
    return None


def _mathml_for_simple_relation(text: str) -> str | None:
    """Transcribe only unambiguous single-relation expressions such as "E = mc2".

    Anything with fractions, integrals, matrices, or nested structure returns
    None so the caller uses an image of the real equation instead of a MathML
    tree we'd have to guess at. Producing wrong mathematics is worse than
    producing a picture of the right mathematics.
    """
    cleaned = " ".join(text.split())
    cleaned = re.sub(r"\(\s*[\dA-Za-z]+(?:\.\d+)*\s*\)$", "", cleaned).strip()
    match = _SIMPLE_RELATION_RE.match(cleaned)
    if not match:
        return None

    lhs, operator, rhs = match.group(1), match.group(2), match.group(3).strip()
    if not _SIMPLE_TERM_RE.match(lhs) or not rhs:
        return None
    # Reject anything needing real parsing.
    if any(ch in rhs for ch in "/^_{}[]|∫∑∏√"):
        return None

    rhs_tokens = rhs.split()
    if len(rhs_tokens) > 3:
        return None

    def term_to_mathml(token: str) -> str | None:
        # "mc2" -> m, c squared: only when the trailing digits are a clean suffix.
        exponent_match = re.fullmatch(r"([A-Za-zαβγπθλμσ]+)(\d+)", token)
        if exponent_match:
            base, exponent = exponent_match.groups()
            identifiers = "".join(f"<mi>{xml_escape(ch)}</mi>" for ch in base[:-1])
            return (
                f"{identifiers}<msup><mi>{xml_escape(base[-1])}</mi>"
                f"<mn>{xml_escape(exponent)}</mn></msup>"
            )
        if re.fullmatch(r"\d+(?:\.\d+)?", token):
            return f"<mn>{xml_escape(token)}</mn>"
        if re.fullmatch(r"[A-Za-zαβγπθλμσ]+", token):
            return "".join(f"<mi>{xml_escape(ch)}</mi>" for ch in token)
        if token in {"+", "-", "*", "×", "⋅"}:
            return f"<mo>{xml_escape(token)}</mo>"
        return None

    rendered_terms = []
    for token in rhs_tokens:
        rendered = term_to_mathml(token)
        if rendered is None:
            return None
        rendered_terms.append(rendered)

    return (
        '<math xmlns="http://www.w3.org/1998/Math/MathML" display="block">'
        f"<mrow><mi>{xml_escape(lhs)}</mi><mo>{xml_escape(operator)}</mo>"
        f"{''.join(rendered_terms)}</mrow></math>"
    )


def detect_formula(block: Block) -> FormulaCandidate | None:
    """Decide whether a block is a display equation, and how confidently we can
    represent it semantically."""
    text = block.text.strip()
    if not text or len(text) > 400:
        return None
    if _looks_like_greek_prose(text) or _reads_as_prose(text):
        return None

    symbol_ratio = _math_symbol_ratio(text)
    math_font_share = _math_font_share(block.spans)
    has_scripts = any(s.is_superscript or s.is_subscript for s in block.spans)
    equation_number = _extract_equation_number(block)
    word_count = len(text.split())
    mathml = _mathml_for_simple_relation(text)

    # Evidence combination — no single signal is sufficient on its own.
    score = 0.0
    if symbol_ratio >= 0.30:
        score += 0.55
    elif symbol_ratio >= 0.12:
        score += 0.35
    elif symbol_ratio > 0:
        score += 0.15
    if math_font_share >= 0.3:
        score += 0.30
    elif math_font_share > 0:
        score += 0.05
    if has_scripts:
        score += 0.15
    if equation_number:
        score += 0.25
    if word_count <= 12:
        score += 0.10  # display equations are short; prose paragraphs are not
    if mathml:
        # The text parsed cleanly as a single relation ("E = mc2"). Plain-ASCII
        # equations carry none of the Unicode-symbol evidence above, so without
        # this they would never be recognised at all.
        score += 0.25

    if score < 0.45:
        return None
    # Confidence here is confidence in *semantic reconstruction*, which is only
    # high when we actually produced MathML we can stand behind.
    confidence = min(0.97, 0.55 + score * 0.4) if mathml else min(0.5, score * 0.5)

    return FormulaCandidate(
        block_id=block.block_id,
        page=block.page,
        bbox=block.bbox,
        text=text,
        confidence=confidence,
        equation_number=equation_number,
        mathml=mathml,
    )


def detect_formulas(blocks: list[Block]) -> list[FormulaCandidate]:
    candidates = []
    for block in blocks:
        if block.kind != "text":
            continue
        candidate = detect_formula(block)
        if candidate:
            candidates.append(candidate)
    return candidates
