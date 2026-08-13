from __future__ import annotations

from pathlib import Path

import pytest

from tests.fixtures.make_test_pdf import build_simple_book

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def simple_book_pdf() -> Path:
    path = FIXTURES_DIR / "simple_book.pdf"
    build_simple_book(path)
    return path
