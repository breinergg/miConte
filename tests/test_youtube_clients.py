"""Automated unit tests for official YouTube API production clients using MockTransport."""

import asyncio
from datetime import date
from typing import Any

import httpx
import pytest

from miconte.integrations.youtube.analytics_v2 import YouTubeAnalyticsClient
from miconte.integrations.youtube.data_v3 import YouTubeDataClient
from miconte.integrations.youtube.dto import parse_iso8601_duration_to_seconds
from miconte.integrations.youtube.exceptions import (
    InsufficientPermissionsError,
    InvalidQueryError,
    QuotaExceededError,
    ResourceNotFoundError,
    TokenExpiredError,
)
from miconte.integrations.youtube.reporting_v1 import YouTubeReportingClient


def test_iso8601_duration_parsing() -> None:
    assert parse_iso8601_duration_to_seconds("PT0S") == 0
    assert parse_iso8601_duration_to_seconds("PT45S") == 45
    assert parse_iso8601_duration_to_seconds("PT10M") == 600
    assert parse_iso8601_duration_to_seconds("PT1H2M3S") == 3723
    assert parse_iso8601_duration_to_seconds("P1DT2H") == 93600
    assert parse_iso8601_duration_to_seconds("") == 0
    assert parse_iso8601_duration_to_seconds("INVALID") == 0


def test_data_client_get_channel_mine_success() -> None:
    async def _run() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.headers.get("Authorization") == "Bearer test_access_token"
            assert "mine=true" in str(request.url)
            content = {
                "items": [
                    {
                        "id": "UC_TEST_MINE_123",
                        "snippet": {
                            "title": "My Test Channel",
                            "description": "Tech and analytics channel",
                            "customUrl": "@mytestchannel",
                            "publishedAt": "2020-01-15T10:00:00Z",
                        },
                        "contentDetails": {
                            "relatedPlaylists": {
                                "uploads": "UU_TEST_MINE_123",
                            }
                        },
                        "statistics": {
                            "viewCount": "1250000",
                            "subscriberCount": "15400",
                            "hiddenSubscriberCount": False,
                            "videoCount": "85",
                        },
                    }
                ]
            }
            return httpx.Response(200, json=content)

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        yt_data = YouTubeDataClient(http_client=client)

        channel = await yt_data.get_channel(mine=True, access_token="test_access_token")
        assert channel.youtube_channel_id == "UC_TEST_MINE_123"
        assert channel.title == "My Test Channel"
        assert channel.uploads_playlist_id == "UU_TEST_MINE_123"
        assert channel.view_count == 1250000
        assert channel.subscriber_count == 15400
        assert channel.video_count == 85

    asyncio.run(_run())


def test_data_client_get_channel_hidden_subscribers() -> None:
    async def _run() -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            content = {
                "items": [
                    {
                        "id": "UC_TEST_HIDDEN",
                        "snippet": {"title": "Hidden Subs Channel"},
                        "contentDetails": {"relatedPlaylists": {"uploads": "UU_TEST_HIDDEN"}},
                        "statistics": {
                            "viewCount": "500",
                            "subscriberCount": "0",
                            "hiddenSubscriberCount": True,
                            "videoCount": "2",
                        },
                    }
                ]
            }
            return httpx.Response(200, json=content)

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        yt_data = YouTubeDataClient(http_client=client)

        channel = await yt_data.get_channel(channel_id="UC_TEST_HIDDEN", access_token="tok")
        # Must preserve None when hiddenSubscriberCount is True
        assert channel.subscriber_count is None

    asyncio.run(_run())


def test_data_client_get_channel_not_found() -> None:
    async def _run() -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"items": []})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        yt_data = YouTubeDataClient(http_client=client)

        with pytest.raises(ResourceNotFoundError, match="not found"):
            await yt_data.get_channel(channel_id="UC_NONEXISTENT", access_token="tok")

    asyncio.run(_run())


def test_data_client_list_playlist_items_pagination() -> None:
    async def _run() -> None:
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if "pageToken" not in str(request.url):
                content = {
                    "nextPageToken": "PAGE_2_TOKEN",
                    "items": [
                        {
                            "contentDetails": {"videoId": "VID_01"},
                            "snippet": {
                                "title": "Video 1",
                                "publishedAt": "2024-01-01T00:00:00Z",
                            },
                        }
                    ],
                }
            else:
                content = {
                    "items": [
                        {
                            "contentDetails": {"videoId": "VID_02"},
                            "snippet": {
                                "title": "Video 2",
                                "publishedAt": "2024-01-02T00:00:00Z",
                            },
                        }
                    ],
                }
            return httpx.Response(200, json=content)

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        yt_data = YouTubeDataClient(http_client=client)

        items1, next_tok = await yt_data.list_playlist_items(
            playlist_id="UU_123", access_token="tok", max_results=50
        )
        assert len(items1) == 1
        assert items1[0].video_id == "VID_01"
        assert next_tok == "PAGE_2_TOKEN"

        items2, next_tok2 = await yt_data.list_playlist_items(
            playlist_id="UU_123", page_token=next_tok, access_token="tok"
        )
        assert len(items2) == 1
        assert items2[0].video_id == "VID_02"
        assert next_tok2 is None

    asyncio.run(_run())


def test_data_client_list_videos_batching_and_null_metrics() -> None:
    async def _run() -> None:
        video_ids = [f"VID_{i:03d}" for i in range(75)]
        requested_chunks: list[list[str]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            query = str(request.url).split("?")[1]
            params = dict(qp.split("=") for qp in query.split("&") if "=" in qp)
            raw_id = params.get("id", "")
            ids = raw_id.split("%2C") if "%2C" in raw_id else raw_id.split(",")
            requested_chunks.append(ids)

            items: list[dict[str, Any]] = []
            for vid in ids:
                if vid == "VID_001":
                    stats = {"viewCount": "1000"}  # likeCount and commentCount absent
                else:
                    stats = {"viewCount": "5000", "likeCount": "200", "commentCount": "30"}

                items.append(
                    {
                        "id": vid,
                        "snippet": {
                            "title": f"Title for {vid}",
                            "description": "Desc",
                            "publishedAt": "2024-01-10T12:00:00Z",
                        },
                        "contentDetails": {"duration": "PT5M15S"},
                        "statistics": stats,
                    }
                )
            return httpx.Response(200, json={"items": items})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        yt_data = YouTubeDataClient(http_client=client)

        results = await yt_data.list_videos_batch(video_ids=video_ids, access_token="tok")
        assert len(results) == 75
        assert len(requested_chunks) == 2
        assert len(requested_chunks[0]) == 50
        assert len(requested_chunks[1]) == 25

        # Check VID_001 has None for likes/comments, not 0
        v1 = next(v for v in results if v.youtube_video_id == "VID_001")
        assert v1.view_count == 1000
        assert v1.like_count is None
        assert v1.comment_count is None
        assert v1.duration_seconds == 315

        # Check standard video has parsed likes
        v2 = next(v for v in results if v.youtube_video_id == "VID_002")
        assert v2.view_count == 5000
        assert v2.like_count == 200
        assert v2.comment_count == 30

    asyncio.run(_run())


def test_data_client_error_handling() -> None:
    async def _run() -> None:
        # Test QuotaExceeded
        def quota_handler(_req: httpx.Request) -> httpx.Response:
            err = {
                "error": {
                    "code": 403,
                    "message": "Quota exceeded",
                    "errors": [{"reason": "quotaExceeded"}],
                }
            }
            return httpx.Response(403, json=err)

        client = httpx.AsyncClient(transport=httpx.MockTransport(quota_handler))
        yt_data = YouTubeDataClient(http_client=client)

        with pytest.raises(QuotaExceededError, match="quota exceeded"):
            await yt_data.get_channel(channel_id="UC_1", access_token="tok")

        # Test TokenExpired (401)
        def auth_handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(
                401, json={"error": {"code": 401, "message": "Invalid Credentials"}}
            )

        client_auth = httpx.AsyncClient(transport=httpx.MockTransport(auth_handler))
        yt_data_auth = YouTubeDataClient(http_client=client_auth)

        with pytest.raises(TokenExpiredError, match="Authentication failed"):
            await yt_data_auth.get_channel(channel_id="UC_1", access_token="bad_tok")

        # Test InsufficientPermissions (403 forbidden)
        def perm_handler(_req: httpx.Request) -> httpx.Response:
            err = {
                "error": {
                    "code": 403,
                    "message": "Insufficient Permission",
                    "errors": [{"reason": "insufficientPermissions"}],
                }
            }
            return httpx.Response(403, json=err)

        client_perm = httpx.AsyncClient(transport=httpx.MockTransport(perm_handler))
        yt_data_perm = YouTubeDataClient(http_client=client_perm)

        with pytest.raises(InsufficientPermissionsError, match="Forbidden"):
            await yt_data_perm.get_channel(mine=True, access_token="tok")

    asyncio.run(_run())


def test_analytics_client_query_report_success() -> None:
    async def _run() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert "startDate=2024-01-01" in str(request.url)
            assert "endDate=2024-01-07" in str(request.url)
            assert "dimensions=day" in str(request.url)
            content = {
                "columnHeaders": [
                    {"name": "day", "columnType": "DIMENSION", "dataType": "STRING"},
                    {"name": "views", "columnType": "METRIC", "dataType": "INTEGER"},
                    {"name": "likes", "columnType": "METRIC", "dataType": "INTEGER"},
                ],
                "rows": [
                    ["2024-01-01", 1200, 45],
                    ["2024-01-02", 1350, 60],
                ],
            }
            return httpx.Response(200, json=content)

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        yt_analytics = YouTubeAnalyticsClient(http_client=client)

        report = await yt_analytics.query_report(
            access_token="tok",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 7),
            metrics=["views", "likes"],
            dimensions=["day"],
        )
        assert len(report.column_headers) == 3
        assert report.column_headers[1].name == "views"
        assert len(report.rows) == 2
        assert report.rows[0] == ["2024-01-01", 1200, 45]

    asyncio.run(_run())


def test_analytics_client_rejects_video_day_without_multi_filter() -> None:
    """dimensions=video,day without a multi-value video filter must be rejected."""
    async def _run() -> None:
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200)),
        )
        yt_analytics = YouTubeAnalyticsClient(http_client=client)

        # No filter at all
        with pytest.raises(InvalidQueryError, match="multi-value video filter"):
            await yt_analytics.query_report(
                access_token="tok",
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 7),
                metrics=["views"],
                dimensions=["video", "day"],
            )

        # Single-value video filter
        with pytest.raises(InvalidQueryError, match="multi-value video filter"):
            await yt_analytics.query_report(
                access_token="tok",
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 7),
                metrics=["views"],
                dimensions=["video", "day"],
                filters="video==VID_001",
            )

        with pytest.raises(InvalidQueryError, match="cannot be after endDate"):
            await yt_analytics.query_report(
                access_token="tok",
                start_date=date(2024, 1, 10),
                end_date=date(2024, 1, 1),
                metrics=["views"],
            )

    asyncio.run(_run())


def test_analytics_client_allows_video_day_with_multi_filter() -> None:
    """dimensions=day,video with a multi-value video filter must be allowed."""
    async def _run() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert "dimensions=day%2Cvideo" in str(request.url) or \
                "dimensions=day,video" in str(request.url)
            content = {
                "columnHeaders": [
                    {"name": "day", "columnType": "DIMENSION", "dataType": "STRING"},
                    {"name": "video", "columnType": "DIMENSION", "dataType": "STRING"},
                    {"name": "views", "columnType": "METRIC", "dataType": "INTEGER"},
                ],
                "rows": [
                    ["2024-01-01", "VID_A", 100],
                    ["2024-01-01", "VID_B", 200],
                    ["2024-01-02", "VID_A", 150],
                    ["2024-01-02", "VID_B", 250],
                ],
            }
            return httpx.Response(200, json=content)

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        yt_analytics = YouTubeAnalyticsClient(http_client=client)

        report = await yt_analytics.query_report(
            access_token="tok",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 7),
            metrics=["views"],
            dimensions=["day", "video"],
            filters="video==VID_A,VID_B",
        )
        assert len(report.rows) == 4
        assert report.column_headers[1].name == "video"

    asyncio.run(_run())


def test_reporting_client_lifecycle_and_csv_parsing() -> None:
    async def _run() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            url_str = str(request.url)
            if request.method == "GET" and "reportTypes" in url_str:
                return httpx.Response(
                    200,
                    json={
                        "reportTypes": [{"id": "channel_reach_basic_a1", "name": "Basic Reach"}]
                    },
                )
            if request.method == "POST" and "jobs" in url_str:
                return httpx.Response(
                    200,
                    json={
                        "id": "JOB_REACH_001",
                        "reportTypeId": "channel_reach_basic_a1",
                        "name": "miConte Reach",
                        "createTime": "2024-01-01T00:00:00Z",
                    },
                )
            if request.method == "GET" and "jobs/JOB_REACH_001/reports" in url_str:
                return httpx.Response(
                    200,
                    json={
                        "reports": [
                            {
                                "id": "REP_001",
                                "jobId": "JOB_REACH_001",
                                "downloadUrl": "https://youtubereporting.googleapis.com/v1/media/REP_001",
                                "startTime": "2024-01-01T00:00:00Z",
                                "endTime": "2024-01-02T00:00:00Z",
                                "createTime": "2024-01-02T05:00:00Z",
                            }
                        ]
                    },
                )
            if request.method == "GET" and "media/REP_001" in url_str:
                csv_content = (
                    "date,channel_id,video_id,live_or_on_demand,video_thumbnail_impressions,video_thumbnail_impressions_ctr\n"
                    "20240101,UC_123,VID_99,on_demand,15000,0.065\n"
                    "20240101,UC_123,VID_100,on_demand,8500,\n"
                )
                return httpx.Response(200, text=csv_content)

            return httpx.Response(404)

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        yt_reporting = YouTubeReportingClient(http_client=client)

        types = await yt_reporting.list_report_types(access_token="tok")
        assert len(types) == 1
        assert types[0]["id"] == "channel_reach_basic_a1"

        job = await yt_reporting.create_job(
            access_token="tok", report_type_id="channel_reach_basic_a1"
        )
        assert job.job_id == "JOB_REACH_001"

        reports = await yt_reporting.list_reports(access_token="tok", job_id="JOB_REACH_001")
        assert len(reports) == 1
        assert (
            reports[0].download_url == "https://youtubereporting.googleapis.com/v1/media/REP_001"
        )

        rows = await yt_reporting.download_report_csv(
            access_token="tok", download_url=reports[0].download_url
        )
        assert len(rows) == 2
        assert rows[0].date == date(2024, 1, 1)
        assert rows[0].video_id == "VID_99"
        assert rows[0].video_thumbnail_impressions == 15000
        assert rows[0].video_thumbnail_impressions_ctr == 0.065

        assert rows[1].video_id == "VID_100"
        assert rows[1].video_thumbnail_impressions_ctr is None

    asyncio.run(_run())


def test_reporting_client_download_ssrf_and_url_validation() -> None:
    async def _run() -> None:
        client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200)))
        yt_reporting = YouTubeReportingClient(http_client=client)

        # Prohibit non-HTTPS schemes
        with pytest.raises(InvalidQueryError, match="must use HTTPS"):
            await yt_reporting.download_report_csv(
                access_token="tok", download_url="http://youtubereporting.googleapis.com/report.csv"
            )

        # Prohibit direct IP addresses (SSRF protection against metadata/internal services)
        with pytest.raises(InvalidQueryError, match="Direct IP addresses are prohibited"):
            await yt_reporting.download_report_csv(
                access_token="tok", download_url="https://169.254.169.254/latest/meta-data"
            )

        with pytest.raises(InvalidQueryError, match="Direct IP addresses are prohibited"):
            await yt_reporting.download_report_csv(
                access_token="tok", download_url="https://127.0.0.1:5432/miconte_db"
            )

        # Prohibit localhost
        with pytest.raises(InvalidQueryError, match="Local and internal hostnames"):
            await yt_reporting.download_report_csv(
                access_token="tok", download_url="https://localhost/report.csv"
            )

        # Prohibit unauthorized third-party domains (Credential exfiltration protection)
        with pytest.raises(InvalidQueryError, match="not an authorized Google reporting domain"):
            await yt_reporting.download_report_csv(
                access_token="tok", download_url="https://attacker.evil.com/fake_report.csv"
            )

        # Prohibit non-standard ports
        with pytest.raises(InvalidQueryError, match="Non-standard port"):
            await yt_reporting.download_report_csv(
                access_token="tok",
                download_url="https://youtubereporting.googleapis.com:8443/report.csv",
            )

    asyncio.run(_run())


def test_reporting_client_download_size_cap_and_corrupt_csv() -> None:
    async def _run() -> None:
        # Mock huge payload exceeding 50 MB
        def large_handler(_req: httpx.Request) -> httpx.Response:
            large_content = b"x" * (51 * 1024 * 1024)
            return httpx.Response(200, content=large_content)

        client_large = httpx.AsyncClient(transport=httpx.MockTransport(large_handler))
        yt_large = YouTubeReportingClient(http_client=client_large)

        with pytest.raises(InvalidQueryError, match="exceeds maximum allowed size"):
            await yt_large.download_report_csv(
                access_token="tok",
                download_url="https://youtubereporting.googleapis.com/huge.csv",
            )

        # Mock CSV missing expected headers
        def invalid_csv_handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="col1,col2\nval1,val2\n")

        client_invalid = httpx.AsyncClient(transport=httpx.MockTransport(invalid_csv_handler))
        yt_invalid = YouTubeReportingClient(http_client=client_invalid)

        with pytest.raises(InvalidQueryError, match="missing expected reach report columns"):
            await yt_invalid.download_report_csv(
                access_token="tok",
                download_url="https://youtubereporting.googleapis.com/invalid.csv",
            )

    asyncio.run(_run())
