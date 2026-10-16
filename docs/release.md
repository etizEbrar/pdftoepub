# Release status and what App Store submission still needs

This file records what is verified, what is not, and what only the account
holder can supply. Nothing here is aspirational — every "verified" line was
produced by running the thing described.

## 1.0.1 (8) — verified 2026-10-16

The App Store serves 1.0 (6). Everything below is on branch
`claude/youthful-rubin-rbgd55` and none of it reaches users until 1.0.1 ships.

### What changed since 1.0 (6)

| Commit | Change |
| --- | --- |
| `f7d48bf` | Every request bounded (no endless "Waking the conversion server"); limits checked before upload; address field always editable |
| `64c2e6d` | Scanned pages read on the device with Vision |
| `45790f6` | The error names the address it tried and offers "Use the app's own server" |
| `cc36d0f` | A debug build's address no longer outlives it; unreachable-server copy depends on the address; "Try again" really retries (it fell through to the home screen); bumped to build 8 |
| this release's last commit | See below |

The last commit:

- **Preview showed only the first chapter.** The spine holds only chapter
  files and chapters do not link to one another, so the in-app reader had no
  way past chapter 1. It now has a chapter bar (previous, "Chapter n of N",
  next); swiping back returns from a note link, and the bar follows.
- **Preview left a copy of the book on disk every time it opened.** Previews
  now unpack under `tmp/epub-previews`, are removed on close, and any leftover
  is swept before the next one opens.
- **Buttons could be pushed off the screen.** The home, error and progress
  screens were centred stacks; in landscape or at large text sizes they
  overflowed and hid "Select PDF" / "Try again". Their content now scrolls and
  the actions are pinned, as on the settings and result screens.
- **Page limit checked before upload.** The server publishes
  `max_page_count` but only enforced it after the whole book was uploaded and
  queued. The app knows the page count locally and now refuses first.
- **Error copy.** The size message no longer tells people to "raise
  MAX_UPLOAD_MB on your own server"; 5xx and client-side transport failures no
  longer show a raw code; a dropped connection no longer says the device is
  offline; a job lost to a server restart says so instead of "This conversion
  job no longer exists". Backend `ocr_too_slow` no longer asks the reader to
  "raise the server's conversion time limit" (takes effect when the backend
  deploys).
- **OCR memory.** One autorelease pool per page, so a long scan's per-page
  Vision and PDFKit buffers are released as it goes. Only a 20-page scan has
  ever been measured on a phone.
- **Finished books no longer pile up** in the temporary folder: "Convert
  another PDF" deletes the last one.
- **Reader tests no longer fail on every machine but one.** They read a
  converted book from a scratch folder on one Mac and used `XCTUnwrap`, so
  anywhere else they failed; they now skip, and new self-contained tests cover
  the reader on any machine.
- **Privacy manifest.** File-timestamp access now also declares `3B52.1`
  (metadata of files the user picked in the document picker), alongside
  `C617.1`.
- **Privacy policy and landing page.** Both said scanned page images "never
  leave your phone". The PDF — scanned pages included — is uploaded to build
  the EPUB; only the bitmaps rendered for Vision stay on the device. Corrected
  in `docs/privacy-policy.md` (regenerated into `site/`) and `landing/`.
  **Not yet published** — review the wording, then run `scripts/publish-site.sh`.
- **App Store metadata.** `docs/app-store-metadata.md` now matches this build:
  version, a What's New, and review notes that no longer say a visible address
  field means a misconfigured build, describe a removed AI row, or promise a
  sample PDF the app does not ship.

### Verified here

| Check | Result |
| --- | --- |
| Live backend: `scripts/verify-deployment.sh https://pdftoepub-backend.onrender.com` | ALL CHECKS PASSED — health, `/docs` and `/openapi.json` 404, HSTS, real upload → convert → download → delete |
| Independent EPUBCheck 5.3.0 (SHA-256 verified) on an EPUB from the live server | 0 fatals, 0 errors, 0 warnings |
| Filenames with Turkish letters and with `"` sent exactly as the app sends them | Stored and titled correctly by the live server; no change needed |
| iOS logic, compiled on Linux with Swift 6.1 (see below) — Debug | 83 run, 5 skipped, 0 failed |
| Same, Release with `PRODUCTION_BACKEND_URL=https://pdftoepub-backend.onrender.com` (the App Store configuration) | 85 run, 5 skipped, 0 failed |
| Every changed Swift file, `swiftc -parse` | All parse |
| `Info.plist`, `PrivacyInfo.xcprivacy`, UI-test `Info.plist` | Valid property lists |
| Backend suite (Python 3.13, EPUBCheck present, no Tesseract) | 436 passed, 46 skipped, 5 failed — the 5 are `test_corpus.py` books generated with this machine's fonts, and fail identically on the unmodified code |
| Support and privacy URLs | Both 200 at `pdftoepub.tech` (the github.io links redirect there) |

The Linux harness compiles the app's Foundation-level sources unmodified —
settings, networking, models, the conversion service and view model, the EPUB
archive and document — with stand-ins only for PDFKit, Vision and Apple's
Compression (replaced by zlib's raw inflate, which is what `COMPRESSION_ZLIB`
is). It runs the repository's own `BackendEnvironmentTests`,
`ConversionServiceTests`, `ModelDecodingTests` and `EPUBReaderTests`, plus
Linux twins of the new `DataLifecycleTests` and scenario tests in the shipped
configuration — among them, an install carrying a debug build's localhost
recovers on launch, and a book from the live server opens in the reader
(stored and deflate) with its chapters in order. The 5 skips are the reader
tests that need the corpus on one Mac.

### Not verified — do this before archiving

There is no Mac in the environment that produced this, so nothing below has
been built by Xcode or run on a simulator or device.

1. **Build and run every test** — the SwiftUI, UIKit, WebKit and Vision files
   changed here are only parse-checked:

   ```bash
   cd ios && xcodegen generate
   xcodebuild -project PDFtoEPUB.xcodeproj -scheme PDFtoEPUB \
     -destination 'platform=iOS Simulator,name=iPhone 17 Pro' test
   ```

2. **Walk the app**, on an iPhone SE (3rd generation) simulator and one
   current iPhone, portrait and landscape, at the default text size and at
   Accessibility 5:

   | Do | Expect |
   | --- | --- |
   | Fresh install, open Settings, Test connection | The onrender address, "Connected", Structural review "Not in use" |
   | Convert a text PDF | Progress by stage, then "Conversion complete" |
   | Preview EPUB | Chapter bar; next and previous move; the counter is right |
   | Tap a footnote that leads to another chapter, then swipe back | Returns to the place tapped; the counter follows |
   | Done, then Preview again | Opens again normally |
   | Convert another PDF | Back to the home screen |
   | Airplane mode, convert | "No network connection"; Try again converts once back online |
   | Settings address `http://localhost:8000`, convert (on a device) | Explains localhost; "Use the app's own server" retries and succeeds |
   | A PDF over 600 pages | Refused before any upload, naming both page counts |
   | Every screen above at Accessibility 5 in landscape | Every button reachable by scrolling or pinned |

3. **A long scan on a device** — 150+ scanned pages, with Xcode's memory gauge
   open during "Reading the scan on this iPhone". Memory should stay flat;
   this has never been measured.

### Archive and upload

```bash
cd ios
xcodegen generate
xcodebuild archive -project PDFtoEPUB.xcodeproj -scheme PDFtoEPUB \
  -configuration Release -destination 'generic/platform=iOS' \
  -archivePath build/PDFtoEPUB.xcarchive -allowProvisioningUpdates

# What App Store Connect will see. Expect 1.0.1, 8, and the onrender URL.
APP=build/PDFtoEPUB.xcarchive/Products/Applications/PDFtoEPUB.app
/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' \
  -c 'Print :CFBundleVersion' -c 'Print :PRODUCTION_BACKEND_URL' "$APP/Info.plist"
```

Then Xcode → Window → Organizer → the archive → Distribute App → App Store
Connect → Upload.

- If build 8 has already been uploaded under 1.0.1, raise
  `CURRENT_PROJECT_VERSION` in `ios/project.yml`: a build number is accepted
  once per version.
- If 1.0.1 has already been **released**, its train is closed (90186):
  raise `MARKETING_VERSION` to `1.0.2` as well.

### App Store Connect

1. **Version 1.0.1.** If it is already in review with build 7, remove it from
   review and select build 8.
2. **What's New** — from `docs/app-store-metadata.md`.
3. **Review notes** — paste the 1.0.1 notes from `docs/app-store-metadata.md`,
   and attach a sample PDF under App Review Information → Attachment.
4. **Privacy policy** — publish the corrected `site/` first
   (`scripts/publish-site.sh`), so the URL Apple has on file is accurate.
5. **App Privacy** — "Data Not Collected", unchanged; it matches
   `PrivacyInfo.xcprivacy`.
6. **Export compliance** — answered in the build
   (`ITSAppUsesNonExemptEncryption = false`).
7. **Backend** — merge to the branch Render deploys from, so the server-side
   message fix is live.

### Decisions only the account holder can make

- **AI wording.** The App Store description says "No AI service is involved",
  and App Privacy says no data is collected. Settings says the server "can ask
  Claude to classify just that fragment", and the landing page lists
  "Ambiguous fragments, if you enable review" — but there is no such switch in
  the app. With `AI_PROVIDER=none` that is true but reads as a disclosure of
  third-party sharing. Make the Settings text match the server you ship, and
  before enabling Claude, update App Privacy and ask for consent in the app
  (Guideline 5.1.2(i)).
- **Server region.** `pdftoepub-backend.onrender.com` resolves through
  `gcp-us-west1-1.origin.onrender.com`, while `render.yaml` and the privacy
  policy say Frankfurt. Check the region in the Render dashboard; the policy
  states it.
- **Review-time cold starts.** The free instance sleeps after 15 minutes.
  The review notes explain the wait; an always-on instance during review
  removes it.

### Known limitations

- A file from iCloud Drive that is not downloaded yet may fail to open with
  "We couldn't open this PDF". Untested.
- A failure inside the system file picker is ignored silently. Rare.
- `UIFileSharingEnabled` shows an empty "PDF to EPUB" folder in Files; the
  app writes nothing there.
- The chapter counter follows links by the page that finishes loading; a
  back-forward cache restore that does not report one would leave it a
  chapter behind until the next move.
