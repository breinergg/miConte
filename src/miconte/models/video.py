"""Video catalog and historical public snapshot domain models."""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
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


class Video(Base):
    """Catalog metadata for published YouTube videos."""

    __tablename__ = "videos"
    __table_args__ = (
        CheckConstraint("duration_seconds >= 0", name="chk_video_duration_non_negative"),
        Index("ix_videos_channel_published", "channel_id", "published_at"),
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
    youtube_video_id: Mapped[str] = mapped_column(
        String(32),
        unique=True,
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    duration_iso: Mapped[str] = mapped_column(String(32), nullable=False)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False)

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
    channel: Mapped["Channel"] = relationship("Channel", back_populates="videos")  # type: ignore[name-defined]  # noqa: F821
    public_snapshots: Mapped[list["VideoPublicSnapshot"]] = relationship(
        "VideoPublicSnapshot",
        back_populates="video",
        cascade="all, delete-orphan",
    )
    daily_metrics: Mapped[list["VideoDailyMetric"]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "VideoDailyMetric",
        back_populates="video",
        cascade="all, delete-orphan",
    )
    period_metrics: Mapped[list["VideoPeriodMetric"]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "VideoPeriodMetric",
        back_populates="video",
        cascade="all, delete-orphan",
    )


class VideoPublicSnapshot(Base):
    """Historical snapshot of public statistics for a video at a point in time."""

    __tablename__ = "video_public_snapshots"
    __table_args__ = (
        UniqueConstraint("video_id", "captured_at", name="uq_video_snapshot_captured"),
        Index("ix_video_public_snapshots_captured", "video_id", "captured_at"),
        CheckConstraint("view_count >= 0", name="chk_video_views_non_negative"),
        CheckConstraint(
            "like_count IS NULL OR like_count >= 0",
            name="chk_video_likes_valid",
        ),
        CheckConstraint(
            "comment_count IS NULL OR comment_count >= 0",
            name="chk_video_comments_valid",
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
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    view_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    like_count: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        comment="NULL if creator hid likes on YouTube; distinguished from 0",
    )
    comment_count: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        comment="NULL if comments are disabled; distinguished from 0",
    )

    is_anomalous: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        comment="True when a metric value violated the API contract (e.g. negative like_count)",
    )
    anomaly_notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Original anomalous value(s) and diagnosis; preserved for audit when NULL stored",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # Relationships
    video: Mapped["Video"] = relationship("Video", back_populates="public_snapshots")
