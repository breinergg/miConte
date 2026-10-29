"""add_reporting_report_ingestions

Revision ID: c1a2b3d4e5f6
Revises: 465c43158ab0
Create Date: 2026-10-27 00:00:00.000000

Adds the reporting_report_ingestions table that persists the identity and metadata
of each YouTube Reporting API report file successfully ingested per channel.
This enables idempotent re-runs: already-processed report IDs are skipped, and
restatements (same period, newer create_time) are allowed to update metrics.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c1a2b3d4e5f6"
down_revision: str | Sequence[str] | None = "465c43158ab0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create reporting_report_ingestions table."""
    op.create_table(
        "reporting_report_ingestions",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("channel_id", sa.UUID(), nullable=False),
        sa.Column(
            "report_id",
            sa.String(length=256),
            nullable=False,
            comment="YouTube Reporting API report ID (globally unique per YouTube)",
        ),
        sa.Column(
            "job_id",
            sa.String(length=256),
            nullable=False,
            comment="YouTube Reporting API job ID that produced this report",
        ),
        sa.Column(
            "report_period_start",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="start_time from YouTube for this report's data window",
        ),
        sa.Column(
            "report_period_end",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="end_time from YouTube for this report's data window",
        ),
        sa.Column(
            "report_create_time",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="create_time from YouTube; used for restatement version comparison",
        ),
        sa.Column(
            "rows_ingested",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="Number of CSV rows committed to video_daily_reach metrics",
        ),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
            comment="Wall-clock timestamp when this ingestion record was written",
        ),
        sa.ForeignKeyConstraint(
            ["channel_id"],
            ["channels.id"],
            name=op.f("fk_reporting_report_ingestions_channel_id_channels"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reporting_report_ingestions")),
        sa.UniqueConstraint(
            "channel_id",
            "report_id",
            name="uq_reporting_ingestion_channel_report",
        ),
    )
    op.create_index(
        op.f("ix_reporting_report_ingestions_channel_id"),
        "reporting_report_ingestions",
        ["channel_id"],
        unique=False,
    )
    op.create_index(
        "ix_reporting_ingestion_channel_period",
        "reporting_report_ingestions",
        ["channel_id", "report_period_start", "report_period_end"],
        unique=False,
    )


def downgrade() -> None:
    """Drop reporting_report_ingestions table."""
    op.drop_index(
        "ix_reporting_ingestion_channel_period",
        table_name="reporting_report_ingestions",
    )
    op.drop_index(
        op.f("ix_reporting_report_ingestions_channel_id"),
        table_name="reporting_report_ingestions",
    )
    op.drop_table("reporting_report_ingestions")
