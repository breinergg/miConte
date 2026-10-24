"""Offline contract and error-handling tests for Phase 2 YouTube API validation.

IMPORTANT: All payloads in this module are synthetic test fixtures (`verified_offline`)
constructed from Google's official API documentation schemas. They must never be
interpreted as live data fetched from YouTube.
"""

from datetime import UTC, date, datetime

import httpx
import pytest

from miconte.validation.live_probe import run_live_probe
from miconte.validation.youtube_phase2 import (
    YouTubeAPIError,
    YouTubeAuthenticationError,
    YouTubeInvalidQueryError,
    YouTubeNotFoundError,
    YouTubePermissionError,
    YouTubePhase2Validator,
    YouTubeQuotaExceededError,
    parse_iso8601_duration_to_seconds,
)


@pytest.mark.parametrize(
    ("iso_duration", "expected_seconds"),
    [
        ("PT0S", 0),
        ("PT45S", 45),
        ("PT12M30S", 750),
        ("PT1H2M3S", 3723),
        ("P1DT2H", 93600),
        ("PT15M", 900),
        ("PT2H", 7200),
    ],
)
def test_parse_iso8601_duration_to_seconds_valid(
    iso_duration: str,
    expected_seconds: int,
) -> None:
    """Verify conversion of ISO 8601 YouTube video durations into integer seconds."""
    assert parse_iso8601_duration_to_seconds(iso_duration) == expected_seconds


@pytest.mark.parametrize("invalid_duration", ["", "INVALID", "12M30S", "PT", "P"])
def test_parse_iso8601_duration_to_seconds_rejects_invalid(invalid_duration: str) -> None:
    """Verify malformed ISO 8601 duration strings raise ValueError."""
    with pytest.raises(ValueError, match="Invalid ISO 8601 duration"):
        parse_iso8601_duration_to_seconds(invalid_duration)


def test_fetch_channel_public_metadata_and_uploads_playlist() -> None:
    """Validate parsing of channels.list response including uploads playlist and statistics."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/youtube/v3/channels"
        assert request.url.params["part"] == "snippet,contentDetails,statistics"
        assert request.url.params["id"] == "UC_TEST_CHANNEL_001"
        assert request.url.params["key"] == "TEST_API_KEY_FIXTURE"
        return httpx.Response(
            200,
            json={
                "kind": "youtube#channelListResponse",
                "pageInfo": {"totalResults": 1, "resultsPerPage": 5},
                "items": [
                    {
                        "id": "UC_TEST_CHANNEL_001",
                        "snippet": {
                            "title": "Canal Fixture de Prueba",
                            "customUrl": "@canalfixture",
                            "publishedAt": "2022-03-15T10:00:00Z",
                            "country": "CO",
                        },
                        "contentDetails": {
                            "relatedPlaylists": {
                                "uploads": "UU_TEST_CHANNEL_001",
                            }
                        },
                        "statistics": {
                            "viewCount": "125430",
                            "subscriberCount": "4520",
                            "hiddenSubscriberCount": False,
                            "videoCount": "42",
                        },
                    }
                ],
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    validator = YouTubePhase2Validator(http_client=client, api_key="TEST_API_KEY_FIXTURE")

    channel = validator.fetch_channel_by_id("UC_TEST_CHANNEL_001")

    assert channel is not None
    assert channel.channel_id == "UC_TEST_CHANNEL_001"
    assert channel.title == "Canal Fixture de Prueba"
    assert channel.uploads_playlist_id == "UU_TEST_CHANNEL_001"
    assert channel.view_count == 125430
    assert channel.subscriber_count == 4520
    assert channel.video_count == 42


def test_fetch_channel_returns_none_on_empty_items() -> None:
    """Verify channels.list handles an empty items array gracefully."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "kind": "youtube#channelListResponse",
                "pageInfo": {"totalResults": 0, "resultsPerPage": 5},
                "items": [],
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    validator = YouTubePhase2Validator(http_client=client, api_key="TEST_API_KEY_FIXTURE")

    assert validator.fetch_channel_by_id("UC_NON_EXISTENT") is None


def test_list_upload_video_ids_handles_pagination() -> None:
    """Verify playlistItems.list follows nextPageToken and enforces maxResults<=50."""
    calls: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/youtube/v3/playlistItems"
        assert request.url.params["playlistId"] == "UU_TEST_CHANNEL_001"
        assert int(request.url.params["maxResults"]) <= 50
        page_token = request.url.params.get("pageToken")
        calls.append(page_token)

        if page_token is None:
            return httpx.Response(
                200,
                json={
                    "kind": "youtube#playlistItemListResponse",
                    "nextPageToken": "PAGE_2_TOKEN",
                    "items": [
                        {
                            "contentDetails": {
                                "videoId": "VID_001",
                                "videoPublishedAt": "2026-09-01T12:00:00Z",
                            }
                        },
                        {
                            "contentDetails": {
                                "videoId": "VID_002",
                                "videoPublishedAt": "2026-09-05T12:00:00Z",
                            }
                        },
                    ],
                },
            )
        return httpx.Response(
            200,
            json={
                "kind": "youtube#playlistItemListResponse",
                "items": [
                    {
                        "contentDetails": {
                            "videoId": "VID_003",
                            "videoPublishedAt": "2026-09-10T12:00:00Z",
                        }
                    }
                ],
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    validator = YouTubePhase2Validator(http_client=client, api_key="TEST_API_KEY_FIXTURE")

    video_ids = validator.list_upload_video_ids("UU_TEST_CHANNEL_001", max_pages=5)

    assert video_ids == ["VID_001", "VID_002", "VID_003"]
    assert calls == [None, "PAGE_2_TOKEN"]


def test_fetch_videos_batch_parses_durations_and_missing_optional_fields() -> None:
    """Verify videos.list parses ISO duration and tolerates hidden likeCount/commentCount."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/youtube/v3/videos"
        assert request.url.params["id"] == "VID_001,VID_002"
        return httpx.Response(
            200,
            json={
                "kind": "youtube#videoListResponse",
                "items": [
                    {
                        "id": "VID_001",
                        "snippet": {
                            "channelId": "UC_TEST_CHANNEL_001",
                            "title": "Video Completo Fixture",
                            "publishedAt": "2026-09-01T12:00:00Z",
                        },
                        "contentDetails": {
                            "duration": "PT10M15S",
                        },
                        "statistics": {
                            "viewCount": "9500",
                            "likeCount": "610",
                            "commentCount": "48",
                        },
                    },
                    {
                        "id": "VID_002",
                        "snippet": {
                            "channelId": "UC_TEST_CHANNEL_001",
                            "title": "Video con Likes y Comentarios Ocultos",
                            "publishedAt": "2026-09-05T15:30:00Z",
                        },
                        "contentDetails": {
                            "duration": "PT55S",
                        },
                        # likeCount and commentCount omitted when disabled by creator
                        "statistics": {
                            "viewCount": "1200",
                        },
                    },
                ],
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    validator = YouTubePhase2Validator(http_client=client, api_key="TEST_API_KEY_FIXTURE")

    videos = validator.fetch_videos_by_ids(["VID_001", "VID_002"])

    assert len(videos) == 2
    assert videos[0].video_id == "VID_001"
    assert videos[0].duration_seconds == 615
    assert videos[0].view_count == 9500
    assert videos[0].like_count == 610
    assert videos[0].comment_count == 48
    assert videos[0].published_at == datetime(2026, 9, 1, 12, 0, tzinfo=UTC)

    assert videos[1].video_id == "VID_002"
    assert videos[1].duration_seconds == 55
    assert videos[1].view_count == 1200
    assert videos[1].like_count is None
    assert videos[1].comment_count is None


def test_fetch_videos_rejects_batch_over_50_ids() -> None:
    """Verify videos.list enforces the official 50-ID per request limit."""
    client = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200)))
    validator = YouTubePhase2Validator(http_client=client, api_key="TEST_API_KEY_FIXTURE")

    too_many_ids = [f"VID_{i:03d}" for i in range(51)]
    with pytest.raises(ValueError, match="maximum of 50 video IDs"):
        validator.fetch_videos_by_ids(too_many_ids)


@pytest.mark.parametrize(
    ("status_code", "reason", "expected_exception"),
    [
        (401, "authError", YouTubeAuthenticationError),
        (403, "quotaExceeded", YouTubeQuotaExceededError),
        (403, "dailyLimitExceeded", YouTubeQuotaExceededError),
        (403, "insufficientPermissions", YouTubePermissionError),
        (403, "forbidden", YouTubePermissionError),
        (404, "channelNotFound", YouTubeNotFoundError),
        (400, "badRequest", YouTubeInvalidQueryError),
    ],
)
def test_youtube_error_classification(
    status_code: int,
    reason: str,
    expected_exception: type[YouTubeAPIError],
) -> None:
    """Verify HTTP 400, 401, 403 (quota vs permission), and 404 map to typed exceptions."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code,
            json={
                "error": {
                    "code": status_code,
                    "message": f"Simulated {reason} error",
                    "errors": [{"domain": "youtube.quota", "reason": reason}],
                }
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    validator = YouTubePhase2Validator(http_client=client, api_key="TEST_API_KEY_FIXTURE")

    with pytest.raises(expected_exception) as exc_info:
        validator.fetch_channel_by_id("UC_ERR")

    assert exc_info.value.status_code == status_code
    assert exc_info.value.reason == reason


def test_analytics_reports_query_parses_tabular_headers_and_rows() -> None:
    """Verify YouTube Analytics API v2 tabular response (`columnHeaders` + `rows`) parsing."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v2/reports"
        assert request.headers.get("Authorization") == "Bearer TEST_OAUTH_TOKEN_FIXTURE"
        assert request.url.params["ids"] == "channel==MINE"
        assert request.url.params["dimensions"] == "day"
        assert request.url.params["filters"] == "video==VID_001"
        return httpx.Response(
            200,
            json={
                "kind": "youtubeAnalytics#resultTable",
                "columnHeaders": [
                    {"name": "day", "columnType": "DIMENSION", "dataType": "STRING"},
                    {"name": "views", "columnType": "METRIC", "dataType": "INTEGER"},
                    {
                        "name": "estimatedMinutesWatched",
                        "columnType": "METRIC",
                        "dataType": "INTEGER",
                    },
                    {
                        "name": "averageViewDuration",
                        "columnType": "METRIC",
                        "dataType": "INTEGER",
                    },
                    {
                        "name": "averageViewPercentage",
                        "columnType": "METRIC",
                        "dataType": "FLOAT",
                    },
                    {"name": "likes", "columnType": "METRIC", "dataType": "INTEGER"},
                    {"name": "comments", "columnType": "METRIC", "dataType": "INTEGER"},
                    {"name": "shares", "columnType": "METRIC", "dataType": "INTEGER"},
                    {
                        "name": "subscribersGained",
                        "columnType": "METRIC",
                        "dataType": "INTEGER",
                    },
                    {
                        "name": "subscribersLost",
                        "columnType": "METRIC",
                        "dataType": "INTEGER",
                    },
                ],
                "rows": [
                    ["2026-09-01", 450, 1800, 240, 48.5, 35, 6, 4, 8, 1],
                    ["2026-09-02", 310, 1210, 234, 47.2, 22, 3, 2, 4, 0],
                ],
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    validator = YouTubePhase2Validator(
        http_client=client,
        oauth_access_token="TEST_OAUTH_TOKEN_FIXTURE",
    )

    report = validator.query_analytics_report(
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 2),
        metrics=[
            "views",
            "estimatedMinutesWatched",
            "averageViewDuration",
            "averageViewPercentage",
            "likes",
            "comments",
            "shares",
            "subscribersGained",
            "subscribersLost",
        ],
        dimensions=["day"],
        filters="video==VID_001",
    )

    assert len(report.column_headers) == 10
    records = report.to_records()
    assert len(records) == 2
    assert records[0]["day"] == "2026-09-01"
    assert records[0]["views"] == 450
    assert records[0]["averageViewPercentage"] == 48.5
    assert records[0]["subscribersGained"] == 8
    assert records[1]["subscribersLost"] == 0


def test_analytics_reports_query_rejects_unsupported_video_and_day_dimension_combo() -> None:
    """Verify local validation blocks `dimensions=['video', 'day']` before hitting API."""
    client = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200)))
    validator = YouTubePhase2Validator(
        http_client=client,
        oauth_access_token="TEST_OAUTH_TOKEN_FIXTURE",
    )

    with pytest.raises(
        ValueError,
        match="Combining 'video' and 'day' in dimensions is not supported",
    ):
        validator.query_analytics_report(
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 7),
            metrics=["views"],
            dimensions=["video", "day"],
        )


def test_reporting_api_reach_report_types_and_job_status_classification() -> None:
    """Verify YouTube Reporting API v1 reportTypes.list and jobs.reports.list parsing."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/reportTypes":
            return httpx.Response(
                200,
                json={
                    "reportTypes": [
                        {
                            "id": "channel_reach_basic_a1",
                            "name": "Channel reach basic",
                        },
                        {
                            "id": "channel_basic_a2",
                            "name": "Channel user activity",
                        },
                    ]
                },
            )
        if request.url.path == "/v1/jobs/JOB_123/reports":
            return httpx.Response(
                200,
                json={"reports": []},
            )
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    validator = YouTubePhase2Validator(
        http_client=client,
        oauth_access_token="TEST_OAUTH_TOKEN_FIXTURE",
    )

    report_types = validator.list_reporting_report_types()
    assert any(rt.report_type_id == "channel_reach_basic_a1" for rt in report_types)

    job_check = validator.check_reporting_job_reports("JOB_123")
    assert job_check.status == "pending_generation"
    assert job_check.reports == []


def test_live_probe_reports_missing_credentials_cleanly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify run_live_probe reports documented_not_tested when no credentials exist."""
    monkeypatch.delenv("MICONTE_YOUTUBE_API_KEY", raising=False)
    monkeypatch.delenv("MICONTE_YOUTUBE_OAUTH_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("MICONTE_YOUTUBE_TEST_CHANNEL_ID", raising=False)

    result = run_live_probe()
    assert result["has_api_key"] is False
    assert result["has_oauth_token"] is False
    assert result["overall_status"] == "documented_not_tested_missing_local_credentials"
