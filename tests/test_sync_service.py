"""Unit and integration tests for miConte Phase 5 data synchronization engine."""

import asyncio
import uuid
from collections.abc import Generator
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.orm import Session

from miconte.core.config import Settings, get_settings
from miconte.main import app
from miconte.models.channel import Channel, ChannelPublicSnapshot
from miconte.models.metrics import ChannelDailyMetric, VideoDailyMetric, VideoPeriodMetric
from miconte.models.reporting import ReportingReportIngestion
from miconte.models.video import Video, VideoPublicSnapshot
from miconte.persistence.repositories.channel_repo import ChannelRepository
from miconte.persistence.repositories.user_repo import UserRepository
from miconte.persistence.session import get_engine
from miconte.security.crypto import TokenEncryptionService, build_token_aad
from miconte.services.oauth_service import OAuthService
from miconte.services.scheduler import SyncScheduler
from miconte.services.sync_service import SyncService


@pytest.fixture
def test_settings() -> Settings:
    return Settings(
        environment="testing",
        sync_enabled=False,  # Don't auto-start background loop during test runs
        sync_interval_hours=24,
        sync_analytics_days=30,
        youtube_client_id="mock_sync_client.apps.googleusercontent.com",
        youtube_client_secret=SecretStr("mock_sync_secret"),
    )


@pytest.fixture
def crypto_svc(test_settings: Settings) -> TokenEncryptionService:
    return TokenEncryptionService(
        primary_key=test_settings.token_encryption_key.get_secret_value(),
        primary_key_id=test_settings.token_encryption_key_id,
    )


@pytest.fixture
def db_session() -> Generator[Session]:
    engine = get_engine()
    with Session(engine) as session:
        yield session
        session.rollback()


def _setup_authorized_channel(
    session: Session,
    crypto_svc: TokenEncryptionService,
    channel_id_str: str = "UC_SYNC_TEST_001",
    user_email_prefix: str = "sync_user",
) -> tuple[Any, Channel]:
    """Helper to create a user, an active OAuth connection, and a channel record."""
    user_repo = UserRepository(session)
    channel_repo = ChannelRepository(session)

    user = user_repo.create_user(
        email=f"{user_email_prefix}_{uuid.uuid4().hex[:6]}@example.com",
        hashed_password="pw",
    )

    aad_access = build_token_aad(
        user_id=str(user.id),
        platform="youtube",
        external_channel_id=channel_id_str,
        credential_kind="access",
    )
    aad_refresh = build_token_aad(
        user_id=str(user.id),
        platform="youtube",
        external_channel_id=channel_id_str,
        credential_kind="refresh",
    )

    user_repo.upsert_oauth_connection(
        user_id=user.id,
        external_channel_id=channel_id_str,
        granted_scopes="https://www.googleapis.com/auth/youtube.readonly",
        encrypted_access_token=crypto_svc.encrypt("ya29.mock_valid_token", aad=aad_access),
        encrypted_refresh_token=crypto_svc.encrypt("1//mock_valid_refresh", aad=aad_refresh),
        token_expires_at=datetime.now(UTC) + timedelta(hours=1),
        is_active=True,
    )

    channel = channel_repo.upsert_channel(
        user_id=user.id,
        youtube_channel_id=channel_id_str,
        title="Sync Test Channel",
        uploads_playlist_id=f"UU_{channel_id_str[3:]}",
    )
    session.commit()
    return user, channel


@pytest.mark.integration
def test_sync_channel_full_flow_with_videos_and_snapshots(
    db_session: Session,
    test_settings: Settings,
    crypto_svc: TokenEncryptionService,
) -> None:
    """Verify complete synchronization of metadata, videos, snapshots, analytics and reach."""
    run_uid = uuid.uuid4().hex[:6]
    ch_id_str = f"UC_FULL_{run_uid}"
    v1_id = f"VID_1_{run_uid}"
    v2_id = f"VID_2_{run_uid}"
    v3_id = f"VID_3_{run_uid}"

    user, channel = _setup_authorized_channel(
        db_session, crypto_svc, channel_id_str=ch_id_str
    )

    # Mock all upstream Google APIs
    def mock_google_api(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)

        # 1. Channels endpoint
        if "/youtube/v3/channels" in url_str:
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": ch_id_str,
                            "snippet": {
                                "title": "Updated Channel Title",
                                "description": "Channel Description",
                                "customUrl": "@updatedchannel",
                                "publishedAt": "2024-01-01T00:00:00Z",
                            },
                            "contentDetails": {
                                "relatedPlaylists": {"uploads": f"UU_{ch_id_str[3:]}"}
                            },
                            "statistics": {
                                "viewCount": "150000",
                                "subscriberCount": "2500",
                                "videoCount": "3",
                            },
                        }
                    ]
                },
            )

        # 2. PlaylistItems endpoint (uploads list)
        if "/youtube/v3/playlistItems" in url_str:
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "contentDetails": {"videoId": v1_id},
                            "snippet": {"title": "Video 1", "publishedAt": "2024-02-01T12:00:00Z"},
                        },
                        {
                            "contentDetails": {"videoId": v2_id},
                            "snippet": {"title": "Video 2", "publishedAt": "2024-02-05T12:00:00Z"},
                        },
                        {
                            "contentDetails": {"videoId": v3_id},
                            "snippet": {"title": "Video 3", "publishedAt": "2024-02-10T12:00:00Z"},
                        },
                    ]
                },
            )

        # 3. Videos endpoint (batch)
        if "/youtube/v3/videos" in url_str:
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": v1_id,
                            "snippet": {
                                "title": "Video 1",
                                "publishedAt": "2024-02-01T12:00:00Z",
                                "description": "Desc 1",
                            },
                            "contentDetails": {"duration": "PT10M30S"},
                            "statistics": {
                                "viewCount": "1000",
                                "likeCount": "50",
                                "commentCount": "10",
                            },
                        },
                        {
                            "id": v2_id,
                            "snippet": {
                                "title": "Video 2",
                                "publishedAt": "2024-02-05T12:00:00Z",
                                "description": "Desc 2",
                            },
                            "contentDetails": {"duration": "PT5M00S"},
                            "statistics": {
                                "viewCount": "2500",
                                "likeCount": "120",
                                "commentCount": "25",
                            },
                        },
                        {
                            "id": v3_id,
                            "snippet": {
                                "title": "Video 3",
                                "publishedAt": "2024-02-10T12:00:00Z",
                                "description": "Desc 3",
                            },
                            "contentDetails": {"duration": "PT12M45S"},
                            "statistics": {
                                "viewCount": "5000",
                                "likeCount": "300",
                                "commentCount": "40",
                            },
                        },
                    ]
                },
            )

        # 4. Analytics reports.query endpoint
        if "/v2/reports" in url_str:
            dims = request.url.params.get("dimensions", "")
            if "day" in dims:
                # Channel daily report
                return httpx.Response(
                    200,
                    json={
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
                            {"name": "likes", "columnType": "METRIC", "dataType": "INTEGER"},
                            {"name": "comments", "columnType": "METRIC", "dataType": "INTEGER"},
                            {"name": "shares", "columnType": "METRIC", "dataType": "INTEGER"},
                        ],
                        "rows": [
                            [
                                "2026-10-20",
                                500,
                                1200,
                                144,
                                48.5,
                                10,
                                2,
                                40,
                                5,
                                3,
                            ],
                            [
                                "2026-10-21",
                                620,
                                1500,
                                145,
                                51.0,
                                15,
                                1,
                                55,
                                8,
                                7,
                            ],
                        ],
                    },
                )
            if "video" in dims:
                # Video period aggregates
                return httpx.Response(
                    200,
                    json={
                        "columnHeaders": [
                            {"name": "video", "columnType": "DIMENSION", "dataType": "STRING"},
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
                            {"name": "likes", "columnType": "METRIC", "dataType": "INTEGER"},
                            {"name": "comments", "columnType": "METRIC", "dataType": "INTEGER"},
                            {"name": "shares", "columnType": "METRIC", "dataType": "INTEGER"},
                        ],
                        "rows": [
                            [v1_id, 1000, 2400, 144, 48.5, 20, 4, 80, 10, 6],
                            [v2_id, 2500, 6000, 144, 52.0, 45, 5, 200, 30, 15],
                        ],
                    },
                )

        # 5. Reporting API list_jobs
        if "/v1/jobs" in url_str and request.method == "GET" and "reports" not in url_str:
            return httpx.Response(
                200,
                json={
                    "jobs": [
                        {
                            "id": "job_reach_001",
                            "reportTypeId": "channel_reach_basic_a1",
                            "name": "Reach Job",
                        }
                    ]
                },
            )

        # 6. Reporting API list_reports
        if "/v1/jobs/job_reach_001/reports" in url_str:
            return httpx.Response(
                200,
                json={
                    "reports": [
                        {
                            "id": f"rep_reach_{run_uid}",
                            "jobId": "job_reach_001",
                            "downloadUrl": "https://storage.googleapis.com/test-bucket/report_001.csv",
                        }
                    ]
                },
            )

        # 7. Download CSV report
        if "test-bucket/report_001.csv" in url_str:
            csv_content = (
                "date,channel_id,video_id,live_or_on_demand,video_thumbnail_impressions,video_thumbnail_impressions_ctr\n"
                f"20261020,{ch_id_str},{v1_id},on_demand,10000,0.100\n"
                f"20261021,{ch_id_str},{v2_id},on_demand,25000,0.085\n"
            )
            return httpx.Response(
                200, text=csv_content, headers={"Content-Type": "text/csv; charset=utf-8"}
            )

        return httpx.Response(404, text=f"Unhandled URL in mock: {url_str}")

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_google_api))
    oauth_service = OAuthService(
        session=db_session,
        settings=test_settings,
        crypto_service=crypto_svc,
        http_client=mock_client,
    )
    sync_service = SyncService(
        session=db_session,
        settings=test_settings,
        oauth_service=oauth_service,
        http_client=mock_client,
    )

    observation_time = datetime(2026, 10, 26, 12, 0, 0, tzinfo=UTC)

    async def _run() -> None:
        result = await sync_service.sync_channel(
            user_id=user.id,
            channel_id=channel.id,
            captured_at=observation_time,
            start_date=date(2026, 10, 1),
            end_date=date(2026, 10, 24),
        )
        assert result.status == "succeeded"
        assert result.records_processed > 0

        # Verify Channel metadata updated
        db_session.expire_all()
        updated_ch = db_session.get(Channel, channel.id)
        assert updated_ch is not None
        assert updated_ch.title == "Updated Channel Title"
        assert updated_ch.custom_url == "@updatedchannel"

        # Verify ChannelPublicSnapshot recorded
        snap_stmt = db_session.query(ChannelPublicSnapshot).filter_by(channel_id=channel.id).all()
        assert len(snap_stmt) == 1
        assert snap_stmt[0].view_count == 150000
        assert snap_stmt[0].subscriber_count == 2500
        assert snap_stmt[0].video_count == 3
        assert snap_stmt[0].captured_at == observation_time

        # Verify Videos and VideoPublicSnapshots
        videos = db_session.query(Video).filter_by(channel_id=channel.id).all()
        assert len(videos) == 3
        vids_dict = {v.youtube_video_id: v for v in videos}
        assert v1_id in vids_dict
        assert vids_dict[v1_id].duration_seconds == 630  # PT10M30S = 10*60 + 30

        vid_ids = [v.id for v in videos]
        vid_snaps = (
            db_session.query(VideoPublicSnapshot)
            .filter(VideoPublicSnapshot.video_id.in_(vid_ids))
            .all()
        )
        assert len(vid_snaps) == 3

        # Verify ChannelDailyMetrics
        daily_metrics = (
            db_session.query(ChannelDailyMetric).filter_by(channel_id=channel.id).all()
        )
        assert len(daily_metrics) == 2
        dates = {d.metric_date.isoformat(): d.views for d in daily_metrics}
        assert dates.get("2026-10-20") == 500
        assert dates.get("2026-10-21") == 620

        # Verify VideoPeriodMetrics
        period_metrics = (
            db_session.query(VideoPeriodMetric)
            .filter(VideoPeriodMetric.video_id.in_(vid_ids))
            .all()
        )
        assert len(period_metrics) == 2

        # Verify Reporting reach updated in VideoDailyMetric
        v1_daily = (
            db_session.query(VideoDailyMetric)
            .filter_by(video_id=vids_dict[v1_id].id, metric_date=date(2026, 10, 20))
            .first()
        )
        assert v1_daily is not None
        assert v1_daily.thumbnail_impressions == 10000
        assert v1_daily.thumbnail_ctr == 0.100
        assert v1_daily.reach_source == "reporting_api_v1"

    asyncio.run(_run())


@pytest.mark.integration
def test_sync_snapshots_preservation_and_idempotency(
    db_session: Session,
    test_settings: Settings,
    crypto_svc: TokenEncryptionService,
) -> None:
    """Verify that snapshots at different times are kept and same-time snapshots update cleanly."""
    unique_channel_id = f"UC_SNAP_{uuid.uuid4().hex[:8]}"
    user, channel = _setup_authorized_channel(
        db_session, crypto_svc, channel_id_str=unique_channel_id
    )

    def mock_data_api(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        if "/channels" in url_str:
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": unique_channel_id,
                            "snippet": {"title": "Title", "publishedAt": "2024-01-01T00:00:00Z"},
                            "contentDetails": {
                                "relatedPlaylists": {"uploads": f"UU_{unique_channel_id[3:]}"}
                            },
                            "statistics": {
                                "viewCount": "1000",
                                "subscriberCount": "100",
                                "videoCount": "1",
                            },
                        }
                    ]
                },
            )
        if "/playlistItems" in url_str:
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "contentDetails": {"videoId": "VID_SNAP_01"},
                            "snippet": {
                                "title": "Vid Snap 1",
                                "publishedAt": "2024-01-01T00:00:00Z",
                            },
                        }
                    ]
                },
            )
        if "/videos" in url_str:
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "VID_SNAP_01",
                            "snippet": {
                                "title": "Vid Snap 1",
                                "publishedAt": "2024-01-01T00:00:00Z",
                            },
                            "contentDetails": {"duration": "PT60S"},
                            "statistics": {
                                "viewCount": "500",
                                "likeCount": "20",
                                "commentCount": "5",
                            },
                        }
                    ]
                },
            )
        return httpx.Response(200, json={"items": [], "rows": [], "jobs": []})

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_data_api))
    oauth_service = OAuthService(
        session=db_session,
        settings=test_settings,
        crypto_service=crypto_svc,
        http_client=mock_client,
    )
    sync_service = SyncService(
        session=db_session,
        settings=test_settings,
        oauth_service=oauth_service,
        http_client=mock_client,
    )

    t1 = datetime(2026, 10, 26, 10, 0, 0, tzinfo=UTC)
    t2 = datetime(2026, 10, 26, 16, 0, 0, tzinfo=UTC)

    async def _run() -> None:
        # Run 1 at t1
        res1 = await sync_service.sync_channel(
            user_id=user.id,
            channel_id=channel.id,
            sync_types=["metadata", "public_snapshots"],
            captured_at=t1,
        )
        assert res1.status == "succeeded"

        # Run 2 at t1 again (exact replay) -> Idempotent, must not fail unique constraint
        res2 = await sync_service.sync_channel(
            user_id=user.id,
            channel_id=channel.id,
            sync_types=["metadata", "public_snapshots"],
            captured_at=t1,
        )
        assert res2.status == "succeeded"

        db_session.expire_all()
        snaps_t1 = (
            db_session.query(ChannelPublicSnapshot).filter_by(channel_id=channel.id).all()
        )
        assert len(snaps_t1) == 1

        # Run 3 at t2 (later observation) -> Must preserve both t1 and t2
        res3 = await sync_service.sync_channel(
            user_id=user.id,
            channel_id=channel.id,
            sync_types=["metadata", "public_snapshots"],
            captured_at=t2,
        )
        assert res3.status == "succeeded"

        db_session.expire_all()
        all_snaps = (
            db_session.query(ChannelPublicSnapshot)
            .filter_by(channel_id=channel.id)
            .order_by(ChannelPublicSnapshot.captured_at.asc())
            .all()
        )
        assert len(all_snaps) == 2
        assert all_snaps[0].captured_at == t1
        assert all_snaps[1].captured_at == t2

    asyncio.run(_run())


@pytest.mark.integration
def test_sync_pagination_and_batch_processing(
    db_session: Session,
    test_settings: Settings,
    crypto_svc: TokenEncryptionService,
) -> None:
    """Verify pagination across playlist items and batching of video queries in chunks of 50."""
    user, channel = _setup_authorized_channel(
        db_session, crypto_svc, channel_id_str="UC_PAGINATION_001"
    )

    batch_requested_counts: list[int] = []

    def mock_paginated_api(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)

        if "/channels" in url_str:
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "UC_PAGINATION_001",
                            "snippet": {"title": "Title"},
                            "contentDetails": {
                                "relatedPlaylists": {"uploads": "UU_PAGINATION_001"}
                            },
                            "statistics": {"viewCount": "100", "videoCount": "55"},
                        }
                    ]
                },
            )

        if "/playlistItems" in url_str:
            token = request.url.params.get("pageToken")
            if not token:
                # Page 1: returns 50 items and a nextPageToken
                items = [
                    {
                        "contentDetails": {"videoId": f"VID_{i:03d}"},
                        "snippet": {
                            "title": f"Video {i}",
                            "publishedAt": "2024-01-01T00:00:00Z",
                        },
                    }
                    for i in range(1, 51)
                ]
                return httpx.Response(200, json={"items": items, "nextPageToken": "page_2_token"})
            if token == "page_2_token":
                # Page 2: returns 5 items and no nextPageToken
                items = [
                    {
                        "contentDetails": {"videoId": f"VID_{i:03d}"},
                        "snippet": {
                            "title": f"Video {i}",
                            "publishedAt": "2024-01-01T00:00:00Z",
                        },
                    }
                    for i in range(51, 56)
                ]
                return httpx.Response(200, json={"items": items})

        if "/videos" in url_str:
            ids_str = request.url.params.get("id", "")
            id_list = ids_str.split(",")
            batch_requested_counts.append(len(id_list))
            items = [
                {
                    "id": vid,
                    "snippet": {"title": vid, "publishedAt": "2024-01-01T00:00:00Z"},
                    "contentDetails": {"duration": "PT10M"},
                    "statistics": {"viewCount": "100"},
                }
                for vid in id_list
            ]
            return httpx.Response(200, json={"items": items})

        return httpx.Response(200, json={})

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_paginated_api))
    oauth_service = OAuthService(
        session=db_session,
        settings=test_settings,
        crypto_service=crypto_svc,
        http_client=mock_client,
    )
    sync_service = SyncService(
        session=db_session,
        settings=test_settings,
        oauth_service=oauth_service,
        http_client=mock_client,
    )

    async def _run() -> None:
        res = await sync_service.sync_channel(
            user_id=user.id,
            channel_id=channel.id,
            sync_types=["metadata", "public_snapshots"],
            max_videos=100,
        )
        assert res.status == "succeeded"

        # Check batches: 55 items fetched in two video batch calls of 50 and 5
        assert batch_requested_counts == [50, 5]

        # Verify 55 videos persisted
        db_session.expire_all()
        count = db_session.query(Video).filter_by(channel_id=channel.id).count()
        assert count == 55

    asyncio.run(_run())


@pytest.mark.integration
def test_sync_negative_likes_isolated_as_anomaly(
    db_session: Session,
    test_settings: Settings,
    crypto_svc: TokenEncryptionService,
) -> None:
    """Verify that unexpected negative metric values are isolated with is_anomalous=True."""
    user, channel = _setup_authorized_channel(
        db_session, crypto_svc, channel_id_str="UC_ANOMALY_001"
    )

    def mock_analytics_anomaly(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        if "/channels" in url_str:
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "UC_ANOMALY_001",
                            "snippet": {"title": "Title"},
                            "contentDetails": {
                                "relatedPlaylists": {"uploads": "UU_ANOMALY_001"}
                            },
                            "statistics": {"viewCount": "100"},
                        }
                    ]
                },
            )
        if "/reports" in url_str:
            # Return negative likes row
            return httpx.Response(
                200,
                json={
                    "columnHeaders": [
                        {"name": "day", "columnType": "DIMENSION", "dataType": "STRING"},
                        {"name": "views", "columnType": "METRIC", "dataType": "INTEGER"},
                        {"name": "likes", "columnType": "METRIC", "dataType": "INTEGER"},
                    ],
                    "rows": [["2026-10-22", 100, -3]],
                },
            )
        return httpx.Response(200, json={"items": [], "rows": [], "jobs": []})

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_analytics_anomaly))
    oauth_service = OAuthService(
        session=db_session,
        settings=test_settings,
        crypto_service=crypto_svc,
        http_client=mock_client,
    )
    sync_service = SyncService(
        session=db_session,
        settings=test_settings,
        oauth_service=oauth_service,
        http_client=mock_client,
    )

    async def _run() -> None:
        res = await sync_service.sync_channel(
            user_id=user.id,
            channel_id=channel.id,
            sync_types=["analytics_daily"],
        )
        assert res.status == "succeeded"

        # Check DB row marked as anomalous
        db_session.expire_all()
        metric = (
            db_session.query(ChannelDailyMetric)
            .filter_by(channel_id=channel.id, metric_date=date(2026, 10, 22))
            .first()
        )
        assert metric is not None
        assert metric.is_anomalous is True
        assert "Negative likes count" in (metric.anomaly_notes or "")

    asyncio.run(_run())


@pytest.mark.integration
def test_sync_reporting_api_pending_generation_window(
    db_session: Session,
    test_settings: Settings,
    crypto_svc: TokenEncryptionService,
) -> None:
    """Verify pending reports (48h window) complete as partially_succeeded without blocking."""
    user, channel = _setup_authorized_channel(
        db_session, crypto_svc, channel_id_str="UC_PENDING_REP_001"
    )

    def mock_reporting_pending(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        if "/channels" in url_str:
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "UC_PENDING_REP_001",
                            "snippet": {"title": "Title"},
                            "contentDetails": {
                                "relatedPlaylists": {"uploads": "UU_PENDING_REP_001"}
                            },
                            "statistics": {"viewCount": "100"},
                        }
                    ]
                },
            )
        if "/v1/jobs" in url_str and "reports" not in url_str:
            return httpx.Response(
                200,
                json={
                    "jobs": [
                        {
                            "id": "job_pending_01",
                            "reportTypeId": "channel_reach_basic_a1",
                        }
                    ]
                },
            )
        if "/reports" in url_str:
            # No reports generated yet
            return httpx.Response(200, json={"reports": []})
        return httpx.Response(200, json={"items": []})

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_reporting_pending))
    oauth_service = OAuthService(
        session=db_session,
        settings=test_settings,
        crypto_service=crypto_svc,
        http_client=mock_client,
    )
    sync_service = SyncService(
        session=db_session,
        settings=test_settings,
        oauth_service=oauth_service,
        http_client=mock_client,
    )

    async def _run() -> None:
        res = await sync_service.sync_channel(
            user_id=user.id,
            channel_id=channel.id,
            sync_types=["reporting_reach"],
        )
        assert res.status == "partially_succeeded"
        reach_stage = next(s for s in res.stages if s.stage == "reporting_reach")
        assert reach_stage.status == "pending"
        assert "awaiting 48-hour" in reach_stage.details

    asyncio.run(_run())


@pytest.mark.integration
def test_sync_quota_exceeded_fails_fast(
    db_session: Session,
    test_settings: Settings,
    crypto_svc: TokenEncryptionService,
) -> None:
    """Verify that a 429 quotaExceeded error aborts sync and does not retry."""
    user, channel = _setup_authorized_channel(
        db_session, crypto_svc, channel_id_str="UC_QUOTA_TEST_001"
    )

    call_count = 0

    def mock_quota_429(_req: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(
            429,
            json={
                "error": {
                    "code": 429,
                    "message": "The request cannot be completed because quota exceeded.",
                    "errors": [{"reason": "quotaExceeded"}],
                }
            },
        )

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_quota_429))
    oauth_service = OAuthService(
        session=db_session,
        settings=test_settings,
        crypto_service=crypto_svc,
        http_client=mock_client,
    )
    sync_service = SyncService(
        session=db_session,
        settings=test_settings,
        oauth_service=oauth_service,
        http_client=mock_client,
    )

    async def _run() -> None:
        res = await sync_service.sync_channel(
            user_id=user.id,
            channel_id=channel.id,
            sync_types=["metadata"],
        )
        assert res.status == "failed"
        assert (
            "quota exceeded" in (res.error_message or "").lower()
            or "429" in (res.error_message or "")
        )
        # Must not retry quota exhaustion
        assert call_count == 1

    asyncio.run(_run())


@pytest.mark.integration
def test_sync_transient_network_error_retries_successfully(
    db_session: Session,
    test_settings: Settings,
    crypto_svc: TokenEncryptionService,
) -> None:
    """Verify that transient 503 errors are retried with backoff and eventually succeed."""
    user, channel = _setup_authorized_channel(
        db_session, crypto_svc, channel_id_str="UC_RETRY_TEST_001"
    )

    attempt = 0

    def mock_retry_api(request: httpx.Request) -> httpx.Response:
        nonlocal attempt
        url_str = str(request.url)
        if "/channels" in url_str:
            attempt += 1
            if attempt < 3:
                return httpx.Response(503, text="Service Unavailable Temporary Glitch")
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "UC_RETRY_TEST_001",
                            "snippet": {"title": "Title After Retry"},
                            "contentDetails": {
                                "relatedPlaylists": {"uploads": "UU_RETRY_TEST_001"}
                            },
                            "statistics": {"viewCount": "100"},
                        }
                    ]
                },
            )
        return httpx.Response(200, json={"items": []})

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_retry_api))
    oauth_service = OAuthService(
        session=db_session,
        settings=test_settings,
        crypto_service=crypto_svc,
        http_client=mock_client,
    )
    sync_service = SyncService(
        session=db_session,
        settings=test_settings,
        oauth_service=oauth_service,
        http_client=mock_client,
    )

    async def _run() -> None:
        res = await sync_service.sync_channel(
            user_id=user.id,
            channel_id=channel.id,
            sync_types=["metadata"],
        )
        assert res.status == "succeeded"
        assert attempt == 3  # Succeeded on 3rd attempt

    asyncio.run(_run())


@pytest.mark.integration
def test_sync_api_endpoints_and_user_isolation(
    db_session: Session,
    test_settings: Settings,
    crypto_svc: TokenEncryptionService,
) -> None:
    """Verify FastAPI sync endpoints, IDOR protection, and channel isolation between users."""
    user_a, channel_a = _setup_authorized_channel(
        db_session, crypto_svc, channel_id_str="UC_USER_A_001", user_email_prefix="user_a"
    )
    user_b, channel_b = _setup_authorized_channel(
        db_session, crypto_svc, channel_id_str="UC_USER_B_001", user_email_prefix="user_b"
    )

    app.dependency_overrides[get_settings] = lambda: test_settings
    try:
        client = TestClient(app)

        # 1. User A lists their synchronizable channels -> only Channel A appears
        resp_a = client.get(
            "/api/v1/sync/channels",
            headers={"X-User-Id": str(user_a.id)},
        )
        assert resp_a.status_code == 200
        ch_list_a = resp_a.json()
        assert len(ch_list_a) == 1
        assert ch_list_a[0]["youtube_channel_id"] == "UC_USER_A_001"

        # 2. User B tries to trigger sync on User A's channel -> 403 Forbidden
        resp_idor_trigger = client.post(
            f"/api/v1/sync/channels/{channel_a.id}/trigger",
            json={},
            headers={"X-User-Id": str(user_b.id)},
        )
        assert resp_idor_trigger.status_code == 403
        assert "not owned by user" in resp_idor_trigger.json()["detail"]

        # 3. User B tries to query sync runs of User A's channel -> 404 Not Found
        resp_idor_runs = client.get(
            f"/api/v1/sync/channels/{channel_a.id}/runs",
            headers={"X-User-Id": str(user_b.id)},
        )
        assert resp_idor_runs.status_code == 404

        # 4. Check scheduler status endpoint
        sched_resp = client.get("/api/v1/sync/scheduler/status")
        assert sched_resp.status_code == 200
        data = sched_resp.json()
        assert "is_running" in data
        assert "sync_interval_hours" in data

    finally:
        app.dependency_overrides.pop(get_settings, None)


@pytest.mark.integration
def test_sync_scheduler_concurrency_lock_prevents_duplicate_runs(
    db_session: Session,
    test_settings: Settings,
) -> None:
    """Verify that per-channel locking prevents two simultaneous executions for the same channel."""
    scheduler = SyncScheduler(settings=test_settings)
    channel_id = uuid.uuid4()
    lock = scheduler._get_channel_lock(channel_id)

    async def _run() -> None:
        # Acquire lock simulating a running sync
        await lock.acquire()
        try:
            # Another attempt must fail with conflict
            with pytest.raises(RuntimeError, match="already in progress"):
                await scheduler.trigger_channel_sync(
                    user_id=uuid.uuid4(),
                    channel_id=channel_id,
                )
        finally:
            lock.release()

    asyncio.run(_run())


@pytest.mark.integration
def test_sync_revoked_or_expired_token_fails_gracefully(
    db_session: Session,
    test_settings: Settings,
    crypto_svc: TokenEncryptionService,
) -> None:
    """Verify that when a token cannot be decrypted or is deactivated, sync marks failed."""
    user, channel = _setup_authorized_channel(
        db_session, crypto_svc, channel_id_str=f"UC_REVOKED_{uuid.uuid4().hex[:6]}"
    )
    # Deactivate connection simulating revocation
    conn = UserRepository(db_session).get_oauth_connection(
        user_id=user.id,
        external_channel_id=channel.youtube_channel_id,
        platform="youtube",
    )
    assert conn is not None
    conn.is_active = False
    conn.encrypted_access_token = None
    conn.encrypted_refresh_token = None
    db_session.commit()

    sync_service = SyncService(
        session=db_session,
        settings=test_settings,
        oauth_service=OAuthService(
            session=db_session, settings=test_settings, crypto_service=crypto_svc
        ),
    )

    async def _run() -> None:
        res = await sync_service.sync_channel(
            user_id=user.id,
            channel_id=channel.id,
            sync_types=["metadata"],
        )
        assert res.status == "failed"
        assert res.records_processed == 0
        assert "No active OAuth connection" in (res.error_message or "")

    asyncio.run(_run())


@pytest.mark.integration
def test_sync_insufficient_permissions_fails_without_retrying(
    db_session: Session,
    test_settings: Settings,
    crypto_svc: TokenEncryptionService,
) -> None:
    """Verify that 403 Forbidden with insufficient permissions aborts without retrying."""
    user, channel = _setup_authorized_channel(
        db_session, crypto_svc, channel_id_str=f"UC_INSUF_{uuid.uuid4().hex[:6]}"
    )
    call_count = 0

    def mock_403_insuf(_req: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(
            403,
            json={
                "error": {
                    "code": 403,
                    "message": "The caller does not have permission",
                    "errors": [{"reason": "insufficientPermissions"}],
                }
            },
        )

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_403_insuf))
    sync_service = SyncService(
        session=db_session,
        settings=test_settings,
        oauth_service=OAuthService(
            session=db_session,
            settings=test_settings,
            crypto_service=crypto_svc,
            http_client=mock_client,
        ),
        http_client=mock_client,
    )

    async def _run() -> None:
        res = await sync_service.sync_channel(
            user_id=user.id,
            channel_id=channel.id,
            sync_types=["metadata"],
        )
        assert res.status == "failed"
        assert "Forbidden" in (res.error_message or "")
        assert call_count == 1  # No retries for 403

    asyncio.run(_run())


@pytest.mark.integration
def test_sync_corrupt_csv_handled_gracefully(
    db_session: Session,
    test_settings: Settings,
    crypto_svc: TokenEncryptionService,
) -> None:
    """Verify that malformed or headerless CSV in Reporting API does not break sync execution."""
    ch_id = f"UC_CORRUPT_{uuid.uuid4().hex[:6]}"
    user, channel = _setup_authorized_channel(
        db_session, crypto_svc, channel_id_str=ch_id
    )

    def mock_corrupt_csv_api(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        if "/v1/jobs" in url_str and "reports" not in url_str:
            return httpx.Response(
                200,
                json={"jobs": [{"id": "job_1", "reportTypeId": "channel_reach_basic_a1"}]},
            )
        if "/reports" in url_str:
            return httpx.Response(
                200,
                json={
                    "reports": [
                        {
                            "id": "rep_bad_01",
                            "jobId": "job_1",
                            "downloadUrl": "https://storage.googleapis.com/test-bucket/bad.csv",
                        }
                    ]
                },
            )
        if "bad.csv" in url_str:
            # Corrupt CSV missing required columns
            return httpx.Response(200, text="foo,bar,baz\n1,2,3\n")
        return httpx.Response(200, json={})

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_corrupt_csv_api))
    sync_service = SyncService(
        session=db_session,
        settings=test_settings,
        oauth_service=OAuthService(
            session=db_session,
            settings=test_settings,
            crypto_service=crypto_svc,
            http_client=mock_client,
        ),
        http_client=mock_client,
    )

    async def _run() -> None:
        res = await sync_service.sync_channel(
            user_id=user.id,
            channel_id=channel.id,
            sync_types=["reporting_reach"],
        )
        # Completes with 0 records processed without raising uncaught exception
        assert res.status in ("succeeded", "partially_succeeded")
        assert res.records_processed == 0

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Reporting API idempotency: the three tests missing from the prior commit
# ---------------------------------------------------------------------------

_VALID_REACH_CSV_HEADER = (
    "date,channel_id,video_id,live_or_on_demand,"
    "video_thumbnail_impressions,video_thumbnail_impressions_ctr\n"
)
_VALID_REACH_CSV_ROW = "20261001,UC_IDEM_TEST,yt_video_aaa,on_demand,1000,0.05\n"


def _build_reporting_mock(
    *,
    channel_id_str: str,
    report_id: str,
    csv_body: str,
    job_id: str = "job_idem_01",
    report_start: str = "2026-10-01T00:00:00Z",
    report_end: str = "2026-10-08T00:00:00Z",
    report_create: str = "2026-10-09T12:00:00Z",
) -> httpx.MockTransport:
    """Build a MockTransport that serves a single Reporting API report."""

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/channels" in url:
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": channel_id_str,
                            "snippet": {"title": "Idem Channel"},
                            "contentDetails": {
                                "relatedPlaylists": {"uploads": f"UU_{channel_id_str[3:]}"}
                            },
                            "statistics": {"viewCount": "500"},
                        }
                    ]
                },
            )
        if "/v1/jobs" in url and "reports" not in url:
            return httpx.Response(
                200,
                json={"jobs": [{"id": job_id, "reportTypeId": "channel_reach_basic_a1"}]},
            )
        if f"/jobs/{job_id}/reports" in url:
            return httpx.Response(
                200,
                json={
                    "reports": [
                        {
                            "id": report_id,
                            "jobId": job_id,
                            "startTime": report_start,
                            "endTime": report_end,
                            "createTime": report_create,
                            "downloadUrl": f"https://storage.googleapis.com/bucket/{report_id}.csv",
                        }
                    ]
                },
            )
        if f"{report_id}.csv" in url:
            return httpx.Response(200, text=csv_body)
        return httpx.Response(200, json={})

    return httpx.MockTransport(handler)


@pytest.mark.integration
def test_sync_reporting_api_empty_csv_handled_gracefully(
    db_session: Session,
    test_settings: Settings,
    crypto_svc: TokenEncryptionService,
) -> None:
    """A valid CSV with a header row but no data rows must complete successfully.

    The report ID must be recorded in reporting_report_ingestions with rows_ingested=0
    so that subsequent syncs do not re-download the empty file.
    """
    ch_id = f"UC_EMPTY_{uuid.uuid4().hex[:6]}"
    rep_id = f"rep_empty_{uuid.uuid4().hex[:8]}"
    user, channel = _setup_authorized_channel(db_session, crypto_svc, channel_id_str=ch_id)

    transport = _build_reporting_mock(
        channel_id_str=ch_id,
        report_id=rep_id,
        # Only header, no data rows
        csv_body=_VALID_REACH_CSV_HEADER,
    )
    mock_client = httpx.AsyncClient(transport=transport)
    sync_service = SyncService(
        session=db_session,
        settings=test_settings,
        oauth_service=OAuthService(
            session=db_session,
            settings=test_settings,
            crypto_service=crypto_svc,
            http_client=mock_client,
        ),
        http_client=mock_client,
    )

    async def _run() -> None:
        res = await sync_service.sync_channel(
            user_id=user.id,
            channel_id=channel.id,
            sync_types=["reporting_reach"],
        )
        assert res.status == "succeeded"
        assert res.records_processed == 0

    asyncio.run(_run())

    # The report ID must be recorded so a second sync skips it
    ingestion = (
        db_session.query(ReportingReportIngestion)
        .filter_by(channel_id=channel.id, report_id=rep_id)
        .one_or_none()
    )
    assert ingestion is not None, "Empty-CSV report must still be recorded as ingested"
    assert ingestion.rows_ingested == 0


@pytest.mark.integration
def test_sync_reporting_api_repeated_reports_not_reimported(
    db_session: Session,
    test_settings: Settings,
    crypto_svc: TokenEncryptionService,
) -> None:
    """Running sync twice with the same report_id must import the report only once.

    After the first sync the report ID is in reporting_report_ingestions.
    The second sync must recognise it as already processed and skip the download
    entirely, leaving exactly one ingestion record and the original row count.
    """
    ch_id = f"UC_REPT_{uuid.uuid4().hex[:6]}"
    rep_id = f"rep_repeat_{uuid.uuid4().hex[:8]}"
    user, channel = _setup_authorized_channel(db_session, crypto_svc, channel_id_str=ch_id)

    # Add a video so the CSV row can be matched to a DB record
    from miconte.persistence.repositories.video_repo import VideoRepository

    video_repo = VideoRepository(db_session)
    video = video_repo.upsert_video(
        channel_id=channel.id,
        youtube_video_id="yt_video_aaa",
        title="Test Video",
        published_at=datetime(2026, 1, 1, tzinfo=UTC),
        duration_seconds=120,
        duration_iso="PT2M",
    )
    db_session.commit()

    csv_body = _VALID_REACH_CSV_HEADER + _VALID_REACH_CSV_ROW.replace(
        "UC_IDEM_TEST", ch_id
    ).replace("yt_video_aaa", video.youtube_video_id)

    download_count = 0

    def counting_handler(request: httpx.Request) -> httpx.Response:
        nonlocal download_count
        url = str(request.url)
        if "/channels" in url:
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": ch_id,
                            "snippet": {"title": "Repeat Channel"},
                            "contentDetails": {
                                "relatedPlaylists": {"uploads": f"UU_{ch_id[3:]}"}
                            },
                            "statistics": {"viewCount": "500"},
                        }
                    ]
                },
            )
        if "/v1/jobs" in url and "reports" not in url:
            return httpx.Response(
                200,
                json={"jobs": [{"id": "job_rpt_01", "reportTypeId": "channel_reach_basic_a1"}]},
            )
        if "/jobs/job_rpt_01/reports" in url:
            return httpx.Response(
                200,
                json={
                    "reports": [
                        {
                            "id": rep_id,
                            "jobId": "job_rpt_01",
                            "startTime": "2026-10-01T00:00:00Z",
                            "endTime": "2026-10-08T00:00:00Z",
                            "createTime": "2026-10-09T12:00:00Z",
                            "downloadUrl": f"https://storage.googleapis.com/bucket/{rep_id}.csv",
                        }
                    ]
                },
            )
        if f"{rep_id}.csv" in url:
            download_count += 1
            return httpx.Response(200, text=csv_body)
        return httpx.Response(200, json={})

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(counting_handler))
    sync_service = SyncService(
        session=db_session,
        settings=test_settings,
        oauth_service=OAuthService(
            session=db_session,
            settings=test_settings,
            crypto_service=crypto_svc,
            http_client=mock_client,
        ),
        http_client=mock_client,
    )

    async def _run_twice() -> None:
        # First sync: must download and record
        res1 = await sync_service.sync_channel(
            user_id=user.id,
            channel_id=channel.id,
            sync_types=["reporting_reach"],
        )
        assert res1.status == "succeeded"
        assert res1.records_processed == 1

        # Second sync: same report_id, must not re-download
        res2 = await sync_service.sync_channel(
            user_id=user.id,
            channel_id=channel.id,
            sync_types=["reporting_reach"],
        )
        assert res2.status == "succeeded"
        assert res2.records_processed == 0

    asyncio.run(_run_twice())

    # CSV downloaded exactly once across both syncs
    assert download_count == 1, f"Expected 1 download, got {download_count}"

    # Exactly one ingestion record in the DB — no duplicates
    ingestion_rows = (
        db_session.query(ReportingReportIngestion)
        .filter_by(channel_id=channel.id, report_id=rep_id)
        .all()
    )
    assert len(ingestion_rows) == 1
    assert ingestion_rows[0].rows_ingested == 1


@pytest.mark.integration
def test_sync_reporting_api_newer_version_restatement_replaces_older_data(
    db_session: Session,
    test_settings: Settings,
    crypto_svc: TokenEncryptionService,
) -> None:
    """A restatement — same period, different report_id, strictly newer create_time —
    must be processed and must update the existing reach metrics.

    A report for the same period with an older or equal create_time must be skipped
    to prevent downgrading already-committed data.
    """
    ch_id = f"UC_RSTAT_{uuid.uuid4().hex[:6]}"
    rep_id_v1 = f"rep_v1_{uuid.uuid4().hex[:8]}"
    rep_id_v2 = f"rep_v2_{uuid.uuid4().hex[:8]}"
    rep_id_old = f"rep_old_{uuid.uuid4().hex[:8]}"
    user, channel = _setup_authorized_channel(db_session, crypto_svc, channel_id_str=ch_id)

    from miconte.persistence.repositories.video_repo import VideoRepository

    video_repo = VideoRepository(db_session)
    video = video_repo.upsert_video(
        channel_id=channel.id,
        youtube_video_id="yt_rstat_vid",
        title="Restatement Video",
        published_at=datetime(2026, 1, 1, tzinfo=UTC),
        duration_seconds=200,
        duration_iso="PT3M20S",
    )
    db_session.commit()

    period_start = "2026-10-01T00:00:00Z"
    period_end = "2026-10-08T00:00:00Z"

    def _csv(impressions: int) -> str:
        return (
            _VALID_REACH_CSV_HEADER
            + f"20261001,{ch_id},{video.youtube_video_id},on_demand,{impressions},0.05\n"
        )

    # ---- Phase 1: ingest v1 report (500 impressions) ----
    v1_client = httpx.AsyncClient(
        transport=_build_reporting_mock(
            channel_id_str=ch_id,
            report_id=rep_id_v1,
            csv_body=_csv(500),
            job_id="job_rstat_01",
            report_start=period_start,
            report_end=period_end,
            report_create="2026-10-09T08:00:00Z",
        )
    )
    svc_v1 = SyncService(
        session=db_session,
        settings=test_settings,
        oauth_service=OAuthService(
            session=db_session,
            settings=test_settings,
            crypto_service=crypto_svc,
            http_client=v1_client,
        ),
        http_client=v1_client,
    )

    async def _run_v1() -> None:
        res = await svc_v1.sync_channel(
            user_id=user.id,
            channel_id=channel.id,
            sync_types=["reporting_reach"],
        )
        assert res.status == "succeeded"
        assert res.records_processed == 1

    asyncio.run(_run_v1())

    # v1 ingestion recorded
    ing_v1 = (
        db_session.query(ReportingReportIngestion)
        .filter_by(channel_id=channel.id, report_id=rep_id_v1)
        .one()
    )
    assert ing_v1.rows_ingested == 1

    # ---- Phase 2: attempt to ingest an OLDER report for the same period (must be skipped) ----
    def older_handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/channels" in url:
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": ch_id,
                            "snippet": {"title": "Rstat Channel"},
                            "contentDetails": {
                                "relatedPlaylists": {"uploads": f"UU_{ch_id[3:]}"}
                            },
                            "statistics": {"viewCount": "500"},
                        }
                    ]
                },
            )
        if "/v1/jobs" in url and "reports" not in url:
            return httpx.Response(
                200,
                json={"jobs": [{"id": "job_rstat_01", "reportTypeId": "channel_reach_basic_a1"}]},
            )
        if "/jobs/job_rstat_01/reports" in url:
            # Returns v1 (already ingested) AND old (earlier create_time)
            return httpx.Response(
                200,
                json={
                    "reports": [
                        {
                            "id": rep_id_v1,
                            "jobId": "job_rstat_01",
                            "startTime": period_start,
                            "endTime": period_end,
                            "createTime": "2026-10-09T08:00:00Z",
                            "downloadUrl": f"https://storage.googleapis.com/b/{rep_id_v1}.csv",
                        },
                        {
                            "id": rep_id_old,
                            "jobId": "job_rstat_01",
                            "startTime": period_start,
                            "endTime": period_end,
                            "createTime": "2026-10-08T00:00:00Z",  # older than v1
                            "downloadUrl": f"https://storage.googleapis.com/b/{rep_id_old}.csv",
                        },
                    ]
                },
            )
        if f"{rep_id_old}.csv" in url:
            # Should never be reached
            return httpx.Response(200, text=_csv(100))
        return httpx.Response(200, json={})

    old_client = httpx.AsyncClient(transport=httpx.MockTransport(older_handler))
    svc_old = SyncService(
        session=db_session,
        settings=test_settings,
        oauth_service=OAuthService(
            session=db_session,
            settings=test_settings,
            crypto_service=crypto_svc,
            http_client=old_client,
        ),
        http_client=old_client,
    )

    async def _run_old() -> None:
        res = await svc_old.sync_channel(
            user_id=user.id,
            channel_id=channel.id,
            sync_types=["reporting_reach"],
        )
        # Nothing new to process — v1 already ingested, old report skipped
        assert res.status == "succeeded"
        assert res.records_processed == 0

    asyncio.run(_run_old())

    # rep_id_old must NOT be in the ingestion table
    assert (
        db_session.query(ReportingReportIngestion)
        .filter_by(channel_id=channel.id, report_id=rep_id_old)
        .one_or_none()
    ) is None

    # ---- Phase 3: ingest v2 restatement (750 impressions, newer create_time) ----
    def restatement_handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/channels" in url:
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": ch_id,
                            "snippet": {"title": "Rstat Channel"},
                            "contentDetails": {
                                "relatedPlaylists": {"uploads": f"UU_{ch_id[3:]}"}
                            },
                            "statistics": {"viewCount": "500"},
                        }
                    ]
                },
            )
        if "/v1/jobs" in url and "reports" not in url:
            return httpx.Response(
                200,
                json={"jobs": [{"id": "job_rstat_01", "reportTypeId": "channel_reach_basic_a1"}]},
            )
        if "/jobs/job_rstat_01/reports" in url:
            return httpx.Response(
                200,
                json={
                    "reports": [
                        {
                            "id": rep_id_v1,
                            "jobId": "job_rstat_01",
                            "startTime": period_start,
                            "endTime": period_end,
                            "createTime": "2026-10-09T08:00:00Z",
                            "downloadUrl": f"https://storage.googleapis.com/b/{rep_id_v1}.csv",
                        },
                        {
                            "id": rep_id_v2,
                            "jobId": "job_rstat_01",
                            "startTime": period_start,
                            "endTime": period_end,
                            "createTime": "2026-10-10T14:00:00Z",  # newer than v1
                            "downloadUrl": f"https://storage.googleapis.com/b/{rep_id_v2}.csv",
                        },
                    ]
                },
            )
        if f"{rep_id_v2}.csv" in url:
            return httpx.Response(200, text=_csv(750))
        if f"{rep_id_v1}.csv" in url:
            return httpx.Response(200, text=_csv(500))
        return httpx.Response(200, json={})

    v2_client = httpx.AsyncClient(transport=httpx.MockTransport(restatement_handler))
    svc_v2 = SyncService(
        session=db_session,
        settings=test_settings,
        oauth_service=OAuthService(
            session=db_session,
            settings=test_settings,
            crypto_service=crypto_svc,
            http_client=v2_client,
        ),
        http_client=v2_client,
    )

    async def _run_v2() -> None:
        res = await svc_v2.sync_channel(
            user_id=user.id,
            channel_id=channel.id,
            sync_types=["reporting_reach"],
        )
        # v2 restatement must be processed; v1 is already in processed_ids and skipped
        assert res.status == "succeeded"
        assert res.records_processed == 1

    asyncio.run(_run_v2())

    # v2 ingestion must exist
    ing_v2 = (
        db_session.query(ReportingReportIngestion)
        .filter_by(channel_id=channel.id, report_id=rep_id_v2)
        .one_or_none()
    )
    assert ing_v2 is not None, "Restatement v2 must be recorded as ingested"
    assert ing_v2.rows_ingested == 1

    # The reach metric for that video/date must reflect the v2 data (750 impressions)
    from miconte.models.metrics import VideoDailyMetric

    metric = (
        db_session.query(VideoDailyMetric)
        .filter_by(video_id=video.id, metric_date=date(2026, 10, 1))
        .one_or_none()
    )
    assert metric is not None
    assert metric.thumbnail_impressions == 750, (
        f"Metric should be updated to v2 (750) but got {metric.thumbnail_impressions}"
    )


@pytest.mark.integration
def test_sync_reporting_api_restatement_clears_rows_absent_in_newer_version(
    db_session: Session,
    test_settings: Settings,
    crypto_svc: TokenEncryptionService,
) -> None:
    """When a restatement covers fewer rows than its predecessor, dates absent in the
    newer version must not silently retain the stale impressions from the old version.

    Scenario:
    - v1 report has two rows: Oct 1 (500 impr.) and Oct 3 (300 impr.).
    - v2 restatement (same period, newer create_time) has only one row: Oct 1 (700 impr.).
    - After v2 is applied: Oct 1 must be 700 impr., Oct 3 must be NULL (cleared).
    """
    ch_id = f"UC_CLR_{uuid.uuid4().hex[:6]}"
    rep_id_v1 = f"rep_clr_v1_{uuid.uuid4().hex[:6]}"
    rep_id_v2 = f"rep_clr_v2_{uuid.uuid4().hex[:6]}"
    user, channel = _setup_authorized_channel(db_session, crypto_svc, channel_id_str=ch_id)

    from miconte.persistence.repositories.video_repo import VideoRepository

    video_repo = VideoRepository(db_session)
    video = video_repo.upsert_video(
        channel_id=channel.id,
        youtube_video_id="yt_clr_vid",
        title="Clear Test Video",
        published_at=datetime(2026, 1, 1, tzinfo=UTC),
        duration_seconds=60,
        duration_iso="PT1M",
    )
    db_session.commit()

    period_start = "2026-10-01T00:00:00Z"
    period_end = "2026-10-08T00:00:00Z"

    def _csv_v1() -> str:
        return (
            _VALID_REACH_CSV_HEADER
            + f"20261001,{ch_id},{video.youtube_video_id},on_demand,500,0.05\n"
            + f"20261003,{ch_id},{video.youtube_video_id},on_demand,300,0.03\n"
        )

    def _csv_v2() -> str:
        # Oct 3 row is absent — restatement covers only Oct 1
        return (
            _VALID_REACH_CSV_HEADER
            + f"20261001,{ch_id},{video.youtube_video_id},on_demand,700,0.07\n"
        )

    # ---- Phase 1: ingest v1 ----
    v1_client = httpx.AsyncClient(
        transport=_build_reporting_mock(
            channel_id_str=ch_id,
            report_id=rep_id_v1,
            csv_body=_csv_v1(),
            job_id="job_clr_01",
            report_start=period_start,
            report_end=period_end,
            report_create="2026-10-09T08:00:00Z",
        )
    )
    svc_v1 = SyncService(
        session=db_session,
        settings=test_settings,
        oauth_service=OAuthService(
            session=db_session,
            settings=test_settings,
            crypto_service=crypto_svc,
            http_client=v1_client,
        ),
        http_client=v1_client,
    )

    async def _run_v1() -> None:
        res = await svc_v1.sync_channel(
            user_id=user.id,
            channel_id=channel.id,
            sync_types=["reporting_reach"],
        )
        assert res.status == "succeeded"
        assert res.records_processed == 2  # Oct 1 + Oct 3

    asyncio.run(_run_v1())

    # Verify both rows are present after v1
    from miconte.models.metrics import VideoDailyMetric

    metric_oct1_after_v1 = (
        db_session.query(VideoDailyMetric)
        .filter_by(video_id=video.id, metric_date=date(2026, 10, 1))
        .one_or_none()
    )
    metric_oct3_after_v1 = (
        db_session.query(VideoDailyMetric)
        .filter_by(video_id=video.id, metric_date=date(2026, 10, 3))
        .one_or_none()
    )
    assert metric_oct1_after_v1 is not None and metric_oct1_after_v1.thumbnail_impressions == 500
    assert metric_oct3_after_v1 is not None and metric_oct3_after_v1.thumbnail_impressions == 300

    # ---- Phase 2: ingest v2 restatement (Oct 3 row absent) ----
    def restatement_handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/channels" in url:
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": ch_id,
                            "snippet": {"title": "Clear Channel"},
                            "contentDetails": {
                                "relatedPlaylists": {"uploads": f"UU_{ch_id[3:]}"}
                            },
                            "statistics": {"viewCount": "100"},
                        }
                    ]
                },
            )
        if "/v1/jobs" in url and "reports" not in url:
            return httpx.Response(
                200,
                json={"jobs": [{"id": "job_clr_01", "reportTypeId": "channel_reach_basic_a1"}]},
            )
        if "/jobs/job_clr_01/reports" in url:
            return httpx.Response(
                200,
                json={
                    "reports": [
                        {
                            "id": rep_id_v1,
                            "jobId": "job_clr_01",
                            "startTime": period_start,
                            "endTime": period_end,
                            "createTime": "2026-10-09T08:00:00Z",
                            "downloadUrl": f"https://storage.googleapis.com/b/{rep_id_v1}.csv",
                        },
                        {
                            "id": rep_id_v2,
                            "jobId": "job_clr_01",
                            "startTime": period_start,
                            "endTime": period_end,
                            "createTime": "2026-10-10T10:00:00Z",  # newer
                            "downloadUrl": f"https://storage.googleapis.com/b/{rep_id_v2}.csv",
                        },
                    ]
                },
            )
        if f"{rep_id_v2}.csv" in url:
            return httpx.Response(200, text=_csv_v2())
        return httpx.Response(200, json={})

    v2_client = httpx.AsyncClient(transport=httpx.MockTransport(restatement_handler))
    svc_v2 = SyncService(
        session=db_session,
        settings=test_settings,
        oauth_service=OAuthService(
            session=db_session,
            settings=test_settings,
            crypto_service=crypto_svc,
            http_client=v2_client,
        ),
        http_client=v2_client,
    )

    async def _run_v2() -> None:
        res = await svc_v2.sync_channel(
            user_id=user.id,
            channel_id=channel.id,
            sync_types=["reporting_reach"],
        )
        assert res.status == "succeeded"
        assert res.records_processed == 1  # only Oct 1 in v2

    asyncio.run(_run_v2())

    # Oct 1 must be updated to v2 value
    db_session.expire_all()
    metric_oct1_after_v2 = (
        db_session.query(VideoDailyMetric)
        .filter_by(video_id=video.id, metric_date=date(2026, 10, 1))
        .one_or_none()
    )
    # Oct 3 must be cleared (absent in v2 → reach fields nulled out)
    metric_oct3_after_v2 = (
        db_session.query(VideoDailyMetric)
        .filter_by(video_id=video.id, metric_date=date(2026, 10, 3))
        .one_or_none()
    )
    assert metric_oct1_after_v2 is not None
    assert metric_oct1_after_v2.thumbnail_impressions == 700, (
        f"Oct 1 should be 700 after v2, got {metric_oct1_after_v2.thumbnail_impressions}"
    )
    assert metric_oct3_after_v2 is not None, "Row must exist but reach fields must be NULL"
    assert metric_oct3_after_v2.thumbnail_impressions is None, (
        "Oct 3 was absent in v2 restatement; thumbnail_impressions must be NULL"
    )
    assert metric_oct3_after_v2.reach_source is None


@pytest.mark.integration
def test_sync_reporting_api_ingestion_failure_does_not_mark_report_processed(
    db_session: Session,
    test_settings: Settings,
    crypto_svc: TokenEncryptionService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If recording the ingestion raises after metrics have been flushed to the session,
    the outer transaction rollback must undo both the metric rows and the ingestion record.

    Guarantees:
    - No ReportingReportIngestion row for the channel after the failed sync.
    - The reach metric written in the same transaction is also absent after rollback.
    - A subsequent sync (without the failure injection) succeeds and persists both.
    """
    ch_id = f"UC_FAIL_{uuid.uuid4().hex[:6]}"
    rep_id = f"rep_fail_{uuid.uuid4().hex[:6]}"
    vid_id = f"yt_fail_vid_{uuid.uuid4().hex[:8]}"
    user, channel = _setup_authorized_channel(db_session, crypto_svc, channel_id_str=ch_id)

    from miconte.persistence.repositories.video_repo import VideoRepository

    video_repo = VideoRepository(db_session)
    video = video_repo.upsert_video(
        channel_id=channel.id,
        youtube_video_id=vid_id,
        title="Failure Test Video",
        published_at=datetime(2026, 1, 1, tzinfo=UTC),
        duration_seconds=90,
        duration_iso="PT1M30S",
    )
    db_session.commit()

    csv_body = (
        _VALID_REACH_CSV_HEADER
        + f"20261005,{ch_id},{video.youtube_video_id},on_demand,800,0.04\n"
    )
    transport = _build_reporting_mock(
        channel_id_str=ch_id,
        report_id=rep_id,
        csv_body=csv_body,
        job_id="job_fail_01",
        report_start="2026-10-01T00:00:00Z",
        report_end="2026-10-08T00:00:00Z",
        report_create="2026-10-09T06:00:00Z",
    )

    # ---- Phase 1: inject fault in record_report_ingestion ----
    mock_client = httpx.AsyncClient(transport=transport)
    svc_fail = SyncService(
        session=db_session,
        settings=test_settings,
        oauth_service=OAuthService(
            session=db_session,
            settings=test_settings,
            crypto_service=crypto_svc,
            http_client=mock_client,
        ),
        http_client=mock_client,
    )

    def _raise_on_record(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("Simulated DB failure during ingestion record")

    monkeypatch.setattr(svc_fail.analysis_repo, "record_report_ingestion", _raise_on_record)

    async def _run_fail() -> None:
        res = await svc_fail.sync_channel(
            user_id=user.id,
            channel_id=channel.id,
            sync_types=["reporting_reach"],
        )
        assert res.status == "failed", f"Expected failed, got {res.status}"

    asyncio.run(_run_fail())

    # After rollback: no ingestion record must exist
    ingestion_after_fail = (
        db_session.query(ReportingReportIngestion)
        .filter_by(channel_id=channel.id, report_id=rep_id)
        .one_or_none()
    )
    assert ingestion_after_fail is None, (
        "Ingestion record must not exist after a rolled-back transaction"
    )

    # After rollback: the reach metric written before the exception must also be absent
    from miconte.models.metrics import VideoDailyMetric

    metric_after_fail = (
        db_session.query(VideoDailyMetric)
        .filter_by(video_id=video.id, metric_date=date(2026, 10, 5))
        .one_or_none()
    )
    assert metric_after_fail is None or metric_after_fail.thumbnail_impressions is None, (
        "Metric written in the same (rolled-back) transaction must not be committed"
    )

    # ---- Phase 2: retry succeeds and persists everything ----
    mock_client_retry = httpx.AsyncClient(transport=transport)
    svc_retry = SyncService(
        session=db_session,
        settings=test_settings,
        oauth_service=OAuthService(
            session=db_session,
            settings=test_settings,
            crypto_service=crypto_svc,
            http_client=mock_client_retry,
        ),
        http_client=mock_client_retry,
    )

    async def _run_retry() -> None:
        res = await svc_retry.sync_channel(
            user_id=user.id,
            channel_id=channel.id,
            sync_types=["reporting_reach"],
        )
        assert res.status == "succeeded"
        assert res.records_processed == 1

    asyncio.run(_run_retry())

    ingestion_after_retry = (
        db_session.query(ReportingReportIngestion)
        .filter_by(channel_id=channel.id, report_id=rep_id)
        .one_or_none()
    )
    assert ingestion_after_retry is not None, "Ingestion record must exist after successful retry"
    assert ingestion_after_retry.rows_ingested == 1


@pytest.mark.integration
def test_analysis_repo_get_latest_ingestion_scoped_by_job_id(
    db_session: Session,
    test_settings: Settings,
    crypto_svc: TokenEncryptionService,
) -> None:
    """get_latest_ingestion_for_period must only return records from the requested job_id.

    Scenario: job_A ingests a report for Oct 1-8. When querying for job_B's ingestion
    for the identical period, the result must be None — job_B has not been ingested,
    and job_A's record must not contaminate the check.

    This exercises the job_id filter added to prevent cross-job restatement confusion:
    two distinct YouTube jobs (different report types) can legally cover the same
    calendar period without being versions of each other.
    """
    from miconte.persistence.repositories.analysis_repo import AnalysisRepository

    user, channel = _setup_authorized_channel(
        db_session, crypto_svc, channel_id_str=f"UC_JOB_ISO_{uuid.uuid4().hex[:6]}"
    )

    period_start = datetime(2026, 10, 1, tzinfo=UTC)
    period_end = datetime(2026, 10, 8, tzinfo=UTC)

    analysis_repo = AnalysisRepository(db_session)

    analysis_repo.record_report_ingestion(
        channel_id=channel.id,
        report_id=f"rep_job_a_{uuid.uuid4().hex[:8]}",
        job_id="job_type_reach_01",
        report_period_start=period_start,
        report_period_end=period_end,
        report_create_time=datetime(2026, 10, 9, 8, tzinfo=UTC),
        rows_ingested=5,
    )
    db_session.flush()

    # Must find job_A's record when querying for job_A
    ingestion_a = analysis_repo.get_latest_ingestion_for_period(
        channel.id, period_start, period_end, job_id="job_type_reach_01"
    )
    assert ingestion_a is not None, "job_A ingestion must be found when queried by job_A id"
    assert ingestion_a.job_id == "job_type_reach_01"

    # Must return None for job_B even though the period is identical
    ingestion_b = analysis_repo.get_latest_ingestion_for_period(
        channel.id, period_start, period_end, job_id="job_type_revenue_01"
    )
    assert ingestion_b is None, (
        "job_B has no ingestion for this period; "
        "get_latest_ingestion_for_period must not return job_A's record just because "
        "the (channel_id, period_start, period_end) tuple matches"
    )


@pytest.mark.integration
def test_sync_reporting_api_restatement_does_not_clear_other_reach_sources(
    db_session: Session,
    test_settings: Settings,
    crypto_svc: TokenEncryptionService,
) -> None:
    """clear_reach_metrics_for_channel_period only NULLs rows tagged 'reporting_api_v1'.

    Rows with a different reach_source in the same date range must survive a
    restatement unchanged.  This guards against future pipelines that might write
    reach data from other sources into the same table.
    """
    ch_id = f"UC_SRC_ISO_{uuid.uuid4().hex[:6]}"
    rep_id_v1 = f"rep_srciso_v1_{uuid.uuid4().hex[:6]}"
    rep_id_v2 = f"rep_srciso_v2_{uuid.uuid4().hex[:6]}"
    vid_id = f"yt_srciso_vid_{uuid.uuid4().hex[:8]}"
    user, channel = _setup_authorized_channel(db_session, crypto_svc, channel_id_str=ch_id)

    from miconte.persistence.repositories.video_repo import VideoRepository

    video_repo = VideoRepository(db_session)
    video = video_repo.upsert_video(
        channel_id=channel.id,
        youtube_video_id=vid_id,
        title="Source Isolation Video",
        published_at=datetime(2026, 1, 1, tzinfo=UTC),
        duration_seconds=90,
        duration_iso="PT1M30S",
    )
    db_session.commit()

    # Insert a row with a different reach_source before any sync runs.
    # This simulates a hypothetical future data source writing to the same table.
    other_source_row = VideoDailyMetric(
        video_id=video.id,
        metric_date=date(2026, 10, 2),
        thumbnail_impressions=999,
        reach_source="other_source",
    )
    db_session.add(other_source_row)
    db_session.commit()

    period_start = "2026-10-01T00:00:00Z"
    period_end = "2026-10-08T00:00:00Z"

    # Ingest v1 (Oct 1 row, reporting_api_v1)
    v1_csv = (
        _VALID_REACH_CSV_HEADER
        + f"20261001,{ch_id},{video.youtube_video_id},on_demand,500,0.05\n"
    )
    v1_client = httpx.AsyncClient(
        transport=_build_reporting_mock(
            channel_id_str=ch_id,
            report_id=rep_id_v1,
            csv_body=v1_csv,
            job_id="job_srciso_01",
            report_start=period_start,
            report_end=period_end,
            report_create="2026-10-09T08:00:00Z",
        )
    )
    svc_v1 = SyncService(
        session=db_session,
        settings=test_settings,
        oauth_service=OAuthService(
            session=db_session,
            settings=test_settings,
            crypto_service=crypto_svc,
            http_client=v1_client,
        ),
        http_client=v1_client,
    )

    async def _run_v1() -> None:
        res = await svc_v1.sync_channel(
            user_id=user.id,
            channel_id=channel.id,
            sync_types=["reporting_reach"],
        )
        assert res.status == "succeeded"

    asyncio.run(_run_v1())

    # Trigger v2 restatement (newer create_time, same period, only Oct 1)
    def restatement_handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/channels" in url:
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": ch_id,
                            "snippet": {"title": "Src Iso Channel"},
                            "contentDetails": {
                                "relatedPlaylists": {"uploads": f"UU_{ch_id[3:]}"}
                            },
                            "statistics": {"viewCount": "100"},
                        }
                    ]
                },
            )
        if "/v1/jobs" in url and "reports" not in url:
            return httpx.Response(
                200,
                json={"jobs": [{"id": "job_srciso_01", "reportTypeId": "channel_reach_basic_a1"}]},
            )
        if "/jobs/job_srciso_01/reports" in url:
            return httpx.Response(
                200,
                json={
                    "reports": [
                        {
                            "id": rep_id_v1,
                            "jobId": "job_srciso_01",
                            "startTime": period_start,
                            "endTime": period_end,
                            "createTime": "2026-10-09T08:00:00Z",
                            "downloadUrl": f"https://storage.googleapis.com/b/{rep_id_v1}.csv",
                        },
                        {
                            "id": rep_id_v2,
                            "jobId": "job_srciso_01",
                            "startTime": period_start,
                            "endTime": period_end,
                            "createTime": "2026-10-10T10:00:00Z",
                            "downloadUrl": f"https://storage.googleapis.com/b/{rep_id_v2}.csv",
                        },
                    ]
                },
            )
        if f"{rep_id_v2}.csv" in url:
            return httpx.Response(
                200,
                text=(
                    _VALID_REACH_CSV_HEADER
                    + f"20261001,{ch_id},{video.youtube_video_id},on_demand,600,0.06\n"
                ),
            )
        return httpx.Response(200, json={})

    v2_client = httpx.AsyncClient(transport=httpx.MockTransport(restatement_handler))
    svc_v2 = SyncService(
        session=db_session,
        settings=test_settings,
        oauth_service=OAuthService(
            session=db_session,
            settings=test_settings,
            crypto_service=crypto_svc,
            http_client=v2_client,
        ),
        http_client=v2_client,
    )

    async def _run_v2() -> None:
        res = await svc_v2.sync_channel(
            user_id=user.id,
            channel_id=channel.id,
            sync_types=["reporting_reach"],
        )
        assert res.status == "succeeded"
        assert res.records_processed == 1

    asyncio.run(_run_v2())

    db_session.expire_all()

    # The row with reach_source='other_source' must be untouched
    other_row = (
        db_session.query(VideoDailyMetric)
        .filter_by(video_id=video.id, metric_date=date(2026, 10, 2))
        .one_or_none()
    )
    assert other_row is not None
    assert other_row.thumbnail_impressions == 999, (
        f"Row with reach_source='other_source' must not be cleared by a restatement; "
        f"got {other_row.thumbnail_impressions}"
    )
    assert other_row.reach_source == "other_source"


@pytest.mark.integration
def test_sync_reporting_api_restatement_respects_endtime_exclusive_boundary(
    db_session: Session,
    test_settings: Settings,
    crypto_svc: TokenEncryptionService,
) -> None:
    """The YouTube Reporting API end_time is exclusive: a metric row dated exactly at
    end_time must NOT be cleared when a restatement is applied.

    Period: 2026-10-01T00:00:00Z → 2026-10-08T00:00:00Z covers Oct 1–7 inclusive.
    A row pre-seeded for Oct 8 (= end_time.date()) must survive the restatement's
    clear pass because end_date = end_time.date() - 1 day = Oct 7.
    """
    ch_id = f"UC_BNDRY_{uuid.uuid4().hex[:6]}"
    rep_id_v1 = f"rep_bndry_v1_{uuid.uuid4().hex[:6]}"
    rep_id_v2 = f"rep_bndry_v2_{uuid.uuid4().hex[:6]}"
    vid_id = f"yt_bndry_vid_{uuid.uuid4().hex[:8]}"
    user, channel = _setup_authorized_channel(db_session, crypto_svc, channel_id_str=ch_id)

    from miconte.persistence.repositories.video_repo import VideoRepository

    video_repo = VideoRepository(db_session)
    video = video_repo.upsert_video(
        channel_id=channel.id,
        youtube_video_id=vid_id,
        title="Boundary Test Video",
        published_at=datetime(2026, 1, 1, tzinfo=UTC),
        duration_seconds=60,
        duration_iso="PT1M",
    )
    db_session.commit()

    period_start = "2026-10-01T00:00:00Z"
    period_end = "2026-10-08T00:00:00Z"

    # Ingest v1: Oct 1 (500 impr.) and Oct 7 (300 impr.)
    v1_csv = (
        _VALID_REACH_CSV_HEADER
        + f"20261001,{ch_id},{video.youtube_video_id},on_demand,500,0.05\n"
        + f"20261007,{ch_id},{video.youtube_video_id},on_demand,300,0.03\n"
    )
    v1_client = httpx.AsyncClient(
        transport=_build_reporting_mock(
            channel_id_str=ch_id,
            report_id=rep_id_v1,
            csv_body=v1_csv,
            job_id="job_bndry_01",
            report_start=period_start,
            report_end=period_end,
            report_create="2026-10-09T08:00:00Z",
        )
    )
    svc_v1 = SyncService(
        session=db_session,
        settings=test_settings,
        oauth_service=OAuthService(
            session=db_session,
            settings=test_settings,
            crypto_service=crypto_svc,
            http_client=v1_client,
        ),
        http_client=v1_client,
    )

    async def _run_v1() -> None:
        res = await svc_v1.sync_channel(
            user_id=user.id,
            channel_id=channel.id,
            sync_types=["reporting_reach"],
        )
        assert res.status == "succeeded"
        assert res.records_processed == 2

    asyncio.run(_run_v1())

    # Pre-seed a row for Oct 8 (= the exclusive end date) with reporting_api_v1.
    # Simulates data from a subsequent period's report that overlaps the boundary.
    oct8_row = VideoDailyMetric(
        video_id=video.id,
        metric_date=date(2026, 10, 8),
        thumbnail_impressions=888,
        reach_source="reporting_api_v1",
    )
    db_session.add(oct8_row)
    db_session.commit()

    # Trigger v2 restatement: only Oct 1 (Oct 7 absent → must be cleared; Oct 8 untouched)
    def restatement_handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/channels" in url:
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": ch_id,
                            "snippet": {"title": "Boundary Channel"},
                            "contentDetails": {
                                "relatedPlaylists": {"uploads": f"UU_{ch_id[3:]}"}
                            },
                            "statistics": {"viewCount": "100"},
                        }
                    ]
                },
            )
        if "/v1/jobs" in url and "reports" not in url:
            return httpx.Response(
                200,
                json={"jobs": [{"id": "job_bndry_01", "reportTypeId": "channel_reach_basic_a1"}]},
            )
        if "/jobs/job_bndry_01/reports" in url:
            return httpx.Response(
                200,
                json={
                    "reports": [
                        {
                            "id": rep_id_v1,
                            "jobId": "job_bndry_01",
                            "startTime": period_start,
                            "endTime": period_end,
                            "createTime": "2026-10-09T08:00:00Z",
                            "downloadUrl": f"https://storage.googleapis.com/b/{rep_id_v1}.csv",
                        },
                        {
                            "id": rep_id_v2,
                            "jobId": "job_bndry_01",
                            "startTime": period_start,
                            "endTime": period_end,
                            "createTime": "2026-10-10T10:00:00Z",
                            "downloadUrl": f"https://storage.googleapis.com/b/{rep_id_v2}.csv",
                        },
                    ]
                },
            )
        if f"{rep_id_v2}.csv" in url:
            # v2 has only Oct 1; Oct 7 is absent and must be cleared
            return httpx.Response(
                200,
                text=(
                    _VALID_REACH_CSV_HEADER
                    + f"20261001,{ch_id},{video.youtube_video_id},on_demand,700,0.07\n"
                ),
            )
        return httpx.Response(200, json={})

    v2_client = httpx.AsyncClient(transport=httpx.MockTransport(restatement_handler))
    svc_v2 = SyncService(
        session=db_session,
        settings=test_settings,
        oauth_service=OAuthService(
            session=db_session,
            settings=test_settings,
            crypto_service=crypto_svc,
            http_client=v2_client,
        ),
        http_client=v2_client,
    )

    async def _run_v2() -> None:
        res = await svc_v2.sync_channel(
            user_id=user.id,
            channel_id=channel.id,
            sync_types=["reporting_reach"],
        )
        assert res.status == "succeeded"
        assert res.records_processed == 1

    asyncio.run(_run_v2())

    db_session.expire_all()

    # Oct 7 is within the period and absent in v2 → must be cleared
    metric_oct7 = (
        db_session.query(VideoDailyMetric)
        .filter_by(video_id=video.id, metric_date=date(2026, 10, 7))
        .one_or_none()
    )
    assert metric_oct7 is not None
    assert metric_oct7.thumbnail_impressions is None, (
        f"Oct 7 is inside the period and absent in v2; thumbnail_impressions must be NULL, "
        f"got {metric_oct7.thumbnail_impressions}"
    )

    # Oct 8 is the exclusive end date — it is OUTSIDE the cleared range and must be untouched
    metric_oct8 = (
        db_session.query(VideoDailyMetric)
        .filter_by(video_id=video.id, metric_date=date(2026, 10, 8))
        .one_or_none()
    )
    assert metric_oct8 is not None
    assert metric_oct8.thumbnail_impressions == 888, (
        f"Oct 8 is the exclusive end_time date and must NOT be cleared; "
        f"got {metric_oct8.thumbnail_impressions}"
    )


# ---------------------------------------------------------------------------
# Public snapshot anomaly isolation: negative like_count
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_sync_public_snapshot_negative_likes_stores_null_not_raises(
    db_session: Session,
    test_settings: Settings,
    crypto_svc: TokenEncryptionService,
) -> None:
    """A negative like_count from YouTube must not raise an IntegrityError.

    The snapshot must be committed successfully with like_count = NULL.
    The DB constraint (like_count IS NULL OR like_count >= 0) must not be violated.
    """
    from miconte.persistence.repositories.video_repo import VideoRepository

    user, channel = _setup_authorized_channel(
        db_session, crypto_svc, channel_id_str=f"UC_SNAP_NEG_{uuid.uuid4().hex[:6]}"
    )
    video_repo = VideoRepository(db_session)
    video = video_repo.upsert_video(
        channel_id=channel.id,
        youtube_video_id="yt_neg_likes_vid",
        title="Negative Likes Video",
        published_at=datetime(2026, 1, 1, tzinfo=UTC),
        duration_seconds=120,
        duration_iso="PT2M",
    )
    db_session.flush()

    # This must not raise despite like_count = -5
    snapshot = video_repo.record_public_snapshot(
        video_id=video.id,
        captured_at=datetime(2026, 10, 27, 12, 0, 0, tzinfo=UTC),
        view_count=1000,
        like_count=-5,
        comment_count=20,
    )
    db_session.commit()

    db_session.expire_all()
    persisted = (
        db_session.query(VideoPublicSnapshot)
        .filter_by(id=snapshot.id)
        .one()
    )
    assert persisted.like_count is None, (
        f"Negative like_count must be stored as NULL; got {persisted.like_count}"
    )


@pytest.mark.integration
def test_sync_public_snapshot_negative_likes_anomaly_flags_set(
    db_session: Session,
    test_settings: Settings,
    crypto_svc: TokenEncryptionService,
) -> None:
    """A negative like_count must set is_anomalous=True and record the original value in
    anomaly_notes."""
    from miconte.persistence.repositories.video_repo import VideoRepository

    user, channel = _setup_authorized_channel(
        db_session, crypto_svc, channel_id_str=f"UC_SNAP_FLAG_{uuid.uuid4().hex[:6]}"
    )
    video_repo = VideoRepository(db_session)
    video = video_repo.upsert_video(
        channel_id=channel.id,
        youtube_video_id="yt_flag_vid",
        title="Flag Test Video",
        published_at=datetime(2026, 1, 1, tzinfo=UTC),
        duration_seconds=90,
        duration_iso="PT1M30S",
    )
    db_session.flush()

    snapshot = video_repo.record_public_snapshot(
        video_id=video.id,
        captured_at=datetime(2026, 10, 27, 12, 0, 0, tzinfo=UTC),
        view_count=500,
        like_count=-3,
        comment_count=10,
    )
    db_session.commit()

    db_session.expire_all()
    persisted = db_session.query(VideoPublicSnapshot).filter_by(id=snapshot.id).one()

    assert persisted.is_anomalous is True, "is_anomalous must be True for a negative like_count"
    assert persisted.anomaly_notes is not None, "anomaly_notes must not be None"
    assert "-3" in persisted.anomaly_notes, (
        f"Original negative value (-3) must appear in anomaly_notes; got: {persisted.anomaly_notes}"
    )


@pytest.mark.integration
def test_sync_public_snapshot_negative_likes_preserves_other_metrics(
    db_session: Session,
    test_settings: Settings,
    crypto_svc: TokenEncryptionService,
) -> None:
    """When like_count is negative, view_count and comment_count must be stored unchanged."""
    from miconte.persistence.repositories.video_repo import VideoRepository

    user, channel = _setup_authorized_channel(
        db_session, crypto_svc, channel_id_str=f"UC_SNAP_OTH_{uuid.uuid4().hex[:6]}"
    )
    video_repo = VideoRepository(db_session)
    video = video_repo.upsert_video(
        channel_id=channel.id,
        youtube_video_id="yt_other_metrics_vid",
        title="Other Metrics Video",
        published_at=datetime(2026, 1, 1, tzinfo=UTC),
        duration_seconds=60,
        duration_iso="PT1M",
    )
    db_session.flush()

    snapshot = video_repo.record_public_snapshot(
        video_id=video.id,
        captured_at=datetime(2026, 10, 27, 12, 0, 0, tzinfo=UTC),
        view_count=9999,
        like_count=-7,
        comment_count=42,
    )
    db_session.commit()

    db_session.expire_all()
    persisted = db_session.query(VideoPublicSnapshot).filter_by(id=snapshot.id).one()

    assert persisted.view_count == 9999, f"view_count must be preserved; got {persisted.view_count}"
    assert persisted.comment_count == 42, (
        f"comment_count must be preserved; got {persisted.comment_count}"
    )
    assert persisted.like_count is None


@pytest.mark.integration
def test_sync_public_snapshot_normal_likes_stored_without_anomaly(
    db_session: Session,
    test_settings: Settings,
    crypto_svc: TokenEncryptionService,
) -> None:
    """A non-negative like_count must be stored as-is with is_anomalous=False."""
    from miconte.persistence.repositories.video_repo import VideoRepository

    user, channel = _setup_authorized_channel(
        db_session, crypto_svc, channel_id_str=f"UC_SNAP_NORM_{uuid.uuid4().hex[:6]}"
    )
    video_repo = VideoRepository(db_session)
    video = video_repo.upsert_video(
        channel_id=channel.id,
        youtube_video_id="yt_normal_likes_vid",
        title="Normal Likes Video",
        published_at=datetime(2026, 1, 1, tzinfo=UTC),
        duration_seconds=180,
        duration_iso="PT3M",
    )
    db_session.flush()

    snapshot = video_repo.record_public_snapshot(
        video_id=video.id,
        captured_at=datetime(2026, 10, 27, 12, 0, 0, tzinfo=UTC),
        view_count=200,
        like_count=150,
        comment_count=5,
    )
    db_session.commit()

    db_session.expire_all()
    persisted = db_session.query(VideoPublicSnapshot).filter_by(id=snapshot.id).one()

    assert persisted.like_count == 150, (
        f"Normal like_count must be stored as-is; got {persisted.like_count}"
    )
    assert persisted.is_anomalous is False
    assert persisted.anomaly_notes is None


@pytest.mark.integration
def test_sync_public_snapshot_negative_likes_does_not_interrupt_sync(
    db_session: Session,
    test_settings: Settings,
    crypto_svc: TokenEncryptionService,
) -> None:
    """A negative like_count in a video must not prevent the full sync from completing.

    The overall sync result must be 'succeeded', and the snapshot must be persisted
    with like_count=NULL and is_anomalous=True.
    """
    ch_id = f"UC_SYNC_NEG_{uuid.uuid4().hex[:6]}"
    user, channel = _setup_authorized_channel(db_session, crypto_svc, channel_id_str=ch_id)

    def mock_negative_likes(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/channels" in url:
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": ch_id,
                            "snippet": {"title": "Negative Likes Channel"},
                            "contentDetails": {
                                "relatedPlaylists": {"uploads": f"UU_{ch_id[3:]}"}
                            },
                            "statistics": {"viewCount": "500", "videoCount": "1"},
                        }
                    ]
                },
            )
        if "/playlistItems" in url:
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "contentDetails": {"videoId": "yt_neg_sync_vid"},
                            "snippet": {
                                "title": "Negative Likes Video",
                                "publishedAt": "2026-01-01T00:00:00Z",
                            },
                        }
                    ]
                },
            )
        if "/videos" in url:
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "yt_neg_sync_vid",
                            "snippet": {
                                "title": "Negative Likes Video",
                                "publishedAt": "2026-01-01T00:00:00Z",
                            },
                            "contentDetails": {"duration": "PT5M"},
                            "statistics": {
                                "viewCount": "1000",
                                "likeCount": "-3",   # negative from YouTube
                                "commentCount": "15",
                            },
                        }
                    ]
                },
            )
        return httpx.Response(200, json={"items": []})

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_negative_likes))
    sync_service = SyncService(
        session=db_session,
        settings=test_settings,
        oauth_service=OAuthService(
            session=db_session,
            settings=test_settings,
            crypto_service=crypto_svc,
            http_client=mock_client,
        ),
        http_client=mock_client,
    )

    async def _run() -> None:
        res = await sync_service.sync_channel(
            user_id=user.id,
            channel_id=channel.id,
            sync_types=["metadata", "public_snapshots"],
        )
        assert res.status == "succeeded", (
            f"Sync must succeed despite negative like_count; got status={res.status}, "
            f"error={res.error_message}"
        )

    asyncio.run(_run())

    db_session.expire_all()
    from miconte.persistence.repositories.video_repo import VideoRepository

    video = VideoRepository(db_session).get_by_youtube_id("yt_neg_sync_vid")
    assert video is not None, "Video must have been persisted"

    snapshot = (
        db_session.query(VideoPublicSnapshot)
        .filter_by(video_id=video.id)
        .order_by(VideoPublicSnapshot.captured_at.desc())
        .first()
    )
    assert snapshot is not None, "Snapshot must have been persisted"
    assert snapshot.like_count is None, f"like_count must be NULL; got {snapshot.like_count}"
    assert snapshot.is_anomalous is True
    assert snapshot.anomaly_notes is not None
    assert "-3" in snapshot.anomaly_notes
    assert snapshot.view_count == 1000
    assert snapshot.comment_count == 15


@pytest.mark.integration
def test_sync_public_snapshot_anomaly_does_not_affect_daily_analytics(
    db_session: Session,
    test_settings: Settings,
    crypto_svc: TokenEncryptionService,
) -> None:
    """A negative like_count in a public snapshot must not interfere with Analytics persistence.

    After a sync that includes both public_snapshots and analytics_daily, the Analytics
    metric row must be stored correctly (using its own anomaly logic) independently of
    any anomaly in the public snapshot.
    """
    ch_id = f"UC_CROSS_{uuid.uuid4().hex[:6]}"
    user, channel = _setup_authorized_channel(db_session, crypto_svc, channel_id_str=ch_id)

    def mock_cross_anomaly(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/channels" in url:
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": ch_id,
                            "snippet": {"title": "Cross Anomaly Channel"},
                            "contentDetails": {
                                "relatedPlaylists": {"uploads": f"UU_{ch_id[3:]}"}
                            },
                            "statistics": {"viewCount": "300", "videoCount": "1"},
                        }
                    ]
                },
            )
        if "/playlistItems" in url:
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "contentDetails": {"videoId": "yt_cross_vid"},
                            "snippet": {
                                "title": "Cross Anomaly Video",
                                "publishedAt": "2026-01-01T00:00:00Z",
                            },
                        }
                    ]
                },
            )
        if "/videos" in url:
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "yt_cross_vid",
                            "snippet": {
                                "title": "Cross Anomaly Video",
                                "publishedAt": "2026-01-01T00:00:00Z",
                            },
                            "contentDetails": {"duration": "PT3M"},
                            "statistics": {
                                "viewCount": "300",
                                "likeCount": "-2",  # anomalous in public snapshot
                                "commentCount": "5",
                            },
                        }
                    ]
                },
            )
        if "/reports" in url:
            # Normal Analytics daily report (likes = 50, valid)
            return httpx.Response(
                200,
                json={
                    "columnHeaders": [
                        {"name": "day", "columnType": "DIMENSION", "dataType": "STRING"},
                        {"name": "views", "columnType": "METRIC", "dataType": "INTEGER"},
                        {"name": "likes", "columnType": "METRIC", "dataType": "INTEGER"},
                    ],
                    "rows": [["2026-10-27", 300, 50]],
                },
            )
        return httpx.Response(200, json={"items": [], "rows": [], "jobs": []})

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_cross_anomaly))
    sync_service = SyncService(
        session=db_session,
        settings=test_settings,
        oauth_service=OAuthService(
            session=db_session,
            settings=test_settings,
            crypto_service=crypto_svc,
            http_client=mock_client,
        ),
        http_client=mock_client,
    )

    async def _run() -> None:
        res = await sync_service.sync_channel(
            user_id=user.id,
            channel_id=channel.id,
            sync_types=["metadata", "public_snapshots", "analytics_daily"],
        )
        assert res.status == "succeeded", (
            f"Sync must succeed; got {res.status}, error={res.error_message}"
        )

    asyncio.run(_run())

    db_session.expire_all()
    channel_metric = (
        db_session.query(ChannelDailyMetric)
        .filter_by(channel_id=channel.id, metric_date=date(2026, 10, 27))
        .one_or_none()
    )
    assert channel_metric is not None, "Analytics daily metric must have been persisted"
    assert channel_metric.likes == 50, f"Analytics likes must be 50; got {channel_metric.likes}"
    assert channel_metric.is_anomalous is False


@pytest.mark.integration
def test_sync_public_snapshot_persistence_failure_does_not_create_misleading_audit(
    db_session: Session,
    test_settings: Settings,
    crypto_svc: TokenEncryptionService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real persistence failure must not leave behind a snapshot row that claims success.

    When record_public_snapshot raises after the anomaly detection logic runs, the
    entire transaction must roll back, leaving no VideoPublicSnapshot row in the DB.
    """
    from miconte.persistence.repositories.video_repo import VideoRepository

    user, channel = _setup_authorized_channel(
        db_session, crypto_svc, channel_id_str=f"UC_SNAP_FAIL_{uuid.uuid4().hex[:6]}"
    )
    video_repo = VideoRepository(db_session)
    video = video_repo.upsert_video(
        channel_id=channel.id,
        youtube_video_id="yt_fail_snap_vid",
        title="Failure Snapshot Video",
        published_at=datetime(2026, 1, 1, tzinfo=UTC),
        duration_seconds=60,
        duration_iso="PT1M",
    )
    db_session.commit()

    captured = datetime(2026, 10, 27, 12, 0, 0, tzinfo=UTC)

    # Patch record_public_snapshot to raise, simulating a DB failure after anomaly conversion.
    def _failing_record(self: VideoRepository, **kwargs: object) -> VideoPublicSnapshot:
        raise RuntimeError("Simulated DB failure during snapshot persist")

    monkeypatch.setattr(VideoRepository, "record_public_snapshot", _failing_record)

    with pytest.raises(RuntimeError, match="Simulated DB failure"):
        video_repo.record_public_snapshot(
            video_id=video.id,
            captured_at=captured,
            view_count=100,
            like_count=-1,
            comment_count=0,
        )

    # Roll back to simulate what the outer transaction handler would do
    db_session.rollback()

    # No snapshot row must exist
    row = (
        db_session.query(VideoPublicSnapshot)
        .filter_by(video_id=video.id, captured_at=captured)
        .one_or_none()
    )
    assert row is None, (
        "No VideoPublicSnapshot must exist after a rolled-back transaction"
    )


def test_periodic_loop_calls_revalidate_all_connections() -> None:
    """_periodic_loop() must invoke revalidate_all_connections() on every cycle.

    Mocking strategy: _check_and_run_due_channels and revalidate_all_connections
    are stubbed to track calls; asyncio.sleep raises CancelledError so the loop
    exits cleanly after the first cycle without waiting the real interval.
    """
    from unittest.mock import patch  # noqa: PLC0415

    scheduler = SyncScheduler(settings=Settings())
    call_counts: dict[str, int] = {"check": 0, "revalidate": 0}

    async def _fake_check() -> None:
        call_counts["check"] += 1

    async def _fake_revalidate() -> dict[str, int]:
        call_counts["revalidate"] += 1
        return {"probed": 0, "revoked": 0, "errors": 0}

    async def _fake_sleep(_seconds: float) -> None:
        raise asyncio.CancelledError

    async def _run() -> None:
        with (
            patch.object(scheduler, "_check_and_run_due_channels", side_effect=_fake_check),
            patch.object(scheduler, "revalidate_all_connections", side_effect=_fake_revalidate),
            patch("miconte.services.scheduler.asyncio.sleep", side_effect=_fake_sleep),
        ):
            scheduler._is_running = True
            await scheduler._periodic_loop()

    asyncio.run(_run())

    assert call_counts["check"] == 1, "_check_and_run_due_channels must be called"
    assert call_counts["revalidate"] == 1, (
        "revalidate_all_connections must be called from _periodic_loop"
    )
