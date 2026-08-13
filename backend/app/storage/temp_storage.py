from __future__ import annotations

import shutil
import time
from pathlib import Path

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def job_dir(job_id: str) -> Path:
    d = settings.jobs_dir / job_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def upload_path_for(job_id: str, filename: str) -> Path:
    safe_name = Path(filename).name or "upload.pdf"
    return job_dir(job_id) / "source" / safe_name


def images_dir_for(job_id: str) -> Path:
    d = job_dir(job_id) / "images"
    d.mkdir(parents=True, exist_ok=True)
    return d


def epub_path_for(job_id: str, title_slug: str = "book") -> Path:
    return job_dir(job_id) / "output" / f"{title_slug}.epub"


def delete_job_files(job_id: str) -> None:
    d = settings.jobs_dir / job_id
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
    logger.info("deleted temp files for job %s", job_id)


def sweep_expired_jobs(ttl_hours: int | None = None) -> list[str]:
    """Delete job directories older than the TTL. Returns deleted job ids."""
    ttl_seconds = (ttl_hours if ttl_hours is not None else settings.job_ttl_hours) * 3600
    now = time.time()
    deleted: list[str] = []
    if not settings.jobs_dir.exists():
        return deleted
    for entry in settings.jobs_dir.iterdir():
        if not entry.is_dir():
            continue
        age = now - entry.stat().st_mtime
        if age > ttl_seconds:
            shutil.rmtree(entry, ignore_errors=True)
            deleted.append(entry.name)
    if deleted:
        logger.info("swept %d expired job(s)", len(deleted))
    return deleted
