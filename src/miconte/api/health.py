"""Health and database readiness endpoints for miConte."""

from typing import Literal

from fastapi import APIRouter, Response, status
from pydantic import BaseModel, Field

from miconte import __version__
from miconte.api.deps import DbSessionDep, SettingsDep
from miconte.persistence.session import check_database_connection

router = APIRouter(prefix="/api/v1/health", tags=["health"])


class ApplicationHealthResponse(BaseModel):
    """Public schema for application liveness check."""

    application: str = Field(description="Visible application name")
    status: Literal["available"] = Field(description="Application availability status")
    version: str = Field(description="Application package version")


class DatabaseHealthResponse(BaseModel):
    """Public schema for database readiness check without sensitive details."""

    application: str = Field(description="Visible application name")
    status: Literal["available", "degraded"] = Field(
        description="Overall service status given dependency state"
    )
    database: Literal["available", "unavailable"] = Field(
        description="PostgreSQL dependency status"
    )


@router.get("", status_code=status.HTTP_200_OK)
def get_application_health(settings: SettingsDep) -> ApplicationHealthResponse:
    """Verify that the miConte API process is running and responsive."""
    return ApplicationHealthResponse(
        application=settings.app_name,
        status="available",
        version=__version__,
    )


@router.get(
    "/db",
    responses={
        status.HTTP_200_OK: {"model": DatabaseHealthResponse},
        status.HTTP_503_SERVICE_UNAVAILABLE: {"model": DatabaseHealthResponse},
    },
)
def get_database_health(
    response: Response,
    settings: SettingsDep,
    session: DbSessionDep,
) -> DatabaseHealthResponse:
    """Verify real connectivity to PostgreSQL via a simple SELECT 1 query.

    Distinguishes between:
    - Application available + Database available (HTTP 200)
    - Application available + Dependency unavailable (HTTP 503)
    Never exposes connection URLs, credentials, or internal driver exceptions.
    """
    is_db_healthy = check_database_connection(session)
    if not is_db_healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return DatabaseHealthResponse(
            application=settings.app_name,
            status="degraded",
            database="unavailable",
        )

    response.status_code = status.HTTP_200_OK
    return DatabaseHealthResponse(
        application=settings.app_name,
        status="available",
        database="available",
    )
