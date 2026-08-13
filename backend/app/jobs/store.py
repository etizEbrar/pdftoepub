from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime

from app.core.config import settings
from app.models.job import ConversionMode, Job, JobStage, QualityReport

_lock = threading.Lock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    stage TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    payload TEXT NOT NULL
);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.db_path, check_same_thread=False)
    conn.execute(_SCHEMA)
    return conn


def _to_row(job: Job) -> dict:
    return {
        "job_id": job.job_id,
        "source_filename": job.source_filename,
        "mode": job.mode.value,
        "stage": job.stage.value,
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
        "current_page": job.current_page,
        "total_pages": job.total_pages,
        "stage_detail": job.stage_detail,
        "error_code": job.error_code,
        "error_message": job.error_message,
        "upload_path": job.upload_path,
        "epub_path": job.epub_path,
        "quality_report": job.quality_report.to_dict() if job.quality_report else None,
    }


def _from_row(payload: dict) -> Job:
    qr = None
    if payload.get("quality_report"):
        qr = QualityReport(**payload["quality_report"])
    return Job(
        job_id=payload["job_id"],
        source_filename=payload["source_filename"],
        mode=ConversionMode(payload["mode"]),
        stage=JobStage(payload["stage"]),
        created_at=datetime.fromisoformat(payload["created_at"]),
        updated_at=datetime.fromisoformat(payload["updated_at"]),
        current_page=payload["current_page"],
        total_pages=payload["total_pages"],
        stage_detail=payload["stage_detail"],
        error_code=payload.get("error_code"),
        error_message=payload.get("error_message"),
        upload_path=payload.get("upload_path"),
        epub_path=payload.get("epub_path"),
        quality_report=qr,
    )


def save_job(job: Job) -> None:
    row = _to_row(job)
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT INTO jobs (job_id, stage, updated_at, payload) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(job_id) DO UPDATE SET stage=excluded.stage, "
            "updated_at=excluded.updated_at, payload=excluded.payload",
            (job.job_id, job.stage.value, job.updated_at.isoformat(), json.dumps(row)),
        )


def get_job(job_id: str) -> Job | None:
    with _lock, _connect() as conn:
        cur = conn.execute("SELECT payload FROM jobs WHERE job_id = ?", (job_id,))
        row = cur.fetchone()
    if row is None:
        return None
    return _from_row(json.loads(row[0]))


def delete_job(job_id: str) -> None:
    with _lock, _connect() as conn:
        conn.execute("DELETE FROM jobs WHERE job_id = ?", (job_id,))


def list_expired_job_ids(ttl_hours: int) -> list[str]:
    with _lock, _connect() as conn:
        cur = conn.execute("SELECT job_id, updated_at FROM jobs")
        rows = cur.fetchall()
    expired = []
    now = datetime.now()
    for job_id, updated_at in rows:
        try:
            ts = datetime.fromisoformat(updated_at)
        except ValueError:
            continue
        if (now - ts).total_seconds() > ttl_hours * 3600:
            expired.append(job_id)
    return expired
