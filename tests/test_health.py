"""Tests for health and database readiness endpoints."""

from collections.abc import Generator

from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from miconte.api.deps import get_db_session
from miconte.main import app


def test_liveness_health_endpoint_returns_available() -> None:
    """Verify /api/v1/health reports application available without exposing internals."""
    client = TestClient(app)
    response = client.get("/api/v1/health")

    assert response.status_code == status.HTTP_200_OK
    payload = response.json()
    assert payload["application"] == "miConte"
    assert payload["status"] == "available"
    assert "database_url" not in str(payload)
    assert "password" not in str(payload)


def test_database_health_endpoint_when_db_available() -> None:
    """Verify /api/v1/health/db returns 200 and available status when SELECT 1 succeeds."""

    class DummyResult:
        def scalar_one(self) -> int:
            return 1

    class FakeHealthySession:
        def execute(self, statement: object) -> DummyResult:
            return DummyResult()

    def override_healthy_db() -> Generator[Session]:
        yield FakeHealthySession()  # type: ignore[misc]

    app.dependency_overrides[get_db_session] = override_healthy_db
    try:
        client = TestClient(app)
        response = client.get("/api/v1/health/db")

        assert response.status_code == status.HTTP_200_OK
        payload = response.json()
        assert payload["application"] == "miConte"
        assert payload["status"] == "available"
        assert payload["database"] == "available"
    finally:
        app.dependency_overrides.clear()


def test_database_health_endpoint_when_dependency_unavailable() -> None:
    """Verify /api/v1/health/db returns 503 and sanitizes connection errors."""

    class FakeUnhealthySession:
        def execute(self, statement: object) -> object:
            raise OperationalError(
                "SELECT 1",
                {},
                Exception(
                    "connection to server at '127.0.0.1', port 5432 failed: "
                    "password authentication failed for user 'secret_admin_user'"
                ),
            )

    def override_unhealthy_db() -> Generator[Session]:
        yield FakeUnhealthySession()  # type: ignore[misc]

    app.dependency_overrides[get_db_session] = override_unhealthy_db
    try:
        client = TestClient(app)
        response = client.get("/api/v1/health/db")

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        payload = response.json()
        assert payload["application"] == "miConte"
        assert payload["status"] == "degraded"
        assert payload["database"] == "unavailable"
        # Ensure sensitive internal details are never leaked
        raw_text = response.text.lower()
        assert "secret_admin_user" not in raw_text
        assert "password" not in raw_text
        assert "postgresql" not in raw_text
    finally:
        app.dependency_overrides.clear()
