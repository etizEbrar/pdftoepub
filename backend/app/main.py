from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.routes import register_routes
from app.core.config import settings
from app.core.errors import ConversionError
from app.core.logging import configure_logging, get_logger
from app.jobs.instance import job_queue
from app.storage.temp_storage import sweep_expired_jobs

configure_logging()
logger = get_logger(__name__)

_CLEANUP_INTERVAL_SECONDS = 3600


async def _cleanup_loop() -> None:
    while True:
        await asyncio.sleep(_CLEANUP_INTERVAL_SECONDS)
        try:
            sweep_expired_jobs()
        except Exception:
            logger.exception("temp file cleanup sweep failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    job_queue.start()
    cleanup_task = asyncio.create_task(_cleanup_loop())
    logger.info("backend started (ai_provider=%s)", settings.ai_provider)
    yield
    cleanup_task.cancel()
    await job_queue.stop()


app = FastAPI(title="PDF to EPUB", version="0.1.0", lifespan=lifespan)
register_routes(app)


@app.exception_handler(ConversionError)
async def conversion_error_handler(request: Request, exc: ConversionError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"code": exc.code, "message": exc.user_message})


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "ai_provider": settings.ai_provider}
