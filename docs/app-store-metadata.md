# App Store Connect submission material

Everything here is ready to paste. Bracketed values are the only ones that
cannot be written for you — they are facts about you or your hosting, not about
the software.

## Identity

| Field | Value |
| --- | --- |
| Bundle ID | `com.pdftoepub.app` |
| Team | `23766BZUS5` |
| Version | `1.0` |
| Build | `1` |
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

PDF to EPUB converts using a server you configure. See the Support page for
setup.
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

```
This app converts PDFs using a hosted server. No account or login is required.

Server: https://pdftoepub-backend.onrender.com

PLEASE READ FIRST — the first request may take up to 60 seconds.
The backend runs on a free hosting tier that suspends the service after about
15 minutes without traffic. The first conversion after an idle period has to
wake it, so the app can appear to sit on "Uploading" or "Queued" for up to a
minute. It is not frozen. Subsequent conversions start immediately. If you would
like us to move it to an always-on tier for the duration of the review, please
let us know and we will do so.

Steps:
1. Open the app and tap "Select PDF".
2. Choose any PDF. A sample is included in the app's own folder, reachable
   through the Files picker under "On My iPhone" > "PDF to EPUB".
3. Pick a conversion mode and tap "Convert to EPUB".
4. Progress is shown per page. Allow the extra wake-up time on the first run.
5. The quality report appears — pages, chapters, footnotes linked, EPUB3
   validation, and whether any AI was used (it reports "None (fully local)").
6. Tap "Preview EPUB" to read it in the app, or "Share or Save to Files" to
   open it in Apple Books.

Notes:
- No AI service is used. Conversion is deterministic software running on the
  server; the quality report shows "None (fully local)" for every conversion.
- The uploaded PDF is deleted from the server as soon as the app has the
  finished EPUB. Nothing is retained and no account is associated with it.
- If a server address field is visible in Settings, the build was not configured
  with a hosted backend. The submitted build is, and the field is hidden.
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
