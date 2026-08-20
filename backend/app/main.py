from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.ratelimit import SlidingWindowLimiter, client_key
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


app = FastAPI(
    title="PDF to EPUB",
    version="0.1.0",
    lifespan=lifespan,
    # The interactive docs enumerate every endpoint and schema. They are a
    # development convenience, not something to publish.
    docs_url="/docs" if settings.expose_api_docs else None,
    redoc_url="/redoc" if settings.expose_api_docs else None,
    openapi_url="/openapi.json" if settings.expose_api_docs else None,
)

# The iOS client is not a browser and is unaffected by CORS. Origins stay empty
# unless someone deliberately configures a web client, so a hostile page cannot
# drive this API with a visitor's credentials.
if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type"],
    )

register_routes(app)

_request_limiter = SlidingWindowLimiter(settings.rate_limit_requests_per_minute, 60.0)


@app.middleware("http")
async def guard_and_harden(request: Request, call_next):
    """Throttle by client and set the response headers a public API should send."""
    if settings.rate_limit_enabled and request.url.path != "/health":
        allowed, retry_after = _request_limiter.check(client_key(request))
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={
                    "code": "rate_limited",
                    "message": "Too many requests. Please slow down and try again.",
                },
                headers={"Retry-After": str(retry_after)},
            )

    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    # This API returns JSON and EPUB files, never HTML meant to be rendered.
    response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    if settings.is_production:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


@app.exception_handler(ConversionError)
async def conversion_error_handler(request: Request, exc: ConversionError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"code": exc.code, "message": exc.user_message})


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Log the detail, tell the client nothing.

    Without this an unexpected failure returns Starlette's bare 500. The trace
    is what we need in the logs and precisely what must not cross the wire: it
    names server paths, package versions and internal structure. The request
    path is safe to log; the uploaded document never is.
    """
    logger.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "code": "internal_error",
            "message": "Something went wrong on our side. Your document was not modified.",
        },
    )


@app.get("/health")
async def health() -> dict:
    """Liveness for the platform's health check.

    Deliberately minimal: no paths, no versions, no configuration, nothing that
    describes the host. `ai_provider` is included because the iOS app shows it
    to prove no cloud AI is in use, and it is a fixed word, not a secret.
    """
    return {"status": "ok", "ai_provider": settings.ai_provider}
