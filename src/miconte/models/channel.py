"""Channel catalog and public snapshot models for miConte."""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
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


class Channel(Base):
    """Connected YouTube channel catalog entry."""

    __tablename__ = "channels"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    youtube_channel_id: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    custom_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    uploads_playlist_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="Uploads playlist ID used to paginate published videos without search.list",
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    thumbnail_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

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
    user: Mapped["User"] = relationship("User", back_populates="channels")  # type: ignore[name-defined]  # noqa: F821
    videos: Mapped[list["Video"]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "Video",
        back_populates="channel",
        cascade="all, delete-orphan",
    )
    public_snapshots: Mapped[list["ChannelPublicSnapshot"]] = relationship(
        "ChannelPublicSnapshot",
        back_populates="channel",
        cascade="all, delete-orphan",
    )
    daily_metrics: Mapped[list["ChannelDailyMetric"]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "ChannelDailyMetric",
        back_populates="channel",
        cascade="all, delete-orphan",
    )
    sync_runs: Mapped[list["SyncRun"]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "SyncRun",
        back_populates="channel",
        cascade="all, delete-orphan",
    )
    analysis_runs: Mapped[list["AnalysisRun"]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "AnalysisRun",
        back_populates="channel",
        cascade="all, delete-orphan",
    )


class ChannelPublicSnapshot(Base):
    """Historical snapshot of public channel counts at an observation timestamp."""

    __tablename__ = "channel_public_snapshots"
    __table_args__ = (
        UniqueConstraint("channel_id", "captured_at", name="uq_channel_snapshot_captured"),
        Index("ix_channel_public_snapshots_captured", "channel_id", "captured_at"),
        CheckConstraint("view_count >= 0", name="chk_channel_views_non_negative"),
        CheckConstraint(
            "subscriber_count IS NULL OR subscriber_count >= 0",
            name="chk_channel_subscribers_valid",
        ),
        CheckConstraint("video_count >= 0", name="chk_channel_videos_non_negative"),
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
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    view_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    subscriber_count: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        comment="NULL if hiddenSubscriberCount=true on YouTube; distinguished from 0",
    )
    video_count: Mapped[int] = mapped_column(Integer, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # Relationships
    channel: Mapped["Channel"] = relationship("Channel", back_populates="public_snapshots")
