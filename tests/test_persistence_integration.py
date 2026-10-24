"""Integration tests for real PostgreSQL persistence and database health check.

Uses an isolated, temporary/test-only SQLAlchemy table created and dropped
in a controlled manner without introducing domain tables prematurely.
"""

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import Column, Integer, MetaData, String, Table, insert, select
from sqlalchemy.orm import Session

from miconte.main import app
from miconte.persistence.session import get_engine


@pytest.mark.integration
def test_real_postgresql_write_and_read_roundtrip() -> None:
    """Perform a real write and read against PostgreSQL using a test-only table."""
    engine = get_engine()
    test_metadata = MetaData()

    probe_table = Table(
        "_miconte_phase1_persistence_probe",
        test_metadata,
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("probe_key", String(64), nullable=False, unique=True),
        Column("probe_value", String(128), nullable=False),
    )

    test_metadata.create_all(bind=engine, tables=[probe_table])
    try:
        with Session(engine) as session:
            session.execute(
                insert(probe_table).values(
                    probe_key="phase1_storage_check",
                    probe_value="deterministic_persistence_verified",
                )
            )
            session.commit()

        with Session(engine) as session:
            row = session.execute(
                select(probe_table.c.probe_key, probe_table.c.probe_value).where(
                    probe_table.c.probe_key == "phase1_storage_check"
                )
            ).one()

            assert row.probe_key == "phase1_storage_check"
            assert row.probe_value == "deterministic_persistence_verified"
    finally:
        test_metadata.drop_all(bind=engine, tables=[probe_table])


@pytest.mark.integration
def test_real_database_health_endpoint_against_postgres() -> None:
    """Verify /api/v1/health/db against the live PostgreSQL container."""
    client = TestClient(app)
    response = client.get("/api/v1/health/db")

    assert response.status_code == status.HTTP_200_OK
    payload = response.json()
    assert payload["application"] == "miConte"
    assert payload["status"] == "available"
    assert payload["database"] == "available"
