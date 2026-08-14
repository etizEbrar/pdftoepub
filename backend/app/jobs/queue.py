from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from app.core.logging import get_logger

logger = get_logger(__name__)

JobHandler = Callable[[str], Awaitable[None]]
# Called with (job_id, jobs_ahead) whenever a job's place in the queue changes,
# and with jobs_ahead = -1 once it starts running.
PositionObserver = Callable[[str, int], None]

RUNNING = -1


class InProcessJobQueue:
    """Minimal async job queue: a fixed pool of worker loops pull job ids off an
    asyncio.Queue and run the handler (which itself off-loads the CPU-bound
    pipeline to a thread — see orchestrator.run_pipeline).

    This runs with zero extra infrastructure, which is what makes "local dev
    only for now" possible without Docker/Redis. It sits behind exactly the
    interface a Redis/RQ or Celery-backed queue would need to replace it with,
    for horizontal scaling later, without touching any pipeline code.

    Waiting jobs report their queue position through `position_observer`. Without
    that, a job queued behind a long conversion looks identical to a hung one:
    the client sees UPLOADED forever with no indication anything is coming.
    """

    def __init__(
        self,
        handler: JobHandler,
        concurrency: int = 2,
        position_observer: PositionObserver | None = None,
    ):
        self._handler = handler
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._workers: list[asyncio.Task] = []
        self._concurrency = concurrency
        self._position_observer = position_observer
        self._waiting: list[str] = []

    def start(self) -> None:
        if self._workers:
            return
        self._workers = [asyncio.create_task(self._worker_loop(i)) for i in range(self._concurrency)]
        logger.info("job queue started with %d worker(s)", self._concurrency)

    async def stop(self) -> None:
        for w in self._workers:
            w.cancel()
        for w in self._workers:
            try:
                await w
            except asyncio.CancelledError:
                pass
        self._workers = []

    @property
    def pending_count(self) -> int:
        return len(self._waiting)

    async def enqueue(self, job_id: str) -> int:
        """Add a job and return how many jobs are ahead of it."""
        position = len(self._waiting)
        self._waiting.append(job_id)
        await self._queue.put(job_id)
        self._notify_positions()
        return position

    def _notify_positions(self) -> None:
        if self._position_observer is None:
            return
        for index, job_id in enumerate(self._waiting):
            try:
                self._position_observer(job_id, index)
            except Exception:
                logger.exception("queue position observer failed for %s", job_id)

    async def _worker_loop(self, worker_index: int) -> None:
        while True:
            job_id = await self._queue.get()
            if job_id in self._waiting:
                self._waiting.remove(job_id)
            if self._position_observer is not None:
                try:
                    self._position_observer(job_id, RUNNING)
                except Exception:
                    logger.exception("queue position observer failed for %s", job_id)
            self._notify_positions()

            logger.info("worker %d starting job %s", worker_index, job_id)
            try:
                await self._handler(job_id)
            except Exception:
                logger.exception("unhandled error processing job %s", job_id)
            finally:
                logger.info("worker %d finished job %s", worker_index, job_id)
                self._queue.task_done()
