from __future__ import annotations

from datetime import datetime

from app.core.config import settings
from app.core.logging import get_logger
from app.jobs import store
from app.jobs.queue import RUNNING, InProcessJobQueue
from app.models.job import JobStage
from app.pipeline.orchestrator import run_pipeline

logger = get_logger(__name__)


def _report_queue_position(job_id: str, jobs_ahead: int) -> None:
    """Record a waiting job's place in the queue on the job itself.

    A job sitting behind a long conversion would otherwise report UPLOADED with
    no detail — indistinguishable from a hang — for as long as the queue is
    busy. Clients render `stage_detail`, so this makes the wait visible.
    """
    job = store.get_job(job_id)
    if job is None or job.stage != JobStage.UPLOADED:
        return

    if jobs_ahead == RUNNING:
        job.stage_detail = "Starting"
    elif jobs_ahead == 0:
        job.stage_detail = "Next in queue"
    else:
        plural = "conversion" if jobs_ahead == 1 else "conversions"
        job.stage_detail = f"Waiting for {jobs_ahead} earlier {plural} to finish"

    job.updated_at = datetime.now()
    store.save_job(job)


job_queue = InProcessJobQueue(
    handler=run_pipeline,
    concurrency=settings.job_concurrency,
    position_observer=_report_queue_position,
)
