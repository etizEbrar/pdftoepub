"""Download the audit corpus listed in sources.json.

The PDFs land in backend/corpus/ (git-ignored): they are public-domain or
openly licensed, but they are not ours to redistribute and are far too large
for the repository. Files already present are not fetched again.

    .venv/bin/python scripts/corpus/fetch.py
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
CORPUS = HERE.parents[1] / "corpus"
# The server refuses uploads above this, so a larger book is not a case the app meets.
MAX_BYTES = 25 * 1024 * 1024


def main() -> int:
    CORPUS.mkdir(exist_ok=True)
    books = json.loads((HERE / "sources.json").read_text())["books"]
    failed = 0
    for book in books:
        target = CORPUS / f"{book['name']}.pdf"
        if target.exists():
            continue
        request = urllib.request.Request(book["url"], headers={"User-Agent": "pdftoepub-audit/1.0"})
        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                data = response.read(MAX_BYTES + 1)
        except Exception as exc:  # network trouble is reported, never fatal
            print(f"  failed  {book['name']}: {exc}")
            failed += 1
            continue
        if len(data) > MAX_BYTES or not data.startswith(b"%PDF"):
            print(f"  skipped {book['name']}: not a PDF under the upload limit")
            failed += 1
            continue
        target.write_bytes(data)
        print(f"  fetched {book['name']} ({len(data) / 1e6:.1f} MB)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
