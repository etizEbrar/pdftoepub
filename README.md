# PDF → EPUB

An iOS app and document-reconstruction backend that converts PDF books into
high-quality, reflowable EPUB3 ebooks.

This is not a PDF text extractor. The backend analyzes a PDF's geometry and
typography to recover the *logical* book — reading order, paragraphs, chapters,
headings, lists, footnotes — and renders that as semantic, reflowable EPUB3,
validated with EPUBCheck before it is ever returned as a success.

## AI-optional by design

**A normal conversion costs $0 in AI API fees and requires no API key.** The
deterministic pipeline is the product; AI is an optional accuracy booster that
is off by default.

```
AIProvider
├── NoneProvider      ← default. No network, no opinions, no cost.
├── LocalProvider      ← free, local, no-network heuristic review
├── AnthropicProvider  ← optional, only with the user's own API key
├── OpenAIProvider     ← reserved
└── GoogleProvider     ← reserved
```

Structural decisions carry confidence scores. Anything at or above 0.90 is
accepted deterministically and AI is never consulted. Only blocks below 0.70
are even eligible for review, and a provider only ever receives that specific
block plus a little surrounding context — never the whole book, never every
page. By construction the AI layer can only attach metadata (role, level,
confidence) to blocks already extracted from the PDF; it has no field capable
of carrying replacement text, so it cannot introduce content the PDF didn't
contain.

## Repository layout

| Path | What it is |
|---|---|
| [`backend/`](backend/) | Python 3.12 / FastAPI pipeline + REST API. See its [README](backend/README.md). |
| [`ios/`](ios/) | SwiftUI app (MVVM, async/await), generated with XcodeGen. |
| [`docs/architecture.md`](docs/architecture.md) | Pipeline design, API contract, document model, AI policy. |

## Quick start

```bash
# 1. Backend
cd backend
python3.12 -m venv .venv
./.venv/bin/pip install -r requirements.txt
brew install epubcheck          # real EPUB3 validation
./scripts/run_dev.sh            # http://127.0.0.1:8000

# 2. iOS app
cd ../ios
xcodegen generate
open PDFtoEPUB.xcodeproj        # run on a simulator
```

The app's Settings screen holds the backend address; it defaults to
`http://localhost:8000`, which the simulator can reach directly.

## Tests

```bash
# Backend: 43 tests
cd backend && ./.venv/bin/pytest -q

# iOS: 10 unit + 5 UI tests
cd ios
./scripts/seed_simulator_fixture.sh    # puts the test PDF in the booted simulator
xcodebuild -project PDFtoEPUB.xcodeproj -scheme PDFtoEPUB \
  -destination 'platform=iOS Simulator,name=iPhone 17 Pro' test
```

Backend tests include a genuine end-to-end run: a synthetic PDF goes through the
real pipeline and the resulting EPUB is validated by EPUBCheck, asserting zero
errors with `AI_PROVIDER=none`.

`ConversionFlowUITests` drives the whole journey through the **real** system
document picker against a **live** backend, and asserts the result screen shows
EPUB3 validation `Pass` and AI provider `None (fully local)`. It skips itself if
the backend isn't running, so the suite stays green without it.
`ScreenshotCaptureTest` attaches a screenshot of each stage to the test results.

## Current status

Working end to end for native-text PDFs, verified in the simulator against the
live backend: import → analyze → convert with live progress → real quality
report → preview → share / Save to Files.

One caveat worth knowing: **QuickLook does not render EPUB contents in the iOS
Simulator** (it shows a file card with type and size instead), because the
Simulator has no Apple Books. On a real device the preview renders, and "Share"
→ Books is the primary reading path either way. Everything else above was
exercised through the real UI, not mocked.

Deliberately declined with a clear error rather than faked: scanned PDFs
needing OCR, table and formula reconstruction, endnote sections, poetry-specific
line preservation, RTL. See [`docs/architecture.md`](docs/architecture.md) §0
for the full boundary of this slice.
