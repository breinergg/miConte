"""Typed Pydantic v2 DTOs for YouTube API integrations."""

import re
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

_DURATION_REGEX = re.compile(
    r"^P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?$"
)


def parse_iso8601_duration_to_seconds(duration_str: str) -> int:
    """Parse an ISO 8601 duration string (e.g., 'PT1H2M3S', 'PT15M33S', 'PT45S') to seconds."""
    if not duration_str:
        return 0

    match = _DURATION_REGEX.match(duration_str.strip())
    if not match:
        return 0

    groups = match.groupdict()
    days = int(groups.get("days") or 0)
    hours = int(groups.get("hours") or 0)
    minutes = int(groups.get("minutes") or 0)
    seconds = int(groups.get("seconds") or 0)

    return days * 86400 + hours * 3600 + minutes * 60 + seconds


class YouTubeChannelDTO(BaseModel):
    """Normalized channel metadata from YouTube Data API v3 channels.list."""

    model_config = ConfigDict(frozen=True)

    youtube_channel_id: str
    title: str
    uploads_playlist_id: str
    description: str | None = None
    custom_url: str | None = None
    published_at: datetime | None = None
    thumbnail_url: str | None = None
    view_count: int = 0
    subscriber_count: int | None = None  # None when creator hides subscriber count
    video_count: int = 0


class YouTubePlaylistItemDTO(BaseModel):
    """Single item retrieved from YouTube Data API v3 playlistItems.list."""

    model_config = ConfigDict(frozen=True)

    video_id: str
    title: str | None = None
    published_at: datetime | None = None
    position: int | None = None


class YouTubeVideoDTO(BaseModel):
    """Normalized video metadata and public stats from YouTube Data API v3 videos.list."""

    model_config = ConfigDict(frozen=True)

    youtube_video_id: str
    title: str
    uploads_playlist_id: str | None = None
    description: str | None = None
    published_at: datetime | None = None
    duration_seconds: int = Field(ge=0)
    duration_iso: str
    thumbnail_url: str | None = None
    tags: list[str] = Field(default_factory=list)
    category_id: str | None = None
    default_language: str | None = None
    view_count: int = Field(default=0, ge=0)
    # Important: None if hidden by creator or disabled, never coerced to 0
    like_count: int | None = None
    comment_count: int | None = None


class AnalyticsColumnHeaderDTO(BaseModel):
    """Column header metadata in YouTube Analytics API v2 reports.query response."""

    model_config = ConfigDict(frozen=True)

    name: str
    column_type: str  # 'DIMENSION' or 'METRIC'
    data_type: str  # 'STRING', 'INTEGER', 'FLOAT'


class AnalyticsReportDTO(BaseModel):
    """Normalized tabular report from YouTube Analytics API v2 reports.query."""

    model_config = ConfigDict(frozen=True)

    column_headers: list[AnalyticsColumnHeaderDTO]
    rows: list[list[Any]] = Field(default_factory=list)


class ReportingJobDTO(BaseModel):
    """Report job configuration in YouTube Reporting API v1."""

    model_config = ConfigDict(frozen=True)

    job_id: str
    report_type_id: str
    name: str | None = None
    create_time: datetime | None = None


class ReportingReportDTO(BaseModel):
    """Individual generated bulk report in YouTube Reporting API v1."""

    model_config = ConfigDict(frozen=True)

    report_id: str
    job_id: str
    start_time: datetime | None = None
    end_time: datetime | None = None
    create_time: datetime | None = None
    download_url: str


class ReportingReachRowDTO(BaseModel):
    """Parsed single row from bulk channel_reach_basic_a1 CSV report."""

    model_config = ConfigDict(frozen=True)

    date: date
    channel_id: str
    video_id: str
    live_or_on_demand: str
    video_thumbnail_impressions: int = Field(ge=0)
    video_thumbnail_impressions_ctr: float | None = None


class OAuthTokenResponseDTO(BaseModel):
    """Token payload returned by Google OAuth 2.0 token endpoint."""

    model_config = ConfigDict(frozen=True)

    access_token: str
    token_type: str = Field(default="Bearer")  # noqa: S105
    expires_in: int
    refresh_token: str | None = None
    scope: str


class DisconnectResultDTO(BaseModel):
    """Result of disconnection distinguishing local credential purge from remote revocation."""

    model_config = ConfigDict(frozen=True)

    channel_id: str
    local_disconnected: bool
    remote_revoked: bool
    details: str
