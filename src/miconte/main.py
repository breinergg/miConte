"""Main FastAPI application entrypoint for miConte."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from miconte import __version__
from miconte.api.ai import router as ai_router
from miconte.api.analytics import router as analytics_router
from miconte.api.auth import router as auth_router
from miconte.api.health import router as health_router
from miconte.api.oauth import router as oauth_router
from miconte.api.sync import router as sync_router
from miconte.core.config import get_settings
from miconte.services.scheduler import default_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Manage application background lifecycles."""
    settings = get_settings()
    # In testing, scheduler is triggered explicitly rather than auto-looping
    if settings.sync_enabled and settings.environment != "testing":
        await default_scheduler.start()
    yield
    await default_scheduler.stop()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application instance."""
    settings = get_settings()
    application = FastAPI(
        title=settings.app_name,
        version=__version__,
        description="Plataforma de inteligencia de contenido — Backend determinista.",
        lifespan=lifespan,
    )

    # CORS: only enabled when MICONTE_CORS_ALLOW_ORIGINS is explicitly set.
    # Same-origin deployments (frontend served by FastAPI's StaticFiles or a
    # reverse proxy on the same host) do not need CORS and leave this empty.
    # Never set to "*" in production.
    raw_origins = settings.cors_allow_origins.strip()
    if raw_origins:
        allowed_origins = [o.strip() for o in raw_origins.split(",") if o.strip()]
        application.add_middleware(
            CORSMiddleware,
            allow_origins=allowed_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["Content-Type", "Authorization", "X-User-Id"],
        )

    application.include_router(health_router)
    application.include_router(auth_router)
    application.include_router(oauth_router)
    application.include_router(sync_router)
    application.include_router(analytics_router)
    application.include_router(ai_router)
    return application


app = create_app()
