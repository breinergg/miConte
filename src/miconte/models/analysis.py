"""Audit trail and analytical execution domain models for miConte."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from miconte.persistence.base import Base


class SyncRun(Base):
    """Audit log of data synchronization runs per channel."""

    __tablename__ = "sync_runs"
    __table_args__ = (
        CheckConstraint("records_processed >= 0", name="chk_sync_records_non_neg"),
        Index("ix_sync_runs_channel_started", "channel_id", "started_at"),
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
    sync_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="Type of sync: 'metadata', 'public_snapshots', 'daily_analytics', 'reporting_jobs'",
    )
    status: Mapped[str] = mapped_column(
        String(32),
        default="pending",
        nullable=False,
        comment="Lifecycle status: 'pending', 'running', 'completed', 'failed'",
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    records_processed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # Relationships
    channel: Mapped["Channel"] = relationship("Channel", back_populates="sync_runs")  # type: ignore[name-defined]  # noqa: F821


class AnalysisRun(Base):
    """Execution record of a statistical or comparative analytics run."""

    __tablename__ = "analysis_runs"
    __table_args__ = (
        CheckConstraint(
            "sample_size_n IS NULL OR sample_size_n >= 0",
            name="chk_analysis_sample_size_valid",
        ),
        Index("ix_analysis_runs_channel_started", "channel_id", "started_at"),
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
    video_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("videos.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    analysis_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="Type of analysis: 'cohort_baseline', 'distribution_check', 'performance_velocity'",
    )
    status: Mapped[str] = mapped_column(
        String(32),
        default="pending",
        nullable=False,
        comment="'pending', 'running', 'completed', 'failed'",
    )
    parameters: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
        comment="Input parameters, date windows, and test criteria",
    )
    sample_size_n: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="Evaluated sample size N; validated against heuristics (N>=10, N>=20, N>=30)",
    )
    summary_results: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="Computed statistics, confidence intervals, p-values and descriptive metrics",
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # Relationships
    channel: Mapped["Channel"] = relationship("Channel", back_populates="analysis_runs")  # type: ignore[name-defined]  # noqa: F821
    video: Mapped["Video | None"] = relationship("Video")  # type: ignore[name-defined]  # noqa: F821
    recommendations: Mapped[list["Recommendation"]] = relationship(
        "Recommendation",
        back_populates="analysis_run",
        cascade="all, delete-orphan",
    )


class Recommendation(Base):
    """Deterministic, non-causal recommendation produced by an analysis run."""

    __tablename__ = "recommendations"
    __table_args__ = (Index("ix_recommendations_channel_created", "channel_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    analysis_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("analysis_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    channel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("channels.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    video_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("videos.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    rule_code: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Deterministic descriptive text; strict prohibition of unjustified causal claims",
    )
    priority: Mapped[str] = mapped_column(
        String(32),
        default="medium",
        nullable=False,
        comment="'low', 'medium', 'high', 'info'",
    )
    metrics_evidence: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
        comment="Statistical values, baselines, and sample sizes supporting the diagnosis",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # Relationships
    analysis_run: Mapped["AnalysisRun"] = relationship(
        "AnalysisRun",
        back_populates="recommendations",
    )
    channel: Mapped["Channel"] = relationship("Channel")  # type: ignore[name-defined]  # noqa: F821
    video: Mapped["Video | None"] = relationship("Video")  # type: ignore[name-defined]  # noqa: F821
