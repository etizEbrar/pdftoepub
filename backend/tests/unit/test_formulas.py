from app.models.document import Block, Span
from app.pipeline.formulas import _mathml_for_simple_relation, detect_formula


def _block(
    text: str,
    *,
    font: str = "Helvetica",
    size: float = 12.0,
    superscript: bool = False,
    x0: float = 100.0,
    eq_number: str | None = None,
) -> Block:
    spans = [
        Span(
            text=text,
            bbox=(x0, 100, x0 + 8 * len(text), 116),
            font=font,
            font_size=size,
            bold=False,
            italic=False,
            baseline=114,
            is_superscript=superscript,
            line_break_after=True,
        )
    ]
    full_text = text
    if eq_number:
        # Equation numbers sit alone at the right margin.
        spans.append(
            Span(
                text=eq_number,
                bbox=(500, 100, 540, 116),
                font=font,
                font_size=size,
                bold=False,
                italic=False,
                baseline=114,
                line_break_after=True,
            )
        )
        full_text = f"{text}\n{eq_number}"
    return Block(
        block_id="b1",
        page=1,
        page_width=612,
        page_height=792,
        bbox=(x0, 100, 540, 116),
        kind="text",
        text=full_text,
        spans=spans,
        font=font,
        font_size=size,
    )


def test_transcribes_a_simple_relation_to_mathml():
    mathml = _mathml_for_simple_relation("E = mc2")
    assert mathml is not None
    assert "<math" in mathml and 'xmlns="http://www.w3.org/1998/Math/MathML"' in mathml
    assert "<msup><mi>c</mi><mn>2</mn></msup>" in mathml


def test_refuses_to_transcribe_expressions_needing_real_parsing():
    # Producing wrong mathematics is worse than producing a picture of it.
    for expression in (
        "∫₀^∞ e^(−x²) dx = √π ⁄ 2",
        "x = (a + b) / (c - d)",
        "A = [1 2; 3 4]",
        "f(x) = Σ aᵢxⁱ",
    ):
        assert _mathml_for_simple_relation(expression) is None, expression


def test_detects_plain_ascii_equation_with_an_equation_number():
    block = _block("E = mc2", size=13.0, eq_number="(1.1)")
    candidate = detect_formula(block)
    assert candidate is not None
    assert candidate.equation_number == "(1.1)"
    assert candidate.mathml is not None
    assert candidate.confidence >= 0.7


def test_detects_symbol_heavy_expression_but_refuses_mathml():
    block = _block("∫₀^∞ e^(−x²) dx = √π ⁄ 2", size=14.0, eq_number="(1.2)")
    candidate = detect_formula(block)
    assert candidate is not None
    assert candidate.mathml is None  # falls back to an image downstream
    assert candidate.confidence < 0.7


def test_ordinary_prose_is_not_a_formula():
    block = _block("This sentence explains the result and is ordinary running prose.")
    assert detect_formula(block) is None


def test_prose_containing_an_equals_sign_is_not_a_formula():
    block = _block("We set the threshold = 5 for all of the experiments described below.")
    assert detect_formula(block) is None


def test_greek_language_prose_is_not_mistaken_for_mathematics():
    block = _block("Αυτό είναι ελληνικό κείμενο και όχι μαθηματικά καθόλου.")
    assert detect_formula(block) is None


def test_math_font_is_evidence_even_without_unicode_symbols():
    block = _block("f x", font="CMMI10", size=12.0, eq_number="(3)")
    candidate = detect_formula(block)
    assert candidate is not None
