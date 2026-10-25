"""Integration tests verifying Alembic migrations forward and backward against PostgreSQL."""

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from miconte.persistence.session import get_engine


def test_alembic_migrations_roundtrip_upgrade_downgrade() -> None:
    """Verify that migrations can upgrade to head, downgrade to base, and upgrade back to head."""
    alembic_cfg = Config("alembic.ini")
    engine = get_engine()

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
