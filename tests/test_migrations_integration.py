"""Integration tests verifying Alembic migrations forward and backward against PostgreSQL."""

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from miconte.persistence.session import get_engine

pytestmark = pytest.mark.integration

_REQUIRED_TEST_DB = "miconte_test_db"


def _assert_connected_to_test_db(engine: object) -> None:
    """Abort immediately if the engine is NOT connected to the dedicated test database.

    This guard prevents ``downgrade base`` (which drops all tables and data) from
    running against the development database (``miconte_db``) or any other database
    that is not explicitly reserved for testing.

    The check queries PostgreSQL directly for the *actual* database name — it does not
    rely on environment variables or connection-string parsing, which can be spoofed or
    misconfigured.  A failed assertion raises ``AssertionError`` before any migration
    command executes.
    """
    from sqlalchemy import Engine  # noqa: PLC0415

    assert isinstance(engine, Engine)
    with engine.connect() as conn:
        actual_db: str = conn.execute(text("SELECT current_database()")).scalar_one()

    assert actual_db == _REQUIRED_TEST_DB, (
        f"SAFETY ABORT: destructive migration tests must run against "
        f"'{_REQUIRED_TEST_DB}', but the engine is connected to '{actual_db}'. "
        f"Set MICONTE_TEST_DATABASE_URL to point to "
        f"'{_REQUIRED_TEST_DB}' before running this test."
    )


def test_alembic_migrations_roundtrip_upgrade_downgrade() -> None:
    """Verify that migrations can upgrade to head, downgrade to base, and upgrade back to head."""
    alembic_cfg = Config("alembic.ini")
    engine = get_engine()

    # Safety: abort if we are not on the dedicated test database
    _assert_connected_to_test_db(engine)

    # 1. Downgrade to base (empty database state)
    command.downgrade(alembic_cfg, "base")
    tables_after_downgrade = set(inspect(engine).get_table_names())
    # Only alembic_version (or nothing) should remain
    assert tables_after_downgrade.issubset({"alembic_version"})

    # 2. Upgrade to head
    command.upgrade(alembic_cfg, "head")
    tables_after_upgrade = set(inspect(engine).get_table_names())

    expected_domain_tables = {
        "users",
        "oauth_connections",
        "channels",
        "channel_public_snapshots",
        "videos",
        "video_public_snapshots",
        "channel_daily_metrics",
        "video_daily_metrics",
        "video_period_metrics",
        "sync_runs",
        "analysis_runs",
        "recommendations",
    }
    assert expected_domain_tables.issubset(tables_after_upgrade)
