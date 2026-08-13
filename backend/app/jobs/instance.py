from __future__ import annotations

from app.jobs.queue import InProcessJobQueue
from app.pipeline.orchestrator import run_pipeline

job_queue = InProcessJobQueue(handler=run_pipeline, concurrency=2)
