"""Reporting API ingestion tracking model for miConte."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from miconte.persistence.base import Base


class ReportingReportIngestion(Base):
    """Registry of YouTube Reporting API reports successfully ingested per channel.

    Each row represents one report file (identified by YouTube's report_id) that was
    downloaded, parsed, and fully committed to the metrics tables. Only written on
    success; never written on partial or failed ingestion.

    The (channel_id, report_period_start, report_period_end) index enables restatement
    detection: if YouTube re-issues a report for the same period with a newer
    create_time, the service can allow re-processing while skipping older versions.
    """

    __tablename__ = "reporting_report_ingestions"
    __table_args__ = (
        UniqueConstraint(
            "channel_id",
            "report_id",
            name="uq_reporting_ingestion_channel_report",
        ),
        Index(
            "ix_reporting_ingestion_channel_period",
            "channel_id",
            "report_period_start",
            "report_period_end",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    channel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("channels.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    report_id: Mapped[str] = mapped_column(
        String(256),
        nullable=False,
        comment="YouTube Reporting API report ID (globally unique per YouTube)",
    )
    job_id: Mapped[str] = mapped_column(
        String(256),
        nullable=False,
        comment="YouTube Reporting API job ID that produced this report",
    )
    report_period_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="start_time from YouTube for this report's data window",
    )
    report_period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="end_time from YouTube for this report's data window",
    )
    report_create_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="create_time from YouTube; used for restatement version comparison",
    )
    rows_ingested: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        comment="Number of CSV rows committed to video_daily_reach metrics",
    )
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="Wall-clock timestamp when this ingestion record was written",
    )

    channel: Mapped["Channel"] = relationship("Channel")  # type: ignore[name-defined]  # noqa: F821
