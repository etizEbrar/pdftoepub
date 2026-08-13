from __future__ import annotations

from pydantic import BaseModel

from app.models.job import ConversionMode, Job, JobStage


class ConversionCreatedResponse(BaseModel):
    id: str
    status: JobStage


class ConversionSummaryResponse(BaseModel):
    id: str
    status: JobStage
    mode: ConversionMode
    source_filename: str
    error_code: str | None = None
    error_message: str | None = None

    @classmethod
    def from_job(cls, job: Job) -> "ConversionSummaryResponse":
        return cls(
            id=job.job_id,
            status=job.stage,
            mode=job.mode,
            source_filename=job.source_filename,
            error_code=job.error_code,
            error_message=job.error_message,
        )


class ConversionProgressResponse(BaseModel):
    id: str
    status: JobStage
    stage_detail: str
    page: int
    total_pages: int
    percent: int

    @classmethod
    def from_job(cls, job: Job) -> "ConversionProgressResponse":
        return cls(
            id=job.job_id,
            status=job.stage,
            stage_detail=job.stage_detail,
            page=job.current_page,
            total_pages=job.total_pages,
            percent=job.percent(),
        )


class ConversionResultResponse(BaseModel):
    id: str
    status: JobStage
    quality_report: dict | None = None
    download_url: str | None = None

    @classmethod
    def from_job(cls, job: Job) -> "ConversionResultResponse":
        return cls(
            id=job.job_id,
            status=job.stage,
            quality_report=job.quality_report.to_dict() if job.quality_report else None,
            download_url=f"/v1/conversions/{job.job_id}/download" if job.epub_path else None,
        )
