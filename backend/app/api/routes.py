from __future__ import annotations

import re
import uuid

from fastapi import APIRouter, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from app.api.ratelimit import SlidingWindowLimiter, client_key
from app.core.config import settings
from app.core.errors import FileTooLargeError, UnsupportedPDFError
from app.core.logging import get_logger
from app.jobs import store
from app.jobs.instance import job_queue
from app.models.api import (
    ConversionCreatedResponse,
    ConversionProgressResponse,
    ConversionResultResponse,
    ConversionSummaryResponse,
)
from app.models.job import ConversionMode, Job, JobStage
from app.storage.temp_storage import delete_job_files, upload_path_for

logger = get_logger(__name__)
router = APIRouter(prefix="/v1/conversions", tags=["conversions"])

_PDF_MAGIC = b"%PDF-"
_UPLOAD_CHUNK = 1024 * 1024

# Job ids are generated as uuid4().hex, so anything else is either a bug or
# someone probing. Validating the shape keeps hand-crafted ids away from the
# filesystem helpers entirely, rather than relying on the store lookup to fail.
_JOB_ID_RE = re.compile(r"\A[0-9a-f]{32}\Z")

# Only characters that are safe unquoted in a Content-Disposition filename.
# Everything else becomes "_", so a filename can't inject header syntax.
_UNSAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9._ -]")

_upload_limiter = SlidingWindowLimiter(settings.rate_limit_uploads_per_hour, 3600.0)


def _safe_download_name(source_filename: str) -> str:
    stem = source_filename.rsplit(".", 1)[0] or "book"
    cleaned = _UNSAFE_FILENAME_CHARS.sub("_", stem).strip() or "book"
    return f"{cleaned[:100]}.epub"


def _get_job_or_404(job_id: str) -> Job:
    if not _JOB_ID_RE.match(job_id):
        # Same response as a genuinely missing job: a probe learns nothing about
        # which ids exist or how they are shaped.
        raise HTTPException(status_code=404, detail="This conversion job no longer exists.")
    job = store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="This conversion job no longer exists.")
    return job


@router.post("", response_model=ConversionCreatedResponse, status_code=201)
async def create_conversion(
    request: Request,
    file: UploadFile = File(...),
    mode: ConversionMode = Form(default=ConversionMode.MAXIMUM_ACCURACY),
) -> ConversionCreatedResponse:
    caller = client_key(request)
    if settings.rate_limit_enabled:
        allowed, retry_after = _upload_limiter.check(caller)
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail="Too many conversions started recently. Please try again later.",
                headers={"Retry-After": str(retry_after)},
            )

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        _refund(caller)
        raise UnsupportedPDFError("Please choose a PDF file.")

    job_id = uuid.uuid4().hex
    upload_path = upload_path_for(job_id, file.filename)
    upload_path.parent.mkdir(parents=True, exist_ok=True)

    # Streamed to disk in chunks and abandoned the moment it exceeds the limit.
    # Reading the whole upload first would let anyone spend `max_upload_mb` of
    # RAM per request before the size check ever ran.
    max_bytes = settings.max_upload_mb * 1024 * 1024
    written = 0
    try:
        with upload_path.open("wb") as out:
            while chunk := await file.read(_UPLOAD_CHUNK):
                if written == 0 and not chunk.startswith(_PDF_MAGIC):
                    raise UnsupportedPDFError()
                written += len(chunk)
                if written > max_bytes:
                    raise FileTooLargeError(
                        f"This PDF is larger than the {settings.max_upload_mb}MB limit."
                    )
                out.write(chunk)
        if written == 0:
            raise UnsupportedPDFError("That file is empty.")
    except Exception:
        # Never leave a partial or oversized upload behind on a rejected request.
        delete_job_files(job_id)
        _refund(caller)
        raise

    job = Job(
        job_id=job_id,
        source_filename=file.filename,
        mode=mode,
        upload_path=str(upload_path),
        stage_detail="Queued",
    )
    store.save_job(job)
    # enqueue reports the job's queue position back onto the job, so a client
    # can tell "waiting behind other work" apart from "nothing is happening".
    await job_queue.enqueue(job_id)

    return ConversionCreatedResponse(id=job.job_id, status=job.stage)


@router.get("/{job_id}", response_model=ConversionSummaryResponse)
async def get_conversion(job_id: str) -> ConversionSummaryResponse:
    return ConversionSummaryResponse.from_job(_get_job_or_404(job_id))


@router.get("/{job_id}/progress", response_model=ConversionProgressResponse)
async def get_progress(job_id: str) -> ConversionProgressResponse:
    return ConversionProgressResponse.from_job(_get_job_or_404(job_id))


@router.get("/{job_id}/result", response_model=ConversionResultResponse)
async def get_result(job_id: str) -> ConversionResultResponse:
    job = _get_job_or_404(job_id)
    if job.stage != JobStage.COMPLETED:
        raise HTTPException(status_code=409, detail="This conversion isn't finished yet.")
    return ConversionResultResponse.from_job(job)


@router.get("/{job_id}/download")
async def download_epub(job_id: str) -> FileResponse:
    job = _get_job_or_404(job_id)
    if job.stage != JobStage.COMPLETED or not job.epub_path:
        raise HTTPException(status_code=409, detail="This conversion isn't finished yet.")
    return FileResponse(
        job.epub_path,
        media_type="application/epub+zip",
        filename=_safe_download_name(job.source_filename),
    )


@router.delete("/{job_id}", status_code=204, response_model=None)
async def delete_conversion(job_id: str) -> None:
    _get_job_or_404(job_id)
    delete_job_files(job_id)
    store.delete_job(job_id)


def _refund(caller: str) -> None:
    """A request rejected before any conversion work shouldn't consume quota."""
    if settings.rate_limit_enabled:
        _upload_limiter.release_one(caller)


def register_routes(app: FastAPI) -> None:
    app.include_router(router)
