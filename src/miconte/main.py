"""Main FastAPI application entrypoint for miConte."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from miconte import __version__
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
    application.include_router(health_router)
    application.include_router(oauth_router)
    application.include_router(sync_router)
    return application


app = create_app()
