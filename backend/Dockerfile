# PDF to EPUB conversion backend.
#
# Everything the pipeline needs is baked in, because the conversion is fully
# local: PyMuPDF for geometry, Tesseract for OCR, and a JRE for EPUBCheck. No
# API key is required or used — AI_PROVIDER defaults to "none".
#
# Deliberately a single long-running container rather than a serverless
# function: a conversion runs for tens of seconds to minutes, holds an
# in-process job queue, and writes temporary files to local disk. None of that
# survives a function-per-request model.

FROM python:3.12-slim-bookworm AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# tesseract-ocr        — local OCR, no network, no per-page cost
# tesseract-ocr-eng/tur — language data (add more with OCR_LANGUAGES)
# default-jre-headless — EPUBCheck is a Java jar
# fonts-dejavu-core    — glyph coverage when rasterizing fallback regions
RUN apt-get update && apt-get install --no-install-recommends -y \
        tesseract-ocr \
        tesseract-ocr-eng \
        tesseract-ocr-tur \
        default-jre-headless \
        fonts-dejavu-core \
        curl \
        unzip \
    && rm -rf /var/lib/apt/lists/*

# EPUBCheck, pinned by version and verified by checksum so a compromised or
# swapped release cannot silently enter the image.
ARG EPUBCHECK_VERSION=5.3.0
ARG EPUBCHECK_SHA256=6c07e68584b2e2ce2f89fe06e1246dfead3eb36b46b340e7d93524f29dcff6c5
RUN curl -fsSL -o /tmp/epubcheck.zip \
        "https://github.com/w3c/epubcheck/releases/download/v${EPUBCHECK_VERSION}/epubcheck-${EPUBCHECK_VERSION}.zip" \
    && echo "${EPUBCHECK_SHA256}  /tmp/epubcheck.zip" | sha256sum -c - \
    && unzip -q /tmp/epubcheck.zip -d /opt \
    && rm /tmp/epubcheck.zip \
    && printf '#!/bin/sh\nexec java -jar /opt/epubcheck-%s/epubcheck.jar "$@"\n' "${EPUBCHECK_VERSION}" \
        > /usr/local/bin/epubcheck \
    && chmod +x /usr/local/bin/epubcheck

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Uploaded documents are private user data. They live only under this directory
# and are swept on a TTL — see app/storage/temp_storage.py.
RUN mkdir -p /data && useradd --create-home --uid 10001 appuser && chown -R appuser /data /app
USER appuser

ENV ENVIRONMENT=production \
    AI_PROVIDER=none \
    DATA_DIR=/data \
    HOST=0.0.0.0 \
    PORT=8000

EXPOSE 8000

# The platform restarts the container if this stops answering.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=4).status==200 else 1)"

# One uvicorn process. The job queue and its workers live inside it, so scaling
# means more machines, not more workers in this container — see docs/deployment.md.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --proxy-headers --forwarded-allow-ips='*' --no-server-header"]
