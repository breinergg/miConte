"""add_anomaly_fields_to_video_public_snapshots

Revision ID: d5e6f7a8b9c0
Revises: c1a2b3d4e5f6
Create Date: 2026-10-27 00:00:00.000000

Adds is_anomalous and anomaly_notes to video_public_snapshots so that public
snapshots which contain values that violate the expected contract (e.g. a negative
like_count returned by YouTube) can be recorded with NULL for the offending column
while preserving the original value and diagnosis in anomaly_notes.

This mirrors the existing anomaly-isolation pattern used by channel_daily_metrics,
video_daily_metrics, and video_period_metrics.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d5e6f7a8b9c0"
down_revision: str | Sequence[str] | None = "c1a2b3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add is_anomalous and anomaly_notes columns to video_public_snapshots."""
    op.add_column(
        "video_public_snapshots",
        sa.Column(
            "is_anomalous",
            sa.Boolean(),
            nullable=False,
            server_default="false",
            comment="True if any metric value contradicted the expected contract (e.g. negative like_count)",
        ),
    )
    op.add_column(
        "video_public_snapshots",
        sa.Column(
            "anomaly_notes",
            sa.Text(),
            nullable=True,
            comment="Original anomalous value(s) and diagnosis; preserved for audit even when the column stores NULL",
        ),
    )


def downgrade() -> None:
    """Remove is_anomalous and anomaly_notes from video_public_snapshots."""
    op.drop_column("video_public_snapshots", "anomaly_notes")
    op.drop_column("video_public_snapshots", "is_anomalous")
