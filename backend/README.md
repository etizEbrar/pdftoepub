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

## What this slice does and doesn't cover yet

Implemented for real (not stubbed): PDF classification, geometry-aware
extraction, multi-column reading order, paragraph reconstruction with
hyphenation repair, running header/footer + page-number stripping, heading
hierarchy detection, list detection, footnote reference/body linking with
back-navigation, image extraction with a cover heuristic, EPUB3 packaging,
EPUBCheck validation, content-integrity scoring, and a real (not invented)
quality score.

Deliberately not yet implemented, and declined with a clear error rather than
faked: OCR for scanned/mixed PDFs, table and formula reconstruction (would
need an image-fallback path), endnote sections, poetry-specific line
preservation, RTL layout.
