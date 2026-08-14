"""Regression tests for the job lifecycle.

A conversion must always reach a terminal state, and a job waiting behind other
work must say so rather than looking identical to a hang. Both of these were
real production failures observed on a physical device.
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import pytest

from app.core.config import settings
from app.jobs import store
from app.jobs.instance import _report_queue_position
from app.jobs.queue import RUNNING, InProcessJobQueue
from app.models.job import ConversionMode, Job, JobStage
from app.pipeline.validate import epubcheck_available
from tests.fixtures.corpus import build_turkish_novel


def _job(job_id: str, upload_path: Path | None = None) -> Job:
    job = Job(
        job_id=job_id,
        source_filename="book.pdf",
        mode=ConversionMode.MAXIMUM_ACCURACY,
        upload_path=str(upload_path) if upload_path else None,
        stage_detail="Queued",
    )
    store.save_job(job)
    return job


@pytest.fixture(autouse=True)
def _cleanup():
    created: list[str] = []
    yield created
    for job_id in created:
        store.delete_job(job_id)
        shutil.rmtree(settings.jobs_dir / job_id, ignore_errors=True)


# --- queue position visibility -------------------------------------------

async def test_a_queued_job_reports_how_many_conversions_are_ahead_of_it():
    """The physical-device symptom: two jobs saturated the worker pool and the
    third sat at UPLOADED with an empty detail, looking hung forever."""
    ids = [f"lifecycle-queue-{i}" for i in range(3)]
    for job_id in ids:
        _job(job_id)

    started = asyncio.Event()
    release = asyncio.Event()

    async def blocking_handler(job_id: str) -> None:
        started.set()
        await release.wait()

    queue = InProcessJobQueue(
        handler=blocking_handler, concurrency=1, position_observer=_report_queue_position
    )
    queue.start()
    try:
        for job_id in ids:
            await queue.enqueue(job_id)
        await asyncio.wait_for(started.wait(), timeout=5)
        await asyncio.sleep(0.1)

        waiting_details = [store.get_job(j).stage_detail for j in ids[1:]]
        assert all(d for d in waiting_details), "a waiting job must not have an empty detail"
        assert any("earlier" in d or "Next in queue" in d for d in waiting_details), waiting_details
    finally:
        release.set()
        await queue.stop()
        for job_id in ids:
            store.delete_job(job_id)


def test_position_observer_marks_a_started_job_and_leaves_running_jobs_alone():
    job_id = "lifecycle-position"
    _job(job_id)
    try:
        _report_queue_position(job_id, 2)
        assert "2 earlier" in store.get_job(job_id).stage_detail

        _report_queue_position(job_id, 0)
        assert store.get_job(job_id).stage_detail == "Next in queue"

        _report_queue_position(job_id, RUNNING)
        assert store.get_job(job_id).stage_detail == "Starting"

        # Once the pipeline owns the job, the queue must not overwrite its detail.
        job = store.get_job(job_id)
        job.stage = JobStage.EXTRACTING
        job.stage_detail = "Extracting text and images"
        store.save_job(job)
        _report_queue_position(job_id, 3)
        assert store.get_job(job_id).stage_detail == "Extracting text and images"
    finally:
        store.delete_job(job_id)


# --- terminal states ------------------------------------------------------

async def test_queue_drains_every_job_to_a_terminal_state(tmp_path: Path, _cleanup):
    """UPLOADED -> ... -> COMPLETED for each job, including ones that queued."""
    if not epubcheck_available():
        pytest.skip("epubcheck is not installed")

    pdf = build_turkish_novel(tmp_path / "novel.pdf")
    ids = [f"lifecycle-drain-{i}" for i in range(3)]
    _cleanup.extend(ids)
    for job_id in ids:
        _job(job_id, pdf)

    from app.pipeline.orchestrator import run_pipeline

    queue = InProcessJobQueue(
        handler=run_pipeline, concurrency=1, position_observer=_report_queue_position
    )
    queue.start()
    try:
        for job_id in ids:
            await queue.enqueue(job_id)

        async def all_terminal() -> bool:
            return all(
                (store.get_job(j) or Job(job_id=j, source_filename="", mode=ConversionMode.FAST)).stage
                in (JobStage.COMPLETED, JobStage.FAILED)
                for j in ids
            )

        deadline = asyncio.get_running_loop().time() + 180
        while asyncio.get_running_loop().time() < deadline:
            if await all_terminal():
                break
            await asyncio.sleep(0.5)

        for job_id in ids:
            job = store.get_job(job_id)
            assert job is not None
            assert job.stage == JobStage.COMPLETED, f"{job_id}: {job.stage} {job.error_code}"
    finally:
        await queue.stop()


async def test_a_failing_job_reaches_FAILED_and_never_sticks_at_UPLOADED(tmp_path: Path, _cleanup):
    """A pipeline error must surface as FAILED with a message, not leave the
    client polling an UPLOADED job indefinitely."""
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"%PDF-1.4\nnot actually a pdf")

    job_id = "lifecycle-fail"
    _cleanup.append(job_id)
    _job(job_id, broken)

    from app.pipeline.orchestrator import run_pipeline

    queue = InProcessJobQueue(handler=run_pipeline, concurrency=1)
    queue.start()
    try:
        await queue.enqueue(job_id)
        deadline = asyncio.get_running_loop().time() + 60
        while asyncio.get_running_loop().time() < deadline:
            job = store.get_job(job_id)
            if job and job.stage in (JobStage.COMPLETED, JobStage.FAILED):
                break
            await asyncio.sleep(0.25)

        job = store.get_job(job_id)
        assert job is not None
        assert job.stage == JobStage.FAILED
        assert job.error_code
        assert job.error_message
    finally:
        await queue.stop()


async def test_worker_survives_a_handler_that_raises_and_keeps_draining(_cleanup):
    """One exploding job must not take the worker pool down with it, which would
    strand every later job at UPLOADED."""
    processed: list[str] = []

    async def handler(job_id: str) -> None:
        processed.append(job_id)
        if job_id.endswith("boom"):
            raise RuntimeError("simulated pipeline crash")

    queue = InProcessJobQueue(handler=handler, concurrency=1)
    queue.start()
    try:
        await queue.enqueue("lifecycle-boom")
        await queue.enqueue("lifecycle-after")
        deadline = asyncio.get_running_loop().time() + 10
        while asyncio.get_running_loop().time() < deadline and "lifecycle-after" not in processed:
            await asyncio.sleep(0.05)
        assert "lifecycle-after" in processed, "worker died after an exception"
    finally:
        await queue.stop()
