"""Unit tests for miConte domain persistence model metadata and constraints."""

from datetime import UTC, datetime

from miconte.models.analysis import AnalysisRun, Recommendation, SyncRun
from miconte.models.channel import Channel
from miconte.models.metrics import VideoDailyMetric
from miconte.models.user import OAuthConnection, User
from miconte.models.video import Video, VideoPublicSnapshot


def test_registered_domain_tables_metadata() -> None:
    """Verify all 12 domain tables are declared in Base.metadata with expected table names."""
    expected_tables = {
        "users",
        "oauth_connections",
        "channels",
        "channel_public_snapshots",
        "videos",
        "video_public_snapshots",
        "channel_daily_metrics",
        "video_daily_metrics",
        "video_period_metrics",
        "sync_runs",
        "analysis_runs",
        "recommendations",
    }
    actual_tables = set(User.metadata.tables.keys())
    assert expected_tables.issubset(actual_tables)


def test_user_and_oauth_model_instantiation() -> None:
    """Verify User and OAuthConnection model attributes."""
    user = User(
        email="creator@example.com",
        hashed_password="argon2_hashed_secret",
        full_name="Test Creator",
        is_active=True,
    )
    assert user.email == "creator@example.com"
    assert user.full_name == "Test Creator"
    assert user.is_active is True

    oauth = OAuthConnection(
        user=user,
        platform="youtube",
        external_channel_id="UC_TEST_CHANNEL_01",
        granted_scopes="https://www.googleapis.com/auth/youtube.readonly",
        encrypted_access_token="enc_payload_access",
        encrypted_refresh_token="enc_payload_refresh",
    )
    assert oauth.platform == "youtube"
    assert oauth.external_channel_id == "UC_TEST_CHANNEL_01"


def test_channel_and_video_model_instantiation() -> None:
    """Verify Channel and Video model fields and relationships."""
    now = datetime.now(UTC)
    channel = Channel(
        youtube_channel_id="UC_1234567890",
        title="Science Channel",
        uploads_playlist_id="UU_1234567890",
        custom_url="@sciencechannel",
    )
    assert channel.uploads_playlist_id == "UU_1234567890"

    video = Video(
        channel=channel,
        youtube_video_id="vid_abc_123",
        title="Physics 101",
        published_at=now,
        duration_iso="PT14M22S",
        duration_seconds=862,
    )
    assert video.duration_seconds == 862
    assert video.duration_iso == "PT14M22S"


def test_public_snapshot_distinguishes_absence_and_zero() -> None:
    """Verify like_count and comment_count support None (hidden) distinct from 0."""
    now = datetime.now(UTC)
    # Creator hid likes and disabled comments
    snapshot_hidden = VideoPublicSnapshot(
        captured_at=now,
        view_count=10000,
        like_count=None,
        comment_count=None,
    )
    assert snapshot_hidden.like_count is None
    assert snapshot_hidden.comment_count is None

    # Video has 0 likes and 0 comments publicly visible
    snapshot_zero = VideoPublicSnapshot(
        captured_at=now,
        view_count=10,
        like_count=0,
        comment_count=0,
    )
    assert snapshot_zero.like_count == 0
    assert snapshot_zero.comment_count == 0
    assert snapshot_hidden.like_count != snapshot_zero.like_count


def test_metrics_models_reach_columns_are_nullable() -> None:
    """Verify impressions and CTR can be omitted when only Analytics API v2 is active."""
    metric = VideoDailyMetric(
        views=150,
        estimated_minutes_watched=450,
        average_view_duration_seconds=180,
        average_view_percentage=45.0,
        likes=12,
        comments=3,
        shares=1,
        subscribers_gained=2,
        subscribers_lost=0,
        thumbnail_impressions=None,
        thumbnail_ctr=None,
        reach_source=None,
        is_anomalous=False,
    )
    assert metric.thumbnail_impressions is None
    assert metric.thumbnail_ctr is None
    assert metric.reach_source is None
    assert metric.is_anomalous is False


def test_analysis_models_instantiation() -> None:
    """Verify SyncRun, AnalysisRun, and Recommendation fields."""
    sync_run = SyncRun(
        sync_type="daily_analytics",
        status="running",
        records_processed=0,
    )
    assert sync_run.status == "running"
    assert sync_run.records_processed == 0

    analysis_run = AnalysisRun(
        analysis_type="cohort_baseline",
        status="completed",
        sample_size_n=25,
        parameters={"window_days": 28},
        summary_results={"median_views": 1250.0},
    )
    assert analysis_run.sample_size_n == 25
    assert analysis_run.summary_results["median_views"] == 1250.0

    recommendation = Recommendation(
        analysis_run=analysis_run,
        rule_code="REC_BASELINE_STABILITY",
        title="Estabilidad de línea base",
        description="Se observa una varianza moderada en el periodo analizado.",
        priority="info",
        metrics_evidence={"n": 25, "iqr": 340},
    )
    assert recommendation.rule_code == "REC_BASELINE_STABILITY"
    assert "causó" not in recommendation.description
