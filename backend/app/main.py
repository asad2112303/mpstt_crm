"""MPSTT CRM API application factory."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import dispose_engine, get_session_factory
from app.core.envelope import ok
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.debug)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        await dispose_engine()

    app = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.env != "production" else None,
        openapi_url="/openapi.json" if settings.env != "production" else None,
    )

    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        # Optional pattern for ephemeral deploy previews (e.g. Vercel branch URLs),
        # which get a new hostname per build and cannot be listed individually.
        allow_origin_regex=settings.cors_origin_regex or None,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "ETag"],
    )
    register_error_handlers(app)

    @app.get("/health", tags=["ops"])
    async def health() -> dict:
        """Liveness: the process is up."""
        return ok({"status": "ok", "env": settings.env})

    @app.get("/ready", tags=["ops"])
    async def ready() -> dict:
        """Readiness: the database answers."""
        async with get_session_factory()() as session:
            await session.execute(text("SELECT 1"))
        return ok({"status": "ready"})

    from app.api.v1.router import api_router

    app.include_router(api_router, prefix="/api/v1")
    return app


app = create_app()
