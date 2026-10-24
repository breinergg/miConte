"""Main FastAPI application entrypoint for miConte."""

from fastapi import FastAPI

from miconte import __version__
from miconte.api.health import router as health_router
from miconte.core.config import get_settings


def create_app() -> FastAPI:
    """Create and configure the FastAPI application instance."""
    settings = get_settings()
    application = FastAPI(
        title=settings.app_name,
        version=__version__,
        description="Plataforma de inteligencia de contenido — Backend determinista.",
    )
    application.include_router(health_router)
    return application


app = create_app()
