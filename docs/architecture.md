# PDF → EPUB — Architecture

## 0. Scope of this build (vertical slice)

This repository is being built incrementally. The first slice targets:

- **Input**: native-text PDFs (real text layer; scanned/OCR PDFs are recognized and
  classified but routed to a not-yet-implemented path with a clear error, not faked).
- **Pipeline**: analysis → geometry-aware extraction → reading order → paragraph
  reconstruction → hyphenation repair → header/footer stripping → heading/structure
  detection → TOC → footnote detection → image extraction → EPUB3 generation →
  EPUBCheck validation → content-integrity check → quality report.
- **AI**: fully optional, OFF by default. The entire pipeline above runs and produces
  a valid, EPUBCheck-passing EPUB with `AI_PROVIDER=none` and no API key configured.
- **iOS**: full user-facing flow (import → analyze → convert → live progress → result
  → preview → share/save) against the real backend API below, with real error states.

Deferred to later iterations (explicitly, not stubbed-and-hidden): OCR for scanned
pages, table/formula reconstruction beyond image fallback, endnote cross-referencing,
poetry/verse-specific handling, RTL, accounts, IAP.

## 1. AI-optional architecture (hard requirement)

**A normal conversion must never require a paid AI API call.** The deterministic
pipeline is the product; AI is an optional accuracy booster the user can turn on.

```
AIProvider (protocol)
├── NoneProvider      — default. Always returns "no opinion"; never called for real.
├── LocalProvider      — free, local heuristics (no network, no model weights required
│                         for this slice); a slot for a real local model later
│                         (e.g. a local layout model) without changing callers.
├── AnthropicProvider  — optional, requires user-supplied ANTHROPIC_API_KEY.
├── OpenAIProvider     — optional, requires user-supplied OPENAI_API_KEY.
└── GoogleProvider     — optional, requires user-supplied GOOGLE_API_KEY.
```

Config: `AI_PROVIDER=none|local|anthropic|openai|google` (default `none`).
If a cloud provider is selected but no key is configured, the backend falls back to
`local` and logs a warning — it never hard-fails a conversion for a missing key.

### Confidence-gated escalation

Every structural decision (heading level, reading-order join, footnote link, table
vs. image-fallback, etc.) carries a confidence score in `[0, 1]`.

```
confidence >= 0.90   → deterministic result accepted, AI never consulted
0.70 <= conf < 0.90   → a second deterministic strategy is tried; still no AI by default
confidence < 0.70     → eligible for AI review (LocalProvider by default; cloud only
                         if the user explicitly configured a cloud provider)
```

### Cost control rules (non-negotiable)

- Never send the full book, or every page, to an AI model.
- Never ask a model to rewrite, summarize, paraphrase, or "fill in" text.
- AI providers only ever receive: (a) a small crop image and/or the extracted text of
  the *specific ambiguous block(s)*, plus a few blocks of surrounding context, and
  (b) a request for a structured JSON classification (role/level/confidence), never
  free-form prose that could replace source text.
- The AI response is only ever allowed to attach metadata (role, level, link target,
  confidence) to existing extracted blocks. It cannot introduce new text content into
  the document model. This is enforced in code, not just by prompt — see
  `app/pipeline/ai/provider.py::AIStructuralOpinion`, which has no field capable of
  carrying replacement body text.

## 2. Backend architecture

```
                 iOS APP
                    |
                    | HTTPS (local: http://localhost:8000)
                    v
              FastAPI backend
                    |
      +-------------+--------------+
      v              v              v
  PDF Engine     AI Engine      Job Store
 (PyMuPDF,       (provider      (SQLite,
  deterministic   abstraction,   in-process
  reconstruction) off by default) asyncio queue)
      |              |              |
      +-------------+--------------+
                    v
               EPUB Engine
                    v
               EPUBCheck (subprocess, local JRE)
                    v
             Final EPUB file (temp storage)
                    v
                  iOS (download, share, save)
```

Job queue: implemented as an in-process `asyncio` background-task runner backed by a
SQLite job table (`app/jobs/store.py`), behind a `JobQueue` protocol. This runs with
zero extra infrastructure (no Docker/Redis required) for local dev and is swappable
for Redis/RQ or Celery later for horizontal scaling without touching pipeline code.

Storage: uploaded PDFs and generated EPUBs live under a per-job temp directory
(`app/storage/temp_storage.py`), deleted on a TTL sweep and on `DELETE
/v1/conversions/{id}`. Nothing is logged that contains document text.

## 3. Document model

The pipeline operates on one shared model (`app/models/document.py`) from extraction
through EPUB generation, so text and geometry never separate:

```json
{
  "page": 12,
  "block_id": "p12_b07",
  "text": "Example paragraph",
  "bbox": [72, 120, 490, 180],
  "font": "ExampleFont",
  "font_size": 10.5,
  "bold": false,
  "italic": false,
  "baseline": 130,
  "line_id": "p12_l05"
}
```

Above this, blocks are grouped into `StructuralNode`s (heading/paragraph/list/
footnote/image/table/etc.) each carrying `role`, `level`, `confidence`, and
`source_block_ids` (so every rendered node traces back to concrete source blocks —
nothing in the EPUB has no corresponding PDF geometry).

## 4. Backend REST API

```
POST   /v1/conversions              multipart upload (file, mode) -> {id, status}
GET    /v1/conversions/{id}         -> job summary + status
GET    /v1/conversions/{id}/progress -> {stage, page, total_pages, percent}
GET    /v1/conversions/{id}/result  -> quality report + download info (once COMPLETED)
GET    /v1/conversions/{id}/download -> EPUB file bytes
DELETE /v1/conversions/{id}         -> deletes job + temp files
```

`mode` ∈ `fast | balanced | maximum_accuracy` (default `maximum_accuracy`).

Job states: `UPLOADED, ANALYZING, EXTRACTING, STRUCTURE_ANALYSIS, AI_REVIEW,
BUILDING_EPUB, VALIDATING, QUALITY_CHECK, COMPLETED, FAILED`.//
`AI_REVIEW` is always visited but is a no-op (near-instant) when `AI_PROVIDER=none`.

## 5. iOS architecture

SwiftUI, MVVM, async/await, protocol-based `APIClient`. Screens: Home,
DocumentPicker, ConversionSettings, ConversionProgress (polls `/progress`),
ConversionResult (renders the real quality report), EPUBPreview (QuickLook), Share
(ShareLink + Save to Files), Settings (holds `backendBaseURL` and, if the user opts
in, their own AI provider API key — never shipped in the app bundle).

No accounts, no IAP in this slice, per spec sections 44–45 ("do not introduce unless
genuinely necessary" / "keep billing logic modular so the app can ship without
monetization").
