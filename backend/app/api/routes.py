from __future__ import annotations

import uuid

from fastapi import APIRouter, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

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


def _get_job_or_404(job_id: str) -> Job:
    job = store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="This conversion job no longer exists.")
    return job


@router.post("", response_model=ConversionCreatedResponse, status_code=201)
async def create_conversion(
    file: UploadFile = File(...),
    mode: ConversionMode = Form(default=ConversionMode.MAXIMUM_ACCURACY),
) -> ConversionCreatedResponse:
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise UnsupportedPDFError("Please choose a PDF file.")

    contents = await file.read()
    max_bytes = settings.max_upload_mb * 1024 * 1024
    if len(contents) > max_bytes:
        raise FileTooLargeError(f"This PDF is larger than the {settings.max_upload_mb}MB limit.")
    if not contents.startswith(_PDF_MAGIC):
        raise UnsupportedPDFError()

    job_id = uuid.uuid4().hex
    upload_path = upload_path_for(job_id, file.filename)
    upload_path.parent.mkdir(parents=True, exist_ok=True)
    upload_path.write_bytes(contents)

    job = Job(job_id=job_id, source_filename=file.filename, mode=mode, upload_path=str(upload_path))
    store.save_job(job)
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
        filename=f"{job.source_filename.rsplit('.', 1)[0]}.epub",
    )


@router.delete("/{job_id}", status_code=204, response_model=None)
async def delete_conversion(job_id: str) -> None:
    _get_job_or_404(job_id)
    delete_job_files(job_id)
    store.delete_job(job_id)


def register_routes(app: FastAPI) -> None:
    app.include_router(router)
