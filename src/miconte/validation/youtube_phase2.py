"""Phase 2 bounded technical validation for YouTube Data, Analytics, and Reporting APIs.

This module validates contract schemas, ISO 8601 duration conversion, pagination,
batch constraints, error classification, and tabular parsing without prematurely
implementing the Phase 4 production integration layer.
"""

import re
from datetime import date, datetime
from typing import Literal

import httpx
from pydantic import BaseModel, Field

_ISO8601_DURATION_RE = re.compile(
    r"^P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?$"
)

YOUTUBE_DATA_API_BASE = "https://www.googleapis.com/youtube/v3"
YOUTUBE_ANALYTICS_API_BASE = "https://youtubeanalytics.googleapis.com/v2"
YOUTUBE_REPORTING_API_BASE = "https://youtubereporting.googleapis.com/v1"

QUOTA_REASON_CODES = frozenset(
    {
        "quotaExceeded",
        "dailyLimitExceeded",
        "rateLimitExceeded",
        "userRateLimitExceeded",
    }
)


def parse_iso8601_duration_to_seconds(iso_duration: str) -> int:
    """Convert an ISO 8601 duration string (e.g. 'PT12M30S') to integer seconds.

    Raises:
        ValueError: If the string is empty, malformed, or lacks any time unit.
    """
    if not iso_duration or iso_duration in {"P", "PT"}:
        raise ValueError(f"Invalid ISO 8601 duration: {iso_duration!r}")

    match = _ISO8601_DURATION_RE.match(iso_duration)
    if match is None:
        raise ValueError(f"Invalid ISO 8601 duration: {iso_duration!r}")

    days = int(match.group("days") or 0)
    hours = int(match.group("hours") or 0)
    minutes = int(match.group("minutes") or 0)
    seconds = int(match.group("seconds") or 0)

    return days * 86400 + hours * 3600 + minutes * 60 + seconds


class YouTubeAPIError(Exception):
    """Base exception for classified YouTube API errors during Phase 2 validation."""

    def __init__(self, status_code: int, reason: str, message: str) -> None:
        super().__init__(f"HTTP {status_code} ({reason}): {message}")
        self.status_code = status_code
        self.reason = reason
        self.message = message


class YouTubeAuthenticationError(YouTubeAPIError):
    """Raised on HTTP 401 invalid or expired credentials."""


class YouTubePermissionError(YouTubeAPIError):
    """Raised on HTTP 403 insufficient permissions / missing OAuth scope."""


class YouTubeQuotaExceededError(YouTubeAPIError):
    """Raised on HTTP 403/429 quota or rate limit exhaustion."""


class YouTubeNotFoundError(YouTubeAPIError):
    """Raised on HTTP 404 resource not found."""


class YouTubeInvalidQueryError(YouTubeAPIError):
    """Raised on HTTP 400 invalid metric/dimension/filter combination."""


class ValidatedChannelMetadata(BaseModel):
    """Normalized channel metadata validated from `channels.list`."""

    channel_id: str
    title: str
    custom_url: str | None = None
    published_at: datetime
    country: str | None = None
    uploads_playlist_id: str
    view_count: int = Field(ge=0)
    subscriber_count: int | None = Field(default=None, ge=0)
    hidden_subscriber_count: bool = False
    video_count: int = Field(ge=0)


class ValidatedVideoMetadata(BaseModel):
    """Normalized video metadata and public statistics validated from `videos.list`."""

    video_id: str
    channel_id: str
    title: str
    published_at: datetime
    duration_iso: str
    duration_seconds: int = Field(ge=0)
    view_count: int = Field(ge=0)
    like_count: int | None = Field(default=None, ge=0)
    comment_count: int | None = Field(default=None, ge=0)


class AnalyticsColumnHeader(BaseModel):
    """Column header definition from `youtubeAnalytics#resultTable`."""

    name: str
    column_type: str = Field(alias="columnType")
    data_type: str = Field(alias="dataType")


class ValidatedAnalyticsReport(BaseModel):
    """Validated tabular response from YouTube Analytics API v2 `reports.query`."""

    column_headers: list[AnalyticsColumnHeader] = Field(
        default_factory=list,
        alias="columnHeaders",
    )
    rows: list[list[str | int | float | None]] = Field(default_factory=list)

    def to_records(self) -> list[dict[str, str | int | float | None]]:
        """Map tabular rows to dictionaries keyed by column header name."""
        header_names = [col.name for col in self.column_headers]
        return [dict(zip(header_names, row, strict=True)) for row in self.rows]


class ReportingReportType(BaseModel):
    """Report type metadata from YouTube Reporting API v1 `reportTypes.list`."""

    report_type_id: str = Field(alias="id")
    name: str


class ReportingJobReportItem(BaseModel):
    """Generated bulk report item from `jobs.reports.list`."""

    report_id: str = Field(alias="id")
    job_id: str = Field(alias="jobId")
    start_time: datetime | None = Field(default=None, alias="startTime")
    end_time: datetime | None = Field(default=None, alias="endTime")
    create_time: datetime | None = Field(default=None, alias="createTime")
    download_url: str | None = Field(default=None, alias="downloadUrl")


class ReportingJobCheckResult(BaseModel):
    """Distinguishes whether a Reporting API job has generated files or is still pending."""

    job_id: str
    status: Literal["reports_available", "pending_generation"]
    reports: list[ReportingJobReportItem] = Field(default_factory=list)


class YouTubePhase2Validator:
    """Bounded validation client for Phase 2 contract and capability checks."""

    def __init__(
        self,
        http_client: httpx.Client,
        api_key: str | None = None,
        oauth_access_token: str | None = None,
    ) -> None:
        self._client = http_client
        self._api_key = api_key
        self._oauth_access_token = oauth_access_token

    def _auth_headers(self) -> dict[str, str]:
        if self._oauth_access_token:
            return {"Authorization": f"Bearer {self._oauth_access_token}"}
        return {}

    def _apply_data_api_auth(self, params: dict[str, str]) -> dict[str, str]:
        merged = dict(params)
        if self._api_key and not self._oauth_access_token:
            merged["key"] = self._api_key
        return merged

    def _raise_for_youtube_error(self, response: httpx.Response) -> None:
        if response.is_success:
            return

        reason = "unknownError"
        message = response.text
        try:
            payload = response.json()
            err_obj = payload.get("error", {})
            if isinstance(err_obj, dict):
                message = str(err_obj.get("message", message))
                errors_list = err_obj.get("errors", [])
                if isinstance(errors_list, list) and errors_list:
                    first_err = errors_list[0]
                    if isinstance(first_err, dict):
                        reason = str(first_err.get("reason", reason))
        except ValueError:
            pass

        status_code = response.status_code
        if status_code == 400:
            raise YouTubeInvalidQueryError(status_code, reason, message)
        if status_code == 401:
            raise YouTubeAuthenticationError(status_code, reason, message)
        if status_code in {403, 429}:
            if reason in QUOTA_REASON_CODES or status_code == 429:
                raise YouTubeQuotaExceededError(status_code, reason, message)
            raise YouTubePermissionError(status_code, reason, message)
        if status_code == 404:
            raise YouTubeNotFoundError(status_code, reason, message)
        raise YouTubeAPIError(status_code, reason, message)

    def fetch_channel_by_id(self, channel_id: str) -> ValidatedChannelMetadata | None:
        """Fetch channel metadata and uploads playlist ID via `channels.list` (1 quota unit)."""
        params = self._apply_data_api_auth(
            {
                "part": "snippet,contentDetails,statistics",
                "id": channel_id,
            }
        )
        response = self._client.get(
            f"{YOUTUBE_DATA_API_BASE}/channels",
            params=params,
            headers=self._auth_headers(),
        )
        self._raise_for_youtube_error(response)
        data = response.json()
        items = data.get("items", [])
        if not items:
            return None

        item = items[0]
        snippet = item.get("snippet", {})
        content_details = item.get("contentDetails", {})
        related_playlists = content_details.get("relatedPlaylists", {})
        statistics = item.get("statistics", {})
        hidden_subs = bool(statistics.get("hiddenSubscriberCount", False))
        raw_subs = statistics.get("subscriberCount")

        return ValidatedChannelMetadata(
            channel_id=str(item["id"]),
            title=str(snippet["title"]),
            custom_url=snippet.get("customUrl"),
            published_at=snippet["publishedAt"],
            country=snippet.get("country"),
            uploads_playlist_id=str(related_playlists["uploads"]),
            view_count=int(statistics.get("viewCount", 0)),
            subscriber_count=int(raw_subs) if raw_subs is not None and not hidden_subs else None,
            hidden_subscriber_count=hidden_subs,
            video_count=int(statistics.get("videoCount", 0)),
        )

    def list_upload_video_ids(
        self,
        uploads_playlist_id: str,
        *,
        max_results_per_page: int = 50,
        max_pages: int = 1,
    ) -> list[str]:
        """Enumerate uploaded video IDs via `playlistItems.list` (1 quota unit per page)."""
        if not 1 <= max_results_per_page <= 50:
            raise ValueError("max_results_per_page must be between 1 and 50")

        collected_ids: list[str] = []
        page_token: str | None = None
        pages_fetched = 0

        while pages_fetched < max_pages:
            params: dict[str, str] = {
                "part": "contentDetails",
                "playlistId": uploads_playlist_id,
                "maxResults": str(max_results_per_page),
            }
            if page_token is not None:
                params["pageToken"] = page_token

            response = self._client.get(
                f"{YOUTUBE_DATA_API_BASE}/playlistItems",
                params=self._apply_data_api_auth(params),
                headers=self._auth_headers(),
            )
            self._raise_for_youtube_error(response)
            data = response.json()

            for item in data.get("items", []):
                content_details = item.get("contentDetails", {})
                video_id = content_details.get("videoId")
                if isinstance(video_id, str) and video_id:
                    collected_ids.append(video_id)

            pages_fetched += 1
            next_token = data.get("nextPageToken")
            if not isinstance(next_token, str) or not next_token:
                break
            page_token = next_token

        return collected_ids

    def fetch_videos_by_ids(self, video_ids: list[str]) -> list[ValidatedVideoMetadata]:
        """Fetch video details and public statistics in a single batch (max 50 IDs, 1 unit)."""
        if not video_ids:
            return []
        if len(video_ids) > 50:
            raise ValueError("videos.list accepts a maximum of 50 video IDs per request")

        params = self._apply_data_api_auth(
            {
                "part": "snippet,contentDetails,statistics",
                "id": ",".join(video_ids),
                "maxResults": str(len(video_ids)),
            }
        )
        response = self._client.get(
            f"{YOUTUBE_DATA_API_BASE}/videos",
            params=params,
            headers=self._auth_headers(),
        )
        self._raise_for_youtube_error(response)
        data = response.json()

        results: list[ValidatedVideoMetadata] = []
        for item in data.get("items", []):
            snippet = item.get("snippet", {})
            content_details = item.get("contentDetails", {})
            statistics = item.get("statistics", {})

            duration_iso = str(content_details.get("duration", "PT0S"))
            duration_seconds = parse_iso8601_duration_to_seconds(duration_iso)

            raw_likes = statistics.get("likeCount")
            raw_comments = statistics.get("commentCount")

            results.append(
                ValidatedVideoMetadata(
                    video_id=str(item["id"]),
                    channel_id=str(snippet["channelId"]),
                    title=str(snippet["title"]),
                    published_at=snippet["publishedAt"],
                    duration_iso=duration_iso,
                    duration_seconds=duration_seconds,
                    view_count=int(statistics.get("viewCount", 0)),
                    like_count=int(raw_likes) if raw_likes is not None else None,
                    comment_count=int(raw_comments) if raw_comments is not None else None,
                )
            )
        return results

    def query_analytics_report(
        self,
        *,
        start_date: date,
        end_date: date,
        metrics: list[str],
        dimensions: list[str] | None = None,
        filters: str | None = None,
        sort: str | None = None,
        max_results: int | None = None,
        ids: str = "channel==MINE",
    ) -> ValidatedAnalyticsReport:
        """Query YouTube Analytics API v2 `reports.query` with dimension validation."""
        dim_set = set(dimensions or [])
        if "video" in dim_set and ("day" in dim_set or "month" in dim_set):
            raise ValueError(
                "Combining 'video' and 'day' in dimensions is not supported by "
                "YouTube Analytics API v2; use dimensions=['day'] with filters='video==VIDEO_ID'."
            )

        params: dict[str, str] = {
            "ids": ids,
            "startDate": start_date.isoformat(),
            "endDate": end_date.isoformat(),
            "metrics": ",".join(metrics),
        }
        if dimensions:
            params["dimensions"] = ",".join(dimensions)
        if filters:
            params["filters"] = filters
        if sort:
            params["sort"] = sort
        if max_results is not None:
            params["maxResults"] = str(max_results)

        response = self._client.get(
            f"{YOUTUBE_ANALYTICS_API_BASE}/reports",
            params=params,
            headers=self._auth_headers(),
        )
        self._raise_for_youtube_error(response)
        return ValidatedAnalyticsReport.model_validate(response.json())

    def list_reporting_report_types(self) -> list[ReportingReportType]:
        """List available bulk report types in YouTube Reporting API v1."""
        response = self._client.get(
            f"{YOUTUBE_REPORTING_API_BASE}/reportTypes",
            headers=self._auth_headers(),
        )
        self._raise_for_youtube_error(response)
        data = response.json()
        return [ReportingReportType.model_validate(rt) for rt in data.get("reportTypes", [])]

    def check_reporting_job_reports(self, job_id: str) -> ReportingJobCheckResult:
        """Inspect generated report files for a Reporting API job (`jobs.reports.list`)."""
        response = self._client.get(
            f"{YOUTUBE_REPORTING_API_BASE}/jobs/{job_id}/reports",
            headers=self._auth_headers(),
        )
        self._raise_for_youtube_error(response)
        data = response.json()
        reports = [ReportingJobReportItem.model_validate(item) for item in data.get("reports", [])]
        status_val: Literal["reports_available", "pending_generation"] = (
            "reports_available" if reports else "pending_generation"
        )
        return ReportingJobCheckResult(
            job_id=job_id,
            status=status_val,
            reports=reports,
        )
