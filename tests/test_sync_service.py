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
