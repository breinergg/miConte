"""Data Transfer Objects for the synchronization engine."""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class SyncStageResultDTO(BaseModel):
    """Result summary for an individual synchronization stage."""

    model_config = ConfigDict(frozen=True)

    stage: str
    status: str  # 'succeeded', 'partially_succeeded', 'failed', 'skipped', 'pending'
    records_processed: int = 0
    details: str = ""


class SyncRunResultDTO(BaseModel):
    """Overall outcome of a channel synchronization run."""

    model_config = ConfigDict(frozen=True)

    sync_run_id: uuid.UUID
    channel_id: uuid.UUID
    sync_type: str
    status: str  # 'succeeded', 'partially_succeeded', 'failed'
    started_at: datetime
    completed_at: datetime | None = None
    records_processed: int = 0
    stages: list[SyncStageResultDTO] = Field(default_factory=list)
    error_message: str | None = None
    is_recoverable: bool = False


class SynchronizableChannelDTO(BaseModel):
    """Metadata of a channel eligible for synchronization by the current user."""

    model_config = ConfigDict(frozen=True)

    channel_id: uuid.UUID
    youtube_channel_id: str
    title: str
    is_oauth_connected: bool
    last_sync_at: datetime | None = None
    last_sync_status: str | None = None
    uploads_playlist_id: str = ""


class SchedulerStatusDTO(BaseModel):
    """Runtime status of the in-process periodic synchronization scheduler."""

    model_config = ConfigDict(frozen=True)

    is_running: bool
    sync_interval_hours: int
    active_jobs: list[str] = Field(default_factory=list)
    last_check_at: datetime | None = None
    channel_locks_active: int = 0


class SyncTriggerRequestDTO(BaseModel):
    """Options for manually triggering a channel synchronization."""

    sync_types: list[str] | None = Field(
        default=None,
        description=(
            "Optional list of stages: 'metadata', 'public_snapshots', 'analytics_daily', "
            "'analytics_period', 'reporting_reach'. Defaults to all."
        ),
    )
    start_date: date | None = Field(
        default=None,
        description="Optional start date for Analytics queries (defaults to 30 days prior).",
    )
    end_date: date | None = Field(
        default=None,
        description="Optional end date for Analytics queries (defaults to 2 days prior to today).",
    )
    max_videos: int | None = Field(
        default=None,
        description="Max videos to enumerate and snapshot (defaults to system setting).",
    )
