"""CheckR FastAPI application."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.ai.factory import shutdown_provider
from app.api import rate_limit
from app.api.rate_limit import RateLimiter
from app.api.router import api_router
from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.db.session import dispose_engine

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    logger.info(
        "Starting %s v%s (env=%s, ai=%s, storage=%s)",
        settings.app_name,
        __version__,
        settings.environment,
        settings.ai_provider,
        settings.storage_provider,
    )
    for warning in settings.warnings():
        logger.warning("Configuration: %s", warning)

    if settings.seed_on_startup and not settings.is_production:
        try:
            from app.db.seed import ensure_demo_data

            created = await ensure_demo_data()
            if created:
                logger.info("Seeded demo data (%s).", created)
        except Exception as exc:  # seeding must never block startup
            logger.warning("Seed skipped: %s", exc)

    yield

    await shutdown_provider()
    await dispose_engine()
    logger.info("Shutdown complete.")


app = FastAPI(
    title="CheckR API",
    version=__version__,
    description=(
        "AI-assisted evaluation of handwritten examination answer sheets. "
        "Human-in-the-loop: the AI proposes, the teacher decides."
    ),
    lifespan=lifespan,
    docs_url="/docs" if not settings.is_production else None,
    redoc_url=None,
    debug=settings.debug,
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Ensure unhandled errors produce a visible traceback in development logs."""
    logger.exception("Unhandled error processing %s %s: %s", request.method, request.url.path, exc)
    if settings.debug:
        import traceback

        return JSONResponse(
            status_code=500,
            content={
                "detail": f"Internal Server Error: {exc}",
                "traceback": traceback.format_exc(),
            },
        )
    return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

#: Cheap global guard against runaway request loops.
_global_limiter = rate_limit.register(RateLimiter(limit=600, window_seconds=60))


@app.middleware("http")
async def security_and_limits(request: Request, call_next):
    client = request.client.host if request.client else "unknown"
    try:
        _global_limiter.check(f"global:{client}")
    except Exception as exc:
        from fastapi import HTTPException

        if isinstance(exc, HTTPException):
            return JSONResponse(
                status_code=exc.status_code, content={"detail": exc.detail}
            )
        raise

    response = await call_next(request)

    # Hardening headers for every response.
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault(
        "Permissions-Policy", "geolocation=(), microphone=(), camera=()"
    )
    return response


app.include_router(api_router, prefix=settings.api_prefix)


@app.get("/", include_in_schema=False)
async def root() -> dict:
    return {
        "name": settings.app_name,
        "version": __version__,
        "docs": "/docs" if not settings.is_production else None,
        "api": settings.api_prefix,
    }
