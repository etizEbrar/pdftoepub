# Deploying the conversion backend

**Status: not deployed.** No cloud provider credentials exist on the development
machine, so nothing has been provisioned and no public URL exists. This document
is what makes deployment a short, checkable procedure once an account exists —
see [What you must provide](#what-you-must-provide).

## What this workload actually needs

Established by auditing the code, not assumed:

| Requirement | Detail |
| --- | --- |
| Runtime | Python 3.12 |
| Web framework | FastAPI on uvicorn |
| PDF engine | PyMuPDF (`pymupdf==1.25.1`) |
| OCR | Tesseract binary + language data, invoked as a subprocess |
| Validation | EPUBCheck 5.3.0 — a **Java** jar, so the image needs a JRE |
| Database | SQLite on local disk |
| Job queue | In-process asyncio workers (`JOB_CONCURRENCY`, default 2) |
| Storage | Local filesystem for uploads, page images and output |
| Memory | ~180 MB peak for a 520-page text book; 2 GB gives headroom for OCR of large scans at 300 dpi |
| CPU | Conversion is CPU-bound; ~48 ms/page on text books |
| Network egress | **None during conversion** with `AI_PROVIDER=none` |

Two consequences follow, and they rule out most of the cheap options:

- **Serverless is unsuitable.** A conversion runs for tens of seconds to
  minutes, holds an in-process queue, and writes to local disk. Function
  runtimes with short timeouts and ephemeral, per-request containers break all
  three.
- **A single long-lived container is the right shape.** Scaling means more
  machines behind the load balancer, not more uvicorn workers in one container:
  the job queue lives inside the process.

## Chosen architecture

One container, built from `backend/Dockerfile`, on a platform that provides TLS,
a health check and restart-on-failure. `backend/fly.toml` configures this for
Fly.io, which fits because it is container-native, has a small always-on machine
tier, terminates TLS automatically and mounts a volume for the temp directory.

Nothing about the application is Fly-specific. The same image runs on Render,
Railway, a container service, or a plain VPS with Docker and a TLS-terminating
reverse proxy. Only `fly.toml` would be replaced.

```
  iOS app ──HTTPS──▶ platform TLS/edge ──▶ container ──▶ local disk
                                             │            (uploads, EPUB,
                                             │             SQLite, TTL-swept)
                                             └── tesseract / epubcheck (local)
```

## The image

`backend/Dockerfile` builds on `python:3.12-slim-bookworm` and installs
Tesseract with English and Turkish data, a headless JRE, and EPUBCheck 5.3.0
pinned by version **and verified by SHA-256** so a swapped release cannot enter
the image silently. It runs as a non-root user and declares a `HEALTHCHECK`.

> **Not yet built.** Docker is not installed on the development machine, and
> there was insufficient free disk to install it safely. The Dockerfile is
> written from the audited dependency list and the EPUBCheck URL and checksum
> were verified against the real release, but **the image has never been
> built**. Expect to iterate on the first `fly deploy`.

## Configuration

Set through environment variables; the shipped values are in `fly.toml`.

| Variable | Production value | Why |
| --- | --- | --- |
| `ENVIRONMENT` | `production` | Hides `/docs`, `/redoc`, `/openapi.json`; enables HSTS; binds all interfaces |
| `AI_PROVIDER` | `none` | Fully local, deterministic conversion. No API key. **Do not change.** |
| `DATA_DIR` | `/data` | On the mounted volume so an in-flight job survives a restart |
| `JOB_TTL_HOURS` | `6` | Outside limit before an abandoned job's files and record are swept |
| `JOB_CONCURRENCY` | `2` | Bounds CPU and memory per machine |
| `MAX_UPLOAD_MB` | `200` | Enforced while streaming, so an oversized upload never occupies RAM |
| `MAX_PAGE_COUNT` | `2000` | Stops a crafted PDF occupying a worker for hours |
| `OCR_LANGUAGES` | `eng+tur` | Must match the language data installed in the image |
| `CORS_ALLOW_ORIGINS` | *(unset)* | The iOS client is not a browser. Leave empty unless you add a web client |
| `RATE_LIMIT_UPLOADS_PER_HOUR` | `20` | Per client IP |

Anything secret would go through `fly secrets set`, never into `fly.toml`.
**At present there are no secrets**, because there is no API key and no account
system — which is a deliberate property of the design, not an oversight.

## Deployment procedure

Once you have an account (see below):

```bash
# 1. Install the CLI  (https://fly.io/docs/flyctl/install/)
brew install flyctl

# 2. Authenticate — opens a browser
fly auth login

# 3. From the repository root
cd backend

# 4. Claim an app name; this writes it into fly.toml
fly apps create YOUR-APP-NAME

# 5. Edit fly.toml: set `app` and `primary_region`
#    (regions: fly platform regions)

# 6. Create the volume for temporary conversion files
fly volumes create pdftoepub_data --size 3 --region YOUR-REGION

# 7. Build and deploy
fly deploy

# 8. Confirm it is actually up
curl https://YOUR-APP-NAME.fly.dev/health
# expect: {"status":"ok","ai_provider":"none"}
```

## Verify before pointing the app at it

Run all of these against the **public HTTPS URL**, not localhost:

```bash
BASE=https://YOUR-APP-NAME.fly.dev

# Health, and proof no paid AI is in use
curl -s $BASE/health

# The interactive docs must NOT be published in production
curl -s -o /dev/null -w "docs=%{http_code}\n"     $BASE/docs      # expect 404
curl -s -o /dev/null -w "openapi=%{http_code}\n"  $BASE/openapi.json  # expect 404

# HTTP must redirect to HTTPS, never serve the API in the clear
curl -s -o /dev/null -w "http=%{http_code}\n" http://YOUR-APP-NAME.fly.dev/health

# Security headers
curl -sI $BASE/health | grep -iE "strict-transport|x-content-type|content-security"

# A real conversion, end to end
JOB=$(curl -s -X POST $BASE/v1/conversions \
        -F "file=@some-book.pdf" -F "mode=maximum_accuracy" | jq -r .id)
curl -s $BASE/v1/conversions/$JOB/progress
curl -s -o out.epub $BASE/v1/conversions/$JOB/download
epubcheck out.epub
```

Then, and only then, set the iOS production URL:

```bash
# In ios/project.yml, or per-build:
xcodebuild archive … PRODUCTION_BACKEND_URL=https://YOUR-APP-NAME.fly.dev
```

`BackendEnvironment` refuses to use a value that is empty or a private address,
so a misconfiguration surfaces as "set up your server" rather than a silent
failure.

## Operating it

- **Logs:** `fly logs`. They contain job ids, stages and error codes — never
  document content. Confirmed by audit.
- **Restarts:** the platform restarts the machine when the `/health` check
  fails three times in a row.
- **Scaling:** `fly scale count N`. Each machine runs its own queue and its own
  SQLite file; a job is served by the machine that accepted it. Sticky routing
  is not required because the client polls by job id and the platform routes to
  a healthy machine — **if you scale beyond one machine, verify this**, as a
  poll landing on a different machine would report the job as missing. For a
  single machine, which is the shipped configuration, this does not arise.
- **Cost:** one always-on shared-CPU machine with a small volume is the minimum,
  because `min_machines_running = 1` keeps a conversion from being killed
  mid-flight.

## What you must provide

Deployment cannot proceed without these, and none of them can be created from
this machine:

1. **A Fly.io account** (or another container host), with billing configured.
   Sign up at fly.io, then `fly auth login`.
2. **An app name**, which becomes the default hostname
   `https://<name>.fly.dev`. It must be globally unique, so only you can pick
   it.
3. **A region**, chosen for where your users are.
4. **Optionally, a custom domain** and its DNS records, if you do not want to
   use the `.fly.dev` hostname. `fly certs add yourdomain.com` issues the
   certificate.

Once the app answers on a public HTTPS URL, the remaining work is: set
`PRODUCTION_BACKEND_URL`, re-archive the iOS app, and run the external
verification above.
