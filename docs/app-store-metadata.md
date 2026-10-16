# App Store Connect submission material

Everything here is ready to paste. Bracketed values are the only ones that
cannot be written for you — they are facts about you or your hosting, not about
the software.

## Identity

| Field | Value |
| --- | --- |
| Bundle ID | `com.pdftoepub.app` |
| Team | `23766BZUS5` |
| Version | `1.0.1` |
| Build | `8` |
| Devices | iPhone only (`UIDeviceFamily = [1]`) |
| Minimum iOS | 17.0 |
| Encryption | `ITSAppUsesNonExemptEncryption = false` — standard HTTPS only |

## App name and subtitle

**Name:** PDF to EPUB

**Subtitle (30 char max):** `Read PDFs as real ebooks` (24)

## Promotional text (170 max)

```
Turn a PDF into an ebook that reflows to your screen. Chapters, footnotes and
tables are rebuilt — not screenshotted. Your file is deleted after conversion.
```

## Description

```
PDF to EPUB rebuilds a PDF as a real ebook.

A PDF is a picture of a page. On a phone that means pinching, scrolling
sideways, and type too small to read. An EPUB reflows: you pick the font size,
and the text fits your screen.

This app does the rebuilding properly.

RECONSTRUCTED, NOT SCREENSHOTTED
• Paragraphs are rejoined across line and page breaks
• Words hyphenated across a line break are put back together
• Chapters and headings become a real table of contents
• Footnotes and endnotes become tappable links, and link back
• Tables stay tables, with their rows and columns intact
• Poetry keeps its line breaks; prose never becomes poetry
• Right-to-left and mixed-direction text keeps its reading order

SCANNED BOOKS TOO
Pages without a text layer are read with OCR. Pages that already have good text
are left alone, so a scanned book with an existing text layer converts in
seconds instead of being needlessly re-read.

WHERE THE TEXT IS UNCERTAIN, IT SAYS SO
The app reports what it did: how many pages needed OCR, how many footnotes were
linked, whether validation passed, and which passages it was unsure about.
Where a page cannot be read confidently, the original page image is kept rather
than filled with invented words. Your author's text is never rewritten.

PRIVATE BY DESIGN
• No account, no tracking, no ads
• No AI service is involved in the conversion
• Your PDF is deleted from the server once you have your ebook
• Your documents are never used to train anything

Every ebook is validated with EPUBCheck before you get it, so it opens in Apple
Books and everywhere else.

There is nothing to set up: books convert on the app's own server. If you would
rather run the conversion server yourself, the Support page explains how.
```

## What's New in This Version (1.0.1)

```
• Read the whole book in the app: Preview now moves chapter by chapter, at a readable size.
• Scanned books are read on your iPhone, so long scans finish instead of timing out.
• Clearer messages when the server can't be reached, with Try again that really tries again.
• A book over the size or page limit is caught before it is uploaded.
• No more endless "Waking the conversion server" wait.
```

## Keywords (100 char max, comma-separated, no spaces)

```
epub,pdf,ebook,convert,converter,reflow,ocr,books,reader,kitap,dönüştür,epub3,scan
```

## Category

- Primary: **Productivity**
- Secondary: **Reference**

## Age rating

4+. No objectionable content, no user-generated content shown to others, no web
browsing, no gambling.

## App Privacy answers

Answer **"Data Not Collected"**. This matches `PrivacyInfo.xcprivacy`, which
declares no tracking, no tracking domains, and no collected data types.

The uploaded PDF is processed to deliver the requested function and deleted
immediately afterwards; it is not linked to identity, not used for tracking, and
not retained. If the questionnaire asks about it, the correct category is
processing not collection.

## URLs

| Field | Value |
| --- | --- |
| Support URL | `https://etizebrar.github.io/pdftoepub/support.html` |
| Privacy Policy URL | `https://etizebrar.github.io/pdftoepub/privacy.html` |
| Marketing URL | `https://etizebrar.github.io/pdftoepub/` (optional) |

Publish `site/` at any static host — GitHub Pages, Cloudflare Pages, Netlify —
and these three URLs exist. The pages are complete apart from the bracketed
owner name and support email.

## Review notes

Submitted with build 1.0.1 (8) on 2026-10-17, with `Sample-Book.pdf` (the
generated `tests/fixtures/corpus/turkish_novel.pdf`) attached under App Review
Information. One line per bullet in What's New: the store shows line breaks as
typed.

```
This app converts PDFs into EPUB ebooks using a hosted server. No account or
login is required, and nothing needs configuring.

Server: https://pdftoepub-backend.onrender.com

PLEASE READ FIRST — the first conversion may take up to a minute to start.
The backend runs on a hosting tier that suspends the service after about 15
minutes without traffic. The first conversion after an idle period wakes it,
and after a few seconds the app says so ("Waking the conversion server"). It
is not frozen, and later conversions start immediately. If you would like it
moved to an always-on tier for the review, let us know and we will do so.

Steps:
1. Open the app and tap "Select PDF".
2. Choose any PDF from Files. A sample PDF is attached to this submission.
3. Pick a conversion quality and tap "Convert to EPUB". Progress is shown by
   stage and page. A scanned PDF is first read on the device ("Reading the
   scan on this iPhone").
4. "Conversion complete" shows the book's pages, chapters and words.
5. Tap "Preview EPUB" to read it in the app; the arrows at the bottom move
   between chapters. "Share or Export" opens it in Apple Books or saves it to
   Files. "Send to Kindle" hands it to the Kindle app when that is installed.

Notes:
- Settings shows the server address, pre-filled with the app's own server.
  Nothing needs changing; the field is there for people who run their own
  conversion server. "Test connection" checks the server and shows that no AI
  provider is in use ("Structural review: Not in use").
- No AI service is used in the conversion.
- The uploaded PDF is deleted from the server as soon as the app has the
  finished EPUB. Nothing is retained and no account is associated with it.
```

## Export compliance

The app uses only standard HTTPS provided by the operating system.
`ITSAppUsesNonExemptEncryption = false` is already set in the build, so no
additional documentation is required.

## Screenshots

Required: iPhone 6.9" (1320 × 2868 or 1290 × 2796). iPad is no longer required —
the target ships iPhone-only.

`ios/scripts/capture_screenshots.sh` drives the simulator and writes the five
required frames. It needs a running backend, since the result and quality-report
screens only exist after a real conversion.
