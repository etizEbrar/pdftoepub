# PDF → EPUB — Architecture

## 0. Scope of this build

- **Input**: native-text PDFs, scanned PDFs (local OCR), and mixed documents.
- **Pipeline**: analysis → per-page routing (native / OCR / image fallback) →
  geometry-aware extraction → reading order → table detection → verse detection →
  paragraph reconstruction → hyphenation repair → header/footer stripping →
  heading/structure detection → formula detection → footnote linking → endnote
  linking → TOC → EPUB3 generation → EPUBCheck validation → content-integrity
  accounting → quality report.
- **AI**: fully optional, OFF by default. Every feature above — including OCR,
  tables, formulas, endnotes, verse and RTL — runs with `AI_PROVIDER=none` and no
  API key. A test hard-blocks all outbound sockets and converts six document
  types through the real pipeline to prove it.
- **iOS**: full user-facing flow (import → analyze → convert → live progress →
  result → preview → share/save) against the real backend, with real error states.

### Ordering constraints in the pipeline

Several stages must run in a specific order; each was established by a real
failure observed while running the fixture corpus:

1. **Furniture detection before reference marking.** Marking footnote-reference
   candidates rewrites block text with sentinel characters, which stops a bare
   page number matching the page-number pattern and gets it misread as a note.
2. **Tables before verse.** Table cells are short, ragged-right lines that look
   exactly like poetry; consuming them first means verse only sees running text.
3. **Verse before paragraph reconstruction.** Verse lines end without terminal
   punctuation, so the paragraph merger would otherwise fuse a poem into one
   prose paragraph and destroy the line breaks.
4. **Footnotes before endnotes, then a finalize pass.** Footnote linking leaves
   unmatched markers wrapped so endnote linking can still claim them; whatever
   remains unmatched degrades to a plain superscript rather than a broken link.

### Known limitations

- **Bidi round-trip.** MuPDF returns RTL text in *visual* order; XHTML needs
  *logical* order, so RTL runs are restored (`pipeline/bidi.py`). Pure RTL
  paragraphs, RTL headings, Hebrew, and RTL containing a parenthesised Latin
  citation round-trip exactly through a real PDF. Lines that heavily interleave
  RTL with digits and long Latin runs keep every character, but a space or
  terminal punctuation mark may land on the other side of a direction boundary —
  inherent to inverting bidi without the original embedding levels.
- **Formula coverage is deliberately narrow.** Only a single unambiguous
  relation (`E = mc2`) becomes MathML. Fractions, integrals, matrices and nested
  structure become a high-resolution image of the real equation, because wrong
  mathematics is worse than a picture of the right mathematics.
- **Table detection needs ruled or well-separated columns.** A table set with
  neither ruling lines nor clear whitespace gutters may not be detected, and is
  then emitted as ordinary paragraphs rather than as a wrong grid.
- **OCR quality is Tesseract's.** Scans scoring below the confidence floor are
  preserved as page images rather than converted to unreliable text.
- Not implemented: accounts, IAP, PDF form fields, embedded media, and semantic
  reconstruction of deeply nested or multi-level-header tables.

## 0a. OCR routing and cost control

Per-page classification (`pipeline/ocr/classify.py`) is the gate that keeps OCR
cheap. A page with a usable text layer answers `NATIVE` and never invokes
Tesseract; only `SCANNED` and `MIXED` pages pay for it. A 520-page native-text
book therefore performs **zero** OCR passes and zero rasterization — asserted in
`tests/integration/test_performance.py`.

Rotation is handled by re-OCR, not by trusting orientation detection: Tesseract's
own OSD cannot recover 180° pages (it returns confident-looking nonsense scoring
in the mid-60s). The upright pass is accepted outright only above a separate
"confident accept" threshold; otherwise each orientation is tried and the
best-scoring result wins. That distinction matters — gating retries on the
reliability floor alone would accept the nonsense and never try the orientation
that reads correctly.

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
