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
    """Delete expired job directories *and* their database rows.

    Both halves matter. The directory holds the user's PDF and the EPUB built
    from it; the row holds the source filename, the detected book title and the
    on-disk paths. Removing only the files would leave a permanent record of
    every book anyone ever converted, which is exactly the kind of retention
    this service promises not to have.
    """
    # Imported here rather than at module scope: the store imports settings, and
    # keeping this local avoids coupling storage to the job store's import order.
    from app.jobs import store

    ttl = ttl_hours if ttl_hours is not None else settings.job_ttl_hours
    ttl_seconds = ttl * 3600
    now = time.time()
    deleted: list[str] = []

    if settings.jobs_dir.exists():
        for entry in settings.jobs_dir.iterdir():
            if not entry.is_dir():
                continue
            if now - entry.stat().st_mtime > ttl_seconds:
                shutil.rmtree(entry, ignore_errors=True)
                deleted.append(entry.name)

    rows_removed = 0
    for job_id in store.list_expired_job_ids(ttl):
        store.delete_job(job_id)
        rows_removed += 1
        # A row can outlive its directory (or vice versa); report the union.
        if job_id not in deleted:
            deleted.append(job_id)

    if deleted:
        logger.info(
            "swept %d expired job(s) (%d database row(s))", len(deleted), rows_removed
        )
    return deleted
