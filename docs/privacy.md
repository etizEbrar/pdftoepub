# Data lifecycle

What actually happens to a document, traced through the code rather than
described in the abstract. File and function references are the authority; if
they disagree with this page, the code is right and this page is a bug.

## The short version

A PDF is uploaded, converted, downloaded, and deleted. No account is required,
no analytics are collected, no third party receives the document, and no AI
service is contacted. The engine is fully deterministic and local.

## Step by step

### 1. Selection — nothing has left the device

The user picks a PDF. `PDFInspector` (`ios/PDFtoEPUB/Core/Services/PDFInspector.swift`)
opens it **on the device** to read the page count, title and author, and to
reject damaged or password-protected files. Nothing is transmitted at this
stage; a file rejected here never leaves the phone.

`DiskSpace` (`ios/PDFtoEPUB/Core/Services/DiskSpace.swift`) then checks there is
room for the result, again locally.

### 2. Upload

`POST /v1/conversions` sends the PDF over HTTPS to the server the user
configured. The request carries the file and a conversion mode. There is no
identifier for the user, because there are no accounts: the server never learns
who sent the document.

The server (`backend/app/api/routes.py`) streams the upload to disk in 1 MB
chunks, rejecting it the moment it exceeds `MAX_UPLOAD_MB` or fails the `%PDF-`
check. A rejected upload is deleted immediately and never becomes a job.

### 3. Where it lives while it is converted

A job id is generated with `uuid.uuid4().hex` — 128 bits of randomness, not
guessable and not derived from the file or the user. Everything for that job
lives under one directory:

```
<DATA_DIR>/jobs/<job_id>/source/<filename>      the uploaded PDF
<DATA_DIR>/jobs/<job_id>/images/                page images, when a region
                                                 cannot be read as text
<DATA_DIR>/jobs/<job_id>/output/<slug>.epub     the finished book
```

Job *metadata* — the source filename, stage, detected title and the quality
report — is a row in a local SQLite database at `<DATA_DIR>/jobs.sqlite3`. This
is on the same machine; it is not a hosted database service.

### 4. Conversion — entirely local

Extraction, OCR, structure detection and EPUB generation all run in-process:

- **PyMuPDF** reads the PDF geometry.
- **Tesseract** performs OCR, as a local binary. No OCR service is contacted and
  no page image is uploaded anywhere.
- **EPUBCheck** validates the result, as a local Java process.

`AI_PROVIDER` defaults to `none`. With that default **no network request leaves
the server at all** during a conversion, and no API key is required.

If an operator deliberately sets `AI_PROVIDER=anthropic`, low-confidence
*fragments* would be sent to that provider for review — never the whole book.
This is off by default and off in the shipped configuration
(`backend/fly.toml` sets `AI_PROVIDER = "none"`). The iOS app displays the
provider the server reports, so the user can see it is `none`.

### 5. Download

`GET /v1/conversions/<job_id>/download` returns the EPUB. The app writes it to
its own temporary directory inside the app container
(`APIClient.downloadEPUB`). From there the user can preview it or share it to
Apple Books or anywhere else, which is an explicit action they take.

### 6. Deletion

Two independent mechanisms, so a failure of either still results in deletion:

1. **Immediately after download.** `ConversionViewModel` calls
   `service.cleanUp(id:)` as soon as the EPUB is on the device, which issues
   `DELETE /v1/conversions/<job_id>`. That removes the job directory *and* the
   database row. In the normal case the document exists on the server only for
   the length of the conversion.
2. **A TTL sweep.** `sweep_expired_jobs` runs hourly and deletes any job older
   than `JOB_TTL_HOURS` — files and database row together. This catches jobs
   whose client vanished mid-conversion.

`backend/fly.toml` sets `JOB_TTL_HOURS = 6`, so the outside limit is six hours
even for an abandoned job.

Verified by `tests/unit/test_security.py::TestRetention` and
`ios/PDFtoEPUBTests/DataLifecycleTests.swift`.

## What is logged

Application logs record job ids, stages, page counts, durations and error
codes. They do **not** record the contents of any PDF, any extracted text, or
any OCR output. The log statements were audited for this; the only user-derived
value that appears is the job id, which is random.

Note that a reverse proxy or hosting platform in front of this service keeps its
own access logs, typically including client IP addresses and request paths. Those
paths contain job ids but never document content.

## What the server never does

- It does not require or create an account.
- It does not store the document beyond the lifecycle above.
- It does not send the document, or any part of it, to a third party in the
  default configuration.
- It does not use the document to train anything.
- It does not embed tracking or analytics SDKs. The iOS app contains none, which
  is why `PrivacyInfo.xcprivacy` declares no collected data types and no
  tracking domains.

## Abuse protection and IP addresses

Rate limiting (`backend/app/api/ratelimit.py`) counts recent requests per client
IP, in memory. Those counters hold an IP address for at most an hour and are
lost on restart. They are not written to disk and are not associated with any
document.
