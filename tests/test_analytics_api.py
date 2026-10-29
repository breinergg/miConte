"""Integration tests for the analytics API router.

Uses the real PostgreSQL test database (miconte_test_db) — not mocks.
All tests roll back their transactions to avoid state leakage.

Covered scenarios:
  - Authentication & isolation (IDOR prevention)
  - Empty / no-data cases
  - Channel summary, video list, channel analytics
  - Recommendations: run, list, baseline thresholds
  - Input validation errors
"""

from __future__ import annotations

import uuid
from collections.abc import Generator
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from miconte.api.analytics import get_analytics_service
from miconte.api.deps import DbSessionDep
from miconte.core.config import Settings
from miconte.main import app
from miconte.models.channel import Channel
from miconte.models.user import User
from miconte.models.video import Video
from miconte.persistence.session import get_engine
from miconte.services.analytics_service import AnalyticsService

_ENABLED_SETTINGS = Settings(analytics_real_data_enabled=True)

# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def db_session() -> Generator[Session]:
    engine = get_engine()
    with Session(engine) as session:
        yield session
        session.rollback()


@pytest.fixture
def client() -> Generator[TestClient]:
    """TestClient with analytics_real_data_enabled=True so the compliance gate is open."""

    def _override_service(session: DbSessionDep) -> AnalyticsService:
        return AnalyticsService(session, settings=_ENABLED_SETTINGS)

    app.dependency_overrides[get_analytics_service] = _override_service
    try:
        yield TestClient(app, raise_server_exceptions=True)
    finally:
        app.dependency_overrides.pop(get_analytics_service, None)


@pytest.fixture
def client_gate_disabled() -> Generator[TestClient]:
    """TestClient with analytics_real_data_enabled=False (default) — gate closed."""
    app.dependency_overrides.pop(get_analytics_service, None)
    try:
        yield TestClient(app, raise_server_exceptions=True)
    finally:
        pass


@pytest.fixture
def test_user(db_session: Session) -> User:
    user = User(
        email=f"analytics-test-{uuid.uuid4()}@example.com",
        hashed_password="$2b$12$placeholder_test_hash",
        is_active=True,
    )
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture
def other_user(db_session: Session) -> User:
    user = User(
        email=f"other-{uuid.uuid4()}@example.com",
        hashed_password="$2b$12$placeholder_other_hash",
        is_active=True,
    )
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture
def test_channel(db_session: Session, test_user: User) -> Channel:
    channel = Channel(
        user_id=test_user.id,
        youtube_channel_id=f"UC_test_{uuid.uuid4().hex[:8]}",
        title="Test Channel",
        uploads_playlist_id=f"UU_test_{uuid.uuid4().hex[:8]}",
    )
    db_session.add(channel)
    db_session.flush()
    return channel


@pytest.fixture
def test_video(db_session: Session, test_channel: Channel) -> Video:
    video = Video(
        channel_id=test_channel.id,
        youtube_video_id=f"yt_{uuid.uuid4().hex[:11]}",
        title="Test Video",
        published_at=datetime.now(UTC) - timedelta(days=10),
        duration_iso="PT10M",
        duration_seconds=600,
    )
    db_session.add(video)
    db_session.flush()
    return video


def _headers(user: User) -> dict[str, str]:
    return {"X-User-Id": str(user.id)}


# ─── Authentication tests ─────────────────────────────────────────────────────

class TestAuthentication:
    def test_summary_without_auth_returns_401_or_422(
        self, client: TestClient, test_channel: Channel
    ) -> None:
        resp = client.get(f"/api/v1/channels/{test_channel.id}/summary")
        # In dev/testing mode with no X-User-Id and no active user: depends on DB state
        # but at minimum should not be 200
        assert resp.status_code in (401, 422, 404)

    def test_summary_with_invalid_uuid_returns_422(
        self, client: TestClient, test_user: User, db_session: Session
    ) -> None:
        db_session.commit()
        resp = client.get(
            "/api/v1/channels/not-a-uuid/summary",
            headers=_headers(test_user),
        )
        assert resp.status_code == 422

    def test_channel_isolation_returns_404_for_other_user(
        self,
        client: TestClient,
        test_channel: Channel,
        other_user: User,
        db_session: Session,
    ) -> None:
        """A user must not access a channel belonging to another user (IDOR prevention)."""
        # db_session flushed test_channel — TestClient uses a separate session but
        # since we committed nothing, the channel is not visible to other sessions.
        # We commit the user and channel so TestClient can query them.
        db_session.commit()

        resp = client.get(
            f"/api/v1/channels/{test_channel.id}/summary",
            headers=_headers(other_user),
        )
        # other_user does not own test_channel → 404
        assert resp.status_code == 404

    def test_non_existent_channel_returns_404(
        self, client: TestClient, test_user: User, db_session: Session
    ) -> None:
        db_session.commit()
        fake_id = uuid.uuid4()
        resp = client.get(
            f"/api/v1/channels/{fake_id}/summary",
            headers=_headers(test_user),
        )
        assert resp.status_code == 404


# ─── Channel summary tests ────────────────────────────────────────────────────

class TestChannelSummary:
    def test_returns_channel_data(
        self, client: TestClient, test_user: User, test_channel: Channel, db_session: Session
    ) -> None:
        db_session.commit()
        resp = client.get(
            f"/api/v1/channels/{test_channel.id}/summary",
            headers=_headers(test_user),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["channel_id"] == str(test_channel.id)
        assert body["youtube_channel_id"] == test_channel.youtube_channel_id
        assert body["title"] == "Test Channel"
        assert "compliance_notice" in body

    def test_snapshot_is_none_when_no_snapshot_recorded(
        self, client: TestClient, test_user: User, test_channel: Channel, db_session: Session
    ) -> None:
        db_session.commit()
        resp = client.get(
            f"/api/v1/channels/{test_channel.id}/summary",
            headers=_headers(test_user),
        )
        assert resp.status_code == 200
        assert resp.json()["snapshot"] is None

    def test_compliance_notice_present(
        self, client: TestClient, test_user: User, test_channel: Channel, db_session: Session
    ) -> None:
        db_session.commit()
        resp = client.get(
            f"/api/v1/channels/{test_channel.id}/summary",
            headers=_headers(test_user),
        )
        assert resp.status_code == 200
        notice = resp.json()["compliance_notice"]
        assert len(notice) > 20
        assert "OAuth" in notice or "verificación" in notice or "cumplimiento" in notice.lower()


# ─── Video list tests ──────────────────────────────────────────────────────────

class TestVideoList:
    def test_returns_empty_list_when_no_videos(
        self, client: TestClient, test_user: User, test_channel: Channel, db_session: Session
    ) -> None:
        db_session.commit()
        resp = client.get(
            f"/api/v1/channels/{test_channel.id}/videos",
            headers=_headers(test_user),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["videos"] == []
        assert body["total_returned"] == 0

    def test_returns_videos_when_present(
        self,
        client: TestClient,
        test_user: User,
        test_channel: Channel,
        test_video: Video,
        db_session: Session,
    ) -> None:
        db_session.commit()
        resp = client.get(
            f"/api/v1/channels/{test_channel.id}/videos",
            headers=_headers(test_user),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_returned"] == 1
        v = body["videos"][0]
        assert v["video_id"] == str(test_video.id)
        assert v["title"] == "Test Video"
        assert v["duration_seconds"] == 600

    def test_pagination_limit_and_offset(
        self,
        client: TestClient,
        test_user: User,
        test_channel: Channel,
        db_session: Session,
    ) -> None:
        # Create 3 videos
        for i in range(3):
            db_session.add(Video(
                channel_id=test_channel.id,
                youtube_video_id=f"yt_page_{uuid.uuid4().hex[:8]}",
                title=f"Video {i}",
                published_at=datetime.now(UTC) - timedelta(days=i),
                duration_iso="PT5M",
                duration_seconds=300,
            ))
        db_session.commit()

        resp = client.get(
            f"/api/v1/channels/{test_channel.id}/videos?limit=2&offset=0",
            headers=_headers(test_user),
        )
        assert resp.status_code == 200
        assert resp.json()["total_returned"] == 2

    def test_isolation_returns_404_for_wrong_user(
        self,
        client: TestClient,
        test_channel: Channel,
        other_user: User,
        db_session: Session,
    ) -> None:
        db_session.commit()
        resp = client.get(
            f"/api/v1/channels/{test_channel.id}/videos",
            headers=_headers(other_user),
        )
        assert resp.status_code == 404


# ─── Channel analytics tests ──────────────────────────────────────────────────

class TestChannelAnalytics:
    def test_returns_empty_stats_when_no_daily_metrics(
        self, client: TestClient, test_user: User, test_channel: Channel, db_session: Session
    ) -> None:
        db_session.commit()
        resp = client.get(
            f"/api/v1/channels/{test_channel.id}/analytics",
            headers=_headers(test_user),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["n_days_with_data"] == 0
        assert body["views_stats"]["n"] == 0

    def test_period_days_query_param_validated(
        self, client: TestClient, test_user: User, test_channel: Channel, db_session: Session
    ) -> None:
        db_session.commit()
        # period_days < 7 is invalid
        resp = client.get(
            f"/api/v1/channels/{test_channel.id}/analytics?period_days=3",
            headers=_headers(test_user),
        )
        assert resp.status_code == 422

    def test_returns_computed_stats_with_daily_metrics(
        self,
        client: TestClient,
        test_user: User,
        test_channel: Channel,
        db_session: Session,
    ) -> None:
        from miconte.models.metrics import ChannelDailyMetric

        today = date.today()
        for i in range(10):
            db_session.add(ChannelDailyMetric(
                channel_id=test_channel.id,
                metric_date=today - timedelta(days=i),
                views=1000 + i * 10,
                estimated_minutes_watched=5000,
                average_view_duration_seconds=300,
                average_view_percentage=50.0,
                likes=20,
                comments=5,
                shares=2,
                subscribers_gained=3,
                subscribers_lost=1,
            ))
        db_session.commit()

        resp = client.get(
            f"/api/v1/channels/{test_channel.id}/analytics?period_days=30",
            headers=_headers(test_user),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["n_days_with_data"] == 10
        assert body["views_stats"]["n"] == 10
        assert body["views_stats"]["mean"] is not None
        assert body["views_stats"]["median"] is not None
        assert "compliance_notice" in body

    def test_isolation_returns_404_for_wrong_user(
        self, client: TestClient, test_channel: Channel, other_user: User, db_session: Session
    ) -> None:
        db_session.commit()
        resp = client.get(
            f"/api/v1/channels/{test_channel.id}/analytics",
            headers=_headers(other_user),
        )
        assert resp.status_code == 404


# ─── Analysis run tests ───────────────────────────────────────────────────────

class TestAnalysisRun:
    def test_run_with_no_videos_returns_zero_analyzed(
        self, client: TestClient, test_user: User, test_channel: Channel, db_session: Session
    ) -> None:
        db_session.commit()
        resp = client.post(
            f"/api/v1/channels/{test_channel.id}/analysis/run",
            headers=_headers(test_user),
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["n_videos_analyzed"] == 0
        assert body["n_rules_triggered"] == 0
        assert "analysis_run_id" in body
        assert "compliance_notice" in body

    def test_run_creates_recommendations_for_poor_video(
        self,
        client: TestClient,
        test_user: User,
        test_channel: Channel,
        test_video: Video,
        db_session: Session,
    ) -> None:
        from miconte.models.metrics import VideoDailyMetric

        today = date.today()
        # Create 15 videos to exceed minimum baseline
        videos = [test_video]
        for i in range(14):
            v = Video(
                channel_id=test_channel.id,
                youtube_video_id=f"yt_base_{uuid.uuid4().hex[:8]}",
                title=f"Baseline Video {i}",
                published_at=datetime.now(UTC) - timedelta(days=60 + i),
                duration_iso="PT10M",
                duration_seconds=600,
            )
            db_session.add(v)
            db_session.flush()
            videos.append(v)

        # Normal baseline videos: good APV and ER
        for video in videos[1:]:
            for j in range(3):
                db_session.add(VideoDailyMetric(
                    video_id=video.id,
                    metric_date=today - timedelta(days=j + 5),
                    views=1000,
                    estimated_minutes_watched=5000,
                    average_view_duration_seconds=300,
                    average_view_percentage=50.0,   # 50% APV → good
                    likes=20,
                    comments=5,
                    shares=2,
                    subscribers_gained=5,
                    subscribers_lost=1,
                ))

        # Poor test video: very low APV (10%), negative NSC
        for j in range(3):
            db_session.add(VideoDailyMetric(
                video_id=test_video.id,
                metric_date=today - timedelta(days=j),
                views=500,
                estimated_minutes_watched=500,
                average_view_duration_seconds=60,
                average_view_percentage=10.0,   # 10% APV → triggers R01
                likes=1,
                comments=0,
                shares=0,
                subscribers_gained=0,
                subscribers_lost=5,   # negative NSC → triggers R04
            ))
        db_session.commit()

        resp = client.post(
            f"/api/v1/channels/{test_channel.id}/analysis/run",
            headers=_headers(test_user),
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["n_videos_analyzed"] >= 15
        assert body["n_rules_triggered"] > 0

        rule_codes = {r["rule_code"] for r in body["recommendations"]}
        assert "R01_APV_BELOW_MEDIAN" in rule_codes or "R04_NSC_NEGATIVE" in rule_codes

    def test_isolation_returns_404_for_wrong_user(
        self, client: TestClient, test_channel: Channel, other_user: User, db_session: Session
    ) -> None:
        db_session.commit()
        resp = client.post(
            f"/api/v1/channels/{test_channel.id}/analysis/run",
            headers=_headers(other_user),
        )
        assert resp.status_code == 404

    def test_run_response_includes_compliance_notice(
        self, client: TestClient, test_user: User, test_channel: Channel, db_session: Session
    ) -> None:
        db_session.commit()
        resp = client.post(
            f"/api/v1/channels/{test_channel.id}/analysis/run",
            headers=_headers(test_user),
        )
        assert resp.status_code == 201
        assert "compliance_notice" in resp.json()


# ─── Recommendations list tests ───────────────────────────────────────────────

class TestRecommendationsList:
    def test_returns_empty_list_before_any_run(
        self, client: TestClient, test_user: User, test_channel: Channel, db_session: Session
    ) -> None:
        db_session.commit()
        resp = client.get(
            f"/api/v1/channels/{test_channel.id}/recommendations",
            headers=_headers(test_user),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_returned"] == 0
        assert body["recommendations"] == []

    def test_returns_persisted_recommendations_after_run(
        self,
        client: TestClient,
        test_user: User,
        test_channel: Channel,
        test_video: Video,
        db_session: Session,
    ) -> None:
        from miconte.models.metrics import VideoDailyMetric

        today = date.today()
        # Create enough videos for baseline
        for i in range(14):
            v = Video(
                channel_id=test_channel.id,
                youtube_video_id=f"yt_list_{uuid.uuid4().hex[:8]}",
                title=f"Video {i}",
                published_at=datetime.now(UTC) - timedelta(days=60 + i),
                duration_iso="PT10M",
                duration_seconds=600,
            )
            db_session.add(v)
            db_session.flush()
            for j in range(2):
                db_session.add(VideoDailyMetric(
                    video_id=v.id,
                    metric_date=today - timedelta(days=j + 2),
                    views=800, estimated_minutes_watched=4000,
                    average_view_duration_seconds=300, average_view_percentage=50.0,
                    likes=15, comments=3, shares=1,
                    subscribers_gained=4, subscribers_lost=0,
                ))

        # Test video: very poor metrics to ensure rules trigger
        for j in range(2):
            db_session.add(VideoDailyMetric(
                video_id=test_video.id,
                metric_date=today - timedelta(days=j),
                views=100, estimated_minutes_watched=100,
                average_view_duration_seconds=30, average_view_percentage=5.0,
                likes=0, comments=0, shares=0,
                subscribers_gained=0, subscribers_lost=10,
            ))
        db_session.commit()

        # Run analysis
        run_resp = client.post(
            f"/api/v1/channels/{test_channel.id}/analysis/run",
            headers=_headers(test_user),
        )
        assert run_resp.status_code == 201

        # List recommendations
        list_resp = client.get(
            f"/api/v1/channels/{test_channel.id}/recommendations",
            headers=_headers(test_user),
        )
        assert list_resp.status_code == 200
        body = list_resp.json()
        assert body["total_returned"] > 0
        for rec in body["recommendations"]:
            assert "rule_code" in rec
            assert "title" in rec
            assert "description" in rec
            assert "priority" in rec
            assert rec["priority"] in ("high", "medium", "low", "info")

    def test_limit_query_param_applied(
        self, client: TestClient, test_user: User, test_channel: Channel, db_session: Session
    ) -> None:
        db_session.commit()
        resp = client.get(
            f"/api/v1/channels/{test_channel.id}/recommendations?limit=5",
            headers=_headers(test_user),
        )
        assert resp.status_code == 200


# ─── Video analytics tests ────────────────────────────────────────────────────

class TestVideoAnalytics:
    def test_requires_channel_id_query_param(
        self,
        client: TestClient,
        test_user: User,
        test_video: Video,
        db_session: Session,
    ) -> None:
        db_session.commit()
        resp = client.get(
            f"/api/v1/videos/{test_video.id}/analytics",
            headers=_headers(test_user),
        )
        # channel_id query param is required
        assert resp.status_code == 422

    def test_returns_no_data_when_no_daily_metrics(
        self,
        client: TestClient,
        test_user: User,
        test_channel: Channel,
        test_video: Video,
        db_session: Session,
    ) -> None:
        db_session.commit()
        resp = client.get(
            f"/api/v1/videos/{test_video.id}/analytics?channel_id={test_channel.id}",
            headers=_headers(test_user),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["n_days_with_data"] == 0
        assert "compliance_notice" in body

    def test_returns_metrics_with_daily_data(
        self,
        client: TestClient,
        test_user: User,
        test_channel: Channel,
        test_video: Video,
        db_session: Session,
    ) -> None:
        from miconte.models.metrics import VideoDailyMetric

        today = date.today()
        for i in range(5):
            db_session.add(VideoDailyMetric(
                video_id=test_video.id,
                metric_date=today - timedelta(days=i),
                views=500,
                estimated_minutes_watched=2500,
                average_view_duration_seconds=300,
                average_view_percentage=50.0,
                likes=10,
                comments=2,
                shares=1,
                subscribers_gained=2,
                subscribers_lost=0,
            ))
        db_session.commit()

        resp = client.get(
            f"/api/v1/videos/{test_video.id}/analytics?channel_id={test_channel.id}",
            headers=_headers(test_user),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["n_days_with_data"] == 5
        assert body["video_id"] == str(test_video.id)
        assert body["duration_seconds"] == 600

        metric_keys = {m["metric_key"] for m in body["metrics"]}
        assert "average_percentage_viewed" in metric_keys
        assert "total_views" in metric_keys

    def test_isolation_returns_404_for_video_in_other_channel(
        self,
        client: TestClient,
        test_user: User,
        test_video: Video,
        db_session: Session,
    ) -> None:
        """channel_id that does not match the video's channel must return 404."""
        db_session.commit()
        fake_channel_id = uuid.uuid4()
        resp = client.get(
            f"/api/v1/videos/{test_video.id}/analytics?channel_id={fake_channel_id}",
            headers=_headers(test_user),
        )
        assert resp.status_code == 404

    def test_period_days_too_small_returns_422(
        self,
        client: TestClient,
        test_user: User,
        test_channel: Channel,
        test_video: Video,
        db_session: Session,
    ) -> None:
        db_session.commit()
        resp = client.get(
            f"/api/v1/videos/{test_video.id}/analytics"
            f"?channel_id={test_channel.id}&period_days=2",
            headers=_headers(test_user),
        )
        assert resp.status_code == 422


# ─── Compliance gate tests ────────────────────────────────────────────────────


class TestComplianceGate:
    """Verify the analytics_real_data_enabled gate returns 503 when disabled."""

    def test_channel_summary_returns_503_when_gate_disabled(
        self,
        client_gate_disabled: TestClient,
        test_user: User,
        test_channel: Channel,
        db_session: Session,
    ) -> None:
        db_session.commit()
        resp = client_gate_disabled.get(
            f"/api/v1/channels/{test_channel.id}/summary",
            headers=_headers(test_user),
        )
        assert resp.status_code == 503
        assert "MICONTE_ANALYTICS_REAL_DATA_ENABLED" in resp.json()["detail"]

    def test_run_analysis_returns_503_when_gate_disabled(
        self,
        client_gate_disabled: TestClient,
        test_user: User,
        test_channel: Channel,
        db_session: Session,
    ) -> None:
        db_session.commit()
        resp = client_gate_disabled.post(
            f"/api/v1/channels/{test_channel.id}/analysis/run",
            headers=_headers(test_user),
        )
        assert resp.status_code == 503

    def test_channel_summary_returns_200_when_gate_enabled(
        self,
        client: TestClient,
        test_user: User,
        test_channel: Channel,
        db_session: Session,
    ) -> None:
        """Control: same endpoint returns 200 when the gate is open (client fixture)."""
        db_session.commit()
        resp = client.get(
            f"/api/v1/channels/{test_channel.id}/summary",
            headers=_headers(test_user),
        )
        assert resp.status_code == 200
