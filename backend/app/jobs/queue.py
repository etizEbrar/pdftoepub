from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from app.core.logging import get_logger

logger = get_logger(__name__)

JobHandler = Callable[[str], Awaitable[None]]


class InProcessJobQueue:
    """Minimal async job queue: a fixed pool of worker loops pull job ids off an
    asyncio.Queue and run the handler (which itself off-loads the CPU-bound
    pipeline to a thread — see orchestrator.run_pipeline).

    This runs with zero extra infrastructure, which is what makes "local dev
    only for now" possible without Docker/Redis. It sits behind exactly the
    interface a Redis/RQ or Celery-backed queue would need to replace it with,
    for horizontal scaling later, without touching any pipeline code.
    """

    def __init__(self, handler: JobHandler, concurrency: int = 2):
        self._handler = handler
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._workers: list[asyncio.Task] = []
        self._concurrency = concurrency

    def start(self) -> None:
        if self._workers:
            return
        self._workers = [asyncio.create_task(self._worker_loop(i)) for i in range(self._concurrency)]

    async def stop(self) -> None:
        for w in self._workers:
            w.cancel()
        for w in self._workers:
            try:
                await w
            except asyncio.CancelledError:
                pass
        self._workers = []

    async def enqueue(self, job_id: str) -> None:
        await self._queue.put(job_id)

    async def _worker_loop(self, worker_index: int) -> None:
        while True:
            job_id = await self._queue.get()
            try:
                await self._handler(job_id)
            except Exception:
                logger.exception("unhandled error processing job %s", job_id)
            finally:
                self._queue.task_done()
