---
title: PDFtoEPUB Backend
emoji: 📚
colorFrom: blue
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
---

# PDF → EPUB backend

FastAPI service implementing the document-reconstruction pipeline described in
[`../docs/architecture.md`](../docs/architecture.md). Deterministic PDF
extraction, structure reconstruction, and EPUB3 generation — AI is an optional,
off-by-default enhancement layer, never a requirement.

## Requirements

- Python 3.12 (a virtualenv at `backend/.venv` is expected by `scripts/run_dev.sh`)
- [EPUBCheck](https://github.com/w3c/epubcheck) on `PATH` (`brew install epubcheck`
  on macOS — pulls in a JRE). The server still runs without it, but conversions
  will fail validation, matching the spec's "never present an unvalidated EPUB
  as successful" rule.
- [Tesseract](https://github.com/tesseract-ocr/tesseract) on `PATH` for scanned
  documents: `brew install tesseract tesseract-lang`. Without it, native-text
  PDFs convert normally and scanned pages are preserved as images rather than
  read. Language packs are selected automatically from the detected document
  language; missing packs degrade to the ones installed instead of failing.

No Docker, no Redis, no database server — job state lives in a local SQLite
file under `backend/data/`, and the job queue is a small in-process asyncio
worker pool (see `docs/architecture.md` §2 for why, and the upgrade path).

## Setup

```bash
cd backend
python3.12 -m venv .venv
./.venv/bin/pip install -r requirements.txt
cp .env.example .env   # optional — all defaults work with no .env at all
```

## Run

```bash
./scripts/run_dev.sh          # http://127.0.0.1:8000, auto-reload
```

`GET /health` reports the active AI provider (`none` by default).

## Try it against a real PDF

```bash
curl -X POST http://127.0.0.1:8000/v1/conversions \
  -F "file=@/path/to/book.pdf" -F "mode=maximum_accuracy"
# => {"id": "...", "status": "UPLOADED"}

curl http://127.0.0.1:8000/v1/conversions/<id>/progress
curl http://127.0.0.1:8000/v1/conversions/<id>/result
curl -o book.epub http://127.0.0.1:8000/v1/conversions/<id>/download
```

## Tests

```bash
./.venv/bin/pytest -q
```

Unit tests cover hyphenation repair, paragraph reconstruction, heading/list
detection, header/footer stripping, multi-column reading order, footnote
linking, EPUB packaging, and the AI provider/confidence-gating contract.
Integration tests run the **real** pipeline (synthetic PDFs generated with
reportlab) through EPUBCheck end to end, and exercise the encrypted/
corrupted/scanned-PDF error paths. `AI_PROVIDER` is asserted to default to
`none` in the end-to-end test — a normal conversion must never require AI.

## Configuration (`.env`, all optional)

See `.env.example`. The only settings worth knowing:

- `AI_PROVIDER=none|local|anthropic` — `none` is the default and requires no
  key. `local` runs a free, no-network heuristic second-opinion pass on
  low-confidence blocks. `anthropic` additionally requires `ANTHROPIC_API_KEY`
  and is only ever consulted for blocks the deterministic pass scored below
  `AI_CONFIDENCE_THRESHOLD` (default 0.70) — never the whole book.
- `MAX_UPLOAD_MB`, `JOB_TTL_HOURS` — upload limit and temp-file retention.

## Configuration for OCR and fallbacks

Also in `.env.example`:

- `OCR_ENABLED` (default true), `OCR_LANGUAGES` (default `eng`), `OCR_DPI` (300).
- `OCR_MIN_WORD_CONFIDENCE` (40) — words below this are dropped, never trusted.
- `OCR_MIN_REGION_CONFIDENCE` (75) — below this a page is preserved as an image
  rather than converted to unreliable text. The floor sits deliberately above the
  mid-60s band where Tesseract returns confident-looking nonsense for upside-down
  Latin text.
- `OCR_CONFIDENT_ACCEPT_THRESHOLD` (88) — above this the upright pass is trusted
  and rotated retries are skipped, which is what keeps normal scans to one pass.
- `TABLE_MIN_CONFIDENCE` / `FORMULA_MIN_CONFIDENCE` (0.70) — below these, a
  faithful image of the source region is emitted instead of a guessed structure.

## What is implemented

PDF classification and per-page OCR routing, geometry-aware extraction,
multi-column reading order, paragraph reconstruction with hyphenation repair,
running header/footer + page-number stripping, heading hierarchy, lists,
footnotes and endnotes with back-navigation, geometric table detection, formula
detection with MathML or image fallback, verse/poetry preservation, RTL and
bidirectional text, a reusable region rasterizer, EPUB3 packaging, real
EPUBCheck validation, per-source content-integrity accounting, and a quality
score computed from actual metrics.

Limitations are documented in [`../docs/architecture.md`](../docs/architecture.md) §0.
