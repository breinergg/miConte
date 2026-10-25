"""Analytical private metrics domain models for miConte.

Covers channel daily series, video daily series, and video aggregated periods,
strictly adhering to YouTube Analytics API v2 and Reporting API v1 capabilities.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Double,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from miconte.persistence.base import Base


class ChannelDailyMetric(Base):
    """Aggregated daily channel time series from YouTube Analytics API v2 (dimensions=day)."""

    __tablename__ = "channel_daily_metrics"
    __table_args__ = (
        UniqueConstraint("channel_id", "metric_date", name="uq_channel_daily_date"),
        Index("ix_channel_daily_metrics_date", "channel_id", "metric_date"),
        CheckConstraint("views >= 0", name="chk_channel_daily_views_non_neg"),
        CheckConstraint(
            "estimated_minutes_watched >= 0",
            name="chk_channel_daily_watch_time_non_neg",
        ),
        CheckConstraint(
            "average_view_duration_seconds >= 0",
            name="chk_channel_daily_duration_non_neg",
        ),
        CheckConstraint(
            "average_view_percentage >= 0.0",
            name="chk_channel_daily_percentage_non_neg",
        ),
        CheckConstraint("subscribers_gained >= 0", name="chk_channel_daily_subs_gained_non_neg"),
        CheckConstraint("subscribers_lost >= 0", name="chk_channel_daily_subs_lost_non_neg"),
        CheckConstraint(
            "likes >= 0 OR is_anomalous = TRUE",
            name="chk_channel_daily_likes_valid_or_anomalous",
        ),
        CheckConstraint("comments >= 0", name="chk_channel_daily_comments_non_neg"),
        CheckConstraint("shares >= 0", name="chk_channel_daily_shares_non_neg"),
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
    metric_date: Mapped[date] = mapped_column(Date, nullable=False)

    views: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    estimated_minutes_watched: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    average_view_duration_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    average_view_percentage: Mapped[float] = mapped_column(Double, default=0.0, nullable=False)

    subscribers_gained: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    subscribers_lost: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    likes: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        comment="Activity count of positive ratings in the period (expected >= 0)",
    )
    comments: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    shares: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    is_anomalous: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        comment="Flagged if upstream delivered values contradicting contract (e.g. negative likes)",
    )
    anomaly_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Relationships
    channel: Mapped["Channel"] = relationship("Channel", back_populates="daily_metrics")  # type: ignore[name-defined]  # noqa: F821


class VideoDailyMetric(Base):
    """Daily time series for a single video from YouTube Analytics API v2 (filters=video==ID)."""

    __tablename__ = "video_daily_metrics"
    __table_args__ = (
        UniqueConstraint("video_id", "metric_date", name="uq_video_daily_date"),
        Index("ix_video_daily_metrics_date", "video_id", "metric_date"),
        CheckConstraint("views >= 0", name="chk_video_daily_views_non_neg"),
        CheckConstraint(
            "estimated_minutes_watched >= 0",
            name="chk_video_daily_watch_time_non_neg",
        ),
        CheckConstraint(
            "average_view_duration_seconds >= 0",
            name="chk_video_daily_duration_non_neg",
        ),
        CheckConstraint(
            "average_view_percentage >= 0.0",
            name="chk_video_daily_percentage_non_neg",
        ),
        CheckConstraint(
            "likes >= 0 OR is_anomalous = TRUE",
            name="chk_video_daily_likes_valid_or_anomalous",
        ),
        CheckConstraint("comments >= 0", name="chk_video_daily_comments_non_neg"),
        CheckConstraint("shares >= 0", name="chk_video_daily_shares_non_neg"),
        CheckConstraint("subscribers_gained >= 0", name="chk_video_daily_subs_gained_non_neg"),
        CheckConstraint("subscribers_lost >= 0", name="chk_video_daily_subs_lost_non_neg"),
        CheckConstraint(
            "thumbnail_impressions IS NULL OR thumbnail_impressions >= 0",
            name="chk_video_daily_impressions_valid",
        ),
        CheckConstraint(
            "thumbnail_ctr IS NULL OR (thumbnail_ctr >= 0.0 AND thumbnail_ctr <= 1.0)",
            name="chk_video_daily_ctr_valid",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    video_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("videos.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    metric_date: Mapped[date] = mapped_column(Date, nullable=False)

    views: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    estimated_minutes_watched: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    average_view_duration_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    average_view_percentage: Mapped[float] = mapped_column(Double, default=0.0, nullable=False)

    likes: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        comment="Positive ratings event count for the day (expected >= 0)",
    )
    comments: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    shares: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    subscribers_gained: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    subscribers_lost: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Reach metrics: strictly nullable with source provenance
    thumbnail_impressions: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        comment="From Reporting API v1 reach report; NULL when not available or pending",
    )
    thumbnail_ctr: Mapped[float | None] = mapped_column(
        Double,
        nullable=True,
        comment="Ratio [0.0, 1.0] from Reporting API v1; NULL when unavailable",
    )
    reach_source: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        comment="Source identifier: 'reporting_api_v1' or NULL",
    )

    is_anomalous: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        comment="Flagged if unexpected negative metrics arrive from upstream",
    )
    anomaly_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Relationships
    video: Mapped["Video"] = relationship("Video", back_populates="daily_metrics")  # type: ignore[name-defined]  # noqa: F821


class VideoPeriodMetric(Base):
    """Aggregated metrics for a video over an arbitrary window (e.g. dimensions=video, 28 days)."""

    __tablename__ = "video_period_metrics"
    __table_args__ = (
        UniqueConstraint("video_id", "start_date", "end_date", name="uq_video_period_range"),
        Index("ix_video_period_metrics_range", "video_id", "start_date", "end_date"),
        CheckConstraint("start_date <= end_date", name="chk_period_dates_ordered"),
        CheckConstraint("views >= 0", name="chk_video_period_views_non_neg"),
        CheckConstraint(
            "estimated_minutes_watched >= 0",
            name="chk_video_period_watch_time_non_neg",
        ),
        CheckConstraint(
            "average_view_duration_seconds >= 0",
            name="chk_video_period_duration_non_neg",
        ),
        CheckConstraint(
            "average_view_percentage >= 0.0",
            name="chk_video_period_percentage_non_neg",
        ),
        CheckConstraint(
            "likes >= 0 OR is_anomalous = TRUE",
            name="chk_video_period_likes_valid_or_anomalous",
        ),
        CheckConstraint("comments >= 0", name="chk_video_period_comments_non_neg"),
        CheckConstraint("shares >= 0", name="chk_video_period_shares_non_neg"),
        CheckConstraint("subscribers_gained >= 0", name="chk_video_period_subs_gained_non_neg"),
        CheckConstraint("subscribers_lost >= 0", name="chk_video_period_subs_lost_non_neg"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    video_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("videos.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)

    views: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    estimated_minutes_watched: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    average_view_duration_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    average_view_percentage: Mapped[float] = mapped_column(Double, default=0.0, nullable=False)

    likes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    comments: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    shares: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    subscribers_gained: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    subscribers_lost: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    is_anomalous: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    anomaly_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Relationships
    video: Mapped["Video"] = relationship("Video", back_populates="period_metrics")  # type: ignore[name-defined]  # noqa: F821
