"""Integration tests for miConte domain persistence and repository contracts against PostgreSQL."""

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from miconte.models.metrics import VideoDailyMetric, VideoPeriodMetric
from miconte.models.video import Video, VideoPublicSnapshot
from miconte.persistence.repositories import (
    AnalysisRepository,
    ChannelRepository,
    MetricsRepository,
    UserRepository,
    VideoRepository,
)
from miconte.persistence.session import get_engine


@pytest.fixture
def db_session() -> Session:  # type: ignore[misc]
    """Provide a transactional SQLAlchemy session for testing."""
    engine = get_engine()
    with Session(engine) as session:
        yield session
        session.rollback()


@pytest.mark.integration
def test_user_and_oauth_persistence_roundtrip(db_session: Session) -> None:
    """Verify creating users and encrypted OAuth connections."""
    user_repo = UserRepository(db_session)
    unique_email = f"creator_{uuid.uuid4().hex[:8]}@example.com"

    user = user_repo.create_user(
        email=unique_email,
        hashed_password="argon2id$v=19$m=65536,t=3,p=4$hashed_secret",
        full_name="Carlos Creador",
    )
    db_session.commit()

    assert user.id is not None
    fetched_user = user_repo.get_by_email(unique_email)
    assert fetched_user is not None
    assert fetched_user.id == user.id
    assert fetched_user.full_name == "Carlos Creador"

    # Upsert OAuth connection with encrypted credentials
    oauth_conn = user_repo.upsert_oauth_connection(
        user_id=user.id,
        external_channel_id="UC_TEST_EXT_CH01",
        granted_scopes="https://www.googleapis.com/auth/youtube.readonly",
        encrypted_access_token="aes256_gcm_ciphertext_access_token",
        encrypted_refresh_token="aes256_gcm_ciphertext_refresh_token",
    )
    db_session.commit()

    assert oauth_conn.id is not None
    assert oauth_conn.encrypted_access_token == "aes256_gcm_ciphertext_access_token"

    # Cleanup
    db_session.delete(fetched_user)
    db_session.commit()


@pytest.mark.integration
def test_user_unique_email_constraint(db_session: Session) -> None:
    """Verify unique constraint on user email raises IntegrityError."""
    user_repo = UserRepository(db_session)
    duplicate_email = f"dup_{uuid.uuid4().hex[:8]}@example.com"

    user1 = user_repo.create_user(email=duplicate_email, hashed_password="pw1")
    db_session.commit()

    with pytest.raises(IntegrityError):
        user_repo.create_user(email=duplicate_email, hashed_password="pw2")
        db_session.commit()

    db_session.rollback()
    db_session.delete(user1)
    db_session.commit()


@pytest.mark.integration
def test_channel_and_video_persistence_with_duration_check(db_session: Session) -> None:
    """Verify channel, video persistence, and duration_seconds >= 0 constraint."""
    user_repo = UserRepository(db_session)
    channel_repo = ChannelRepository(db_session)
    video_repo = VideoRepository(db_session)

    user = user_repo.create_user(
        email=f"vids_{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="hash",
    )
    db_session.commit()

    yt_channel_id = f"UC_{uuid.uuid4().hex[:12]}"
    channel = channel_repo.upsert_channel(
        user_id=user.id,
        youtube_channel_id=yt_channel_id,
        title="Canal de Tecnología",
        uploads_playlist_id=f"UU_{yt_channel_id[3:]}",
        custom_url="@tecnologia",
    )
    db_session.commit()

    now = datetime.now(UTC)
    video = video_repo.upsert_video(
        channel_id=channel.id,
        youtube_video_id=f"vid_{uuid.uuid4().hex[:8]}",
        title="Cómo funciona PostgreSQL",
        published_at=now,
        duration_iso="PT15M30S",
        duration_seconds=930,
    )
    db_session.commit()

    assert video.id is not None
    assert video.duration_seconds == 930

    # Negative duration must be rejected by check constraint
    with pytest.raises(IntegrityError):
        invalid_video = Video(
            channel_id=channel.id,
            youtube_video_id=f"invalid_{uuid.uuid4().hex[:8]}",
            title="Video Inválido",
            published_at=now,
            duration_iso="PT0S",
            duration_seconds=-10,
        )
        db_session.add(invalid_video)
        db_session.commit()

    db_session.rollback()
    # Cleanup via cascade
    db_session.delete(user)
    db_session.commit()


@pytest.mark.integration
def test_foreign_key_referential_integrity(db_session: Session) -> None:
    """Verify inserting a video with non-existent channel_id raises IntegrityError."""
    video = Video(
        channel_id=uuid.uuid4(),  # Random non-existent ID
        youtube_video_id="vid_orphan",
        title="Orphan Video",
        published_at=datetime.now(UTC),
        duration_iso="PT1M",
        duration_seconds=60,
    )
    db_session.add(video)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


@pytest.mark.integration
def test_multi_user_data_isolation(db_session: Session) -> None:
    """Verify channels and videos of User A cannot be accessed under User B's listing."""
    user_repo = UserRepository(db_session)
    channel_repo = ChannelRepository(db_session)

    user_a = user_repo.create_user(
        email=f"usera_{uuid.uuid4().hex[:8]}@example.com", hashed_password="pw"
    )
    user_b = user_repo.create_user(
        email=f"userb_{uuid.uuid4().hex[:8]}@example.com", hashed_password="pw"
    )
    db_session.commit()

    channel_a = channel_repo.upsert_channel(
        user_id=user_a.id,
        youtube_channel_id=f"UC_A_{uuid.uuid4().hex[:8]}",
        title="Canal User A",
        uploads_playlist_id="UU_A",
    )
    channel_b = channel_repo.upsert_channel(
        user_id=user_b.id,
        youtube_channel_id=f"UC_B_{uuid.uuid4().hex[:8]}",
        title="Canal User B",
        uploads_playlist_id="UU_B",
    )
    db_session.commit()

    channels_for_a = channel_repo.list_by_user_id(user_a.id)
    channels_for_b = channel_repo.list_by_user_id(user_b.id)

    assert any(c.id == channel_a.id for c in channels_for_a)
    assert not any(c.id == channel_b.id for c in channels_for_a)

    assert any(c.id == channel_b.id for c in channels_for_b)
    assert not any(c.id == channel_a.id for c in channels_for_b)

    # Deleting User A cascades only User A's channel
    db_session.delete(user_a)
    db_session.commit()

    assert channel_repo.get_by_id(channel_a.id) is None
    assert channel_repo.get_by_id(channel_b.id) is not None

    db_session.delete(user_b)
    db_session.commit()


@pytest.mark.integration
def test_public_snapshot_retention_and_absence_vs_zero(db_session: Session) -> None:
    """Verify historical public snapshot retention, distinguishing absence (None) from zero."""
    user_repo = UserRepository(db_session)
    channel_repo = ChannelRepository(db_session)
    video_repo = VideoRepository(db_session)

    user = user_repo.create_user(
        email=f"snap_{uuid.uuid4().hex[:8]}@example.com", hashed_password="pw"
    )
    channel = channel_repo.upsert_channel(
        user_id=user.id,
        youtube_channel_id=f"UC_SNAP_{uuid.uuid4().hex[:8]}",
        title="Canal Snapshots",
        uploads_playlist_id="UU_SNAP",
    )
    now = datetime.now(UTC)
    video = video_repo.upsert_video(
        channel_id=channel.id,
        youtube_video_id=f"vid_snap_{uuid.uuid4().hex[:8]}",
        title="Video Snapshots",
        published_at=now,
        duration_iso="PT5M",
        duration_seconds=300,
    )
    db_session.commit()

    t1 = now - timedelta(hours=48)
    t2 = now - timedelta(hours=24)
    t3 = now

    # Snapshot 1: Likes enabled, 0 likes, comments enabled, 0 comments
    video_repo.record_public_snapshot(
        video_id=video.id,
        captured_at=t1,
        view_count=50,
        like_count=0,
        comment_count=0,
    )
    # Snapshot 2: Creator hid likes (None) and disabled comments (None)
    video_repo.record_public_snapshot(
        video_id=video.id,
        captured_at=t2,
        view_count=120,
        like_count=None,
        comment_count=None,
    )
    # Snapshot 3: Creator re-enabled likes (5 likes)
    video_repo.record_public_snapshot(
        video_id=video.id,
        captured_at=t3,
        view_count=350,
        like_count=5,
        comment_count=2,
    )
    db_session.commit()

    latest = video_repo.get_latest_public_snapshot(video.id)
    assert latest is not None
    assert latest.captured_at == t3
    assert latest.view_count == 350
    assert latest.like_count == 5

    # Check that all 3 snapshots were retained
    stmt = (
        select(VideoPublicSnapshot)
        .where(VideoPublicSnapshot.video_id == video.id)
        .order_by(VideoPublicSnapshot.captured_at.asc())
    )
    all_snapshots = list(db_session.execute(stmt).scalars().all())
    assert len(all_snapshots) == 3

    assert all_snapshots[0].like_count == 0  # Zero
    assert all_snapshots[1].like_count is None  # Absent (hidden)
    assert all_snapshots[2].like_count == 5  # Positive count

    # Cleanup
    db_session.delete(user)
    db_session.commit()


@pytest.mark.integration
def test_separation_between_public_snapshots_and_daily_metrics(db_session: Session) -> None:
    """Verify cumulative snapshot vs daily interval metric separation."""
    user_repo = UserRepository(db_session)
    channel_repo = ChannelRepository(db_session)
    video_repo = VideoRepository(db_session)
    metrics_repo = MetricsRepository(db_session)

    user = user_repo.create_user(
        email=f"sep_{uuid.uuid4().hex[:8]}@example.com", hashed_password="pw"
    )
    channel = channel_repo.upsert_channel(
        user_id=user.id,
        youtube_channel_id=f"UC_SEP_{uuid.uuid4().hex[:8]}",
        title="Canal Separación",
        uploads_playlist_id="UU_SEP",
    )
    video = video_repo.upsert_video(
        channel_id=channel.id,
        youtube_video_id=f"vid_sep_{uuid.uuid4().hex[:8]}",
        title="Separación de Fuentes",
        published_at=datetime.now(UTC) - timedelta(days=10),
        duration_iso="PT10M",
        duration_seconds=600,
    )
    db_session.commit()

    # Public Snapshot: Cumulative lifetime views
    video_repo.record_public_snapshot(
        video_id=video.id,
        captured_at=datetime.now(UTC),
        view_count=54200,  # Cumulative
        like_count=1820,
        comment_count=94,
    )

    # Analytics API v2: Daily interval views on a specific date
    metric_d1 = metrics_repo.record_video_daily_metric(
        video_id=video.id,
        metric_date=date(2026, 9, 1),
        views=450,  # Day's increment
        estimated_minutes_watched=1800,
        average_view_duration_seconds=240,
        average_view_percentage=40.0,
        likes=35,
        comments=6,
        shares=4,
        subscribers_gained=8,
        subscribers_lost=1,
    )
    metrics_repo.record_video_daily_metric(
        video_id=video.id,
        metric_date=date(2026, 9, 2),
        views=310,
        estimated_minutes_watched=1210,
        average_view_duration_seconds=234,
        average_view_percentage=39.0,
        likes=22,
        comments=3,
        shares=2,
        subscribers_gained=4,
        subscribers_lost=0,
    )
    db_session.commit()

    daily_metrics = metrics_repo.list_video_daily_metrics(
        video.id,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 2),
    )
    assert len(daily_metrics) == 2
    assert daily_metrics[0].views == 450
    assert daily_metrics[1].views == 310

    latest_snapshot = video_repo.get_latest_public_snapshot(video.id)
    assert latest_snapshot is not None
    assert latest_snapshot.view_count == 54200
    # Cumulative public count is orders of magnitude different from daily incremental metrics
    assert latest_snapshot.view_count != metric_d1.views

    # Cleanup
    db_session.delete(user)
    db_session.commit()


@pytest.mark.integration
def test_reach_metrics_optionality_and_source_provenance(db_session: Session) -> None:
    """Verify thumbnail impressions and CTR are strictly nullable with source tracking."""
    user_repo = UserRepository(db_session)
    channel_repo = ChannelRepository(db_session)
    video_repo = VideoRepository(db_session)
    metrics_repo = MetricsRepository(db_session)

    user = user_repo.create_user(
        email=f"reach_{uuid.uuid4().hex[:8]}@example.com", hashed_password="pw"
    )
    channel = channel_repo.upsert_channel(
        user_id=user.id,
        youtube_channel_id=f"UC_REACH_{uuid.uuid4().hex[:8]}",
        title="Canal Reach",
        uploads_playlist_id="UU_REACH",
    )
    video = video_repo.upsert_video(
        channel_id=channel.id,
        youtube_video_id=f"vid_reach_{uuid.uuid4().hex[:8]}",
        title="Reach Test",
        published_at=datetime.now(UTC),
        duration_iso="PT8M",
        duration_seconds=480,
    )
    db_session.commit()

    # Day 1: Only Analytics API v2 ingested (no impressions)
    m1 = metrics_repo.record_video_daily_metric(
        video_id=video.id,
        metric_date=date(2026, 9, 1),
        views=100,
        estimated_minutes_watched=400,
        average_view_duration_seconds=240,
        average_view_percentage=50.0,
        likes=10,
        comments=2,
        shares=1,
        subscribers_gained=1,
        subscribers_lost=0,
        thumbnail_impressions=None,
        thumbnail_ctr=None,
        reach_source=None,
    )
    db_session.commit()
    assert m1.thumbnail_impressions is None
    assert m1.thumbnail_ctr is None
    assert m1.reach_source is None

    # Day 2: Reporting API v1 reach report ingested
    m2 = metrics_repo.record_video_daily_metric(
        video_id=video.id,
        metric_date=date(2026, 9, 2),
        views=250,
        estimated_minutes_watched=1000,
        average_view_duration_seconds=240,
        average_view_percentage=50.0,
        likes=20,
        comments=5,
        shares=3,
        subscribers_gained=3,
        subscribers_lost=0,
        thumbnail_impressions=5000,
        thumbnail_ctr=0.05,
        reach_source="reporting_api_v1",
    )
    db_session.commit()
    assert m2.thumbnail_impressions == 5000
    assert m2.thumbnail_ctr == 0.05
    assert m2.reach_source == "reporting_api_v1"

    # Invalid CTR (> 1.0) must fail database constraint
    with pytest.raises(IntegrityError):
        invalid_metric = VideoDailyMetric(
            video_id=video.id,
            metric_date=date(2026, 9, 3),
            views=10,
            estimated_minutes_watched=40,
            average_view_duration_seconds=240,
            average_view_percentage=50.0,
            likes=1,
            comments=0,
            shares=0,
            subscribers_gained=0,
            subscribers_lost=0,
            thumbnail_ctr=1.5,  # Out of ratio range [0, 1]
        )
        db_session.add(invalid_metric)
        db_session.commit()

    db_session.rollback()
    db_session.delete(user)
    db_session.commit()


@pytest.mark.integration
def test_non_negative_likes_contract_and_anomaly_isolation(db_session: Session) -> None:
    """Verify non-negative likes contract and safe anomaly isolation.

    Ensures values contradicting contract are flagged without altering history.
    """
    user_repo = UserRepository(db_session)
    channel_repo = ChannelRepository(db_session)
    video_repo = VideoRepository(db_session)
    metrics_repo = MetricsRepository(db_session)

    user = user_repo.create_user(
        email=f"like_{uuid.uuid4().hex[:8]}@example.com", hashed_password="pw"
    )
    channel = channel_repo.upsert_channel(
        user_id=user.id,
        youtube_channel_id=f"UC_LIKE_{uuid.uuid4().hex[:8]}",
        title="Canal Likes Contract",
        uploads_playlist_id="UU_LIKE",
    )
    video = video_repo.upsert_video(
        channel_id=channel.id,
        youtube_video_id=f"vid_like_{uuid.uuid4().hex[:8]}",
        title="Likes Contract Video",
        published_at=datetime.now(UTC),
        duration_iso="PT5M",
        duration_seconds=300,
    )
    db_session.commit()

    # Case A: Direct insert of negative likes without is_anomalous=True triggers CheckConstraint
    with pytest.raises(IntegrityError):
        invalid_metric = VideoDailyMetric(
            video_id=video.id,
            metric_date=date(2026, 9, 1),
            views=100,
            estimated_minutes_watched=400,
            average_view_duration_seconds=240,
            average_view_percentage=50.0,
            likes=-5,  # Negative without anomaly flag
            comments=2,
            shares=1,
            subscribers_gained=1,
            subscribers_lost=0,
            is_anomalous=False,
        )
        db_session.add(invalid_metric)
        db_session.commit()

    db_session.rollback()

    # Case B: Repository intercepts negative likes, flags anomaly, and stores safely
    anomalous_metric = metrics_repo.record_video_daily_metric(
        video_id=video.id,
        metric_date=date(2026, 9, 1),
        views=100,
        estimated_minutes_watched=400,
        average_view_duration_seconds=240,
        average_view_percentage=50.0,
        likes=-5,
        comments=2,
        shares=1,
        subscribers_gained=1,
        subscribers_lost=0,
    )
    db_session.commit()

    assert anomalous_metric.id is not None
    assert anomalous_metric.likes == -5
    assert anomalous_metric.is_anomalous is True
    assert anomalous_metric.anomaly_notes is not None
    assert "anomaly requiring technical investigation" in anomalous_metric.anomaly_notes

    db_session.delete(user)
    db_session.commit()


@pytest.mark.integration
def test_video_period_metrics_persistence_and_date_ordering(db_session: Session) -> None:
    """Verify aggregated video period metrics and start_date <= end_date constraint."""
    user_repo = UserRepository(db_session)
    channel_repo = ChannelRepository(db_session)
    video_repo = VideoRepository(db_session)
    metrics_repo = MetricsRepository(db_session)

    user = user_repo.create_user(
        email=f"period_{uuid.uuid4().hex[:8]}@example.com", hashed_password="pw"
    )
    channel = channel_repo.upsert_channel(
        user_id=user.id,
        youtube_channel_id=f"UC_PER_{uuid.uuid4().hex[:8]}",
        title="Canal Period",
        uploads_playlist_id="UU_PER",
    )
    video = video_repo.upsert_video(
        channel_id=channel.id,
        youtube_video_id=f"vid_per_{uuid.uuid4().hex[:8]}",
        title="Period Video",
        published_at=datetime.now(UTC),
        duration_iso="PT5M",
        duration_seconds=300,
    )
    db_session.commit()

    period_metric = metrics_repo.record_video_period_metric(
        video_id=video.id,
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 28),
        views=12500,
        estimated_minutes_watched=50000,
        average_view_duration_seconds=240,
        average_view_percentage=48.0,
        likes=850,
        comments=120,
        shares=45,
        subscribers_gained=110,
        subscribers_lost=15,
    )
    db_session.commit()

    assert period_metric.id is not None
    retrieved = metrics_repo.get_video_period_metric(
        video.id, start_date=date(2026, 8, 1), end_date=date(2026, 8, 28)
    )
    assert retrieved is not None
    assert retrieved.views == 12500

    # Inverted date window (start_date > end_date) must fail check constraint
    with pytest.raises(IntegrityError):
        invalid_period = VideoPeriodMetric(
            video_id=video.id,
            start_date=date(2026, 8, 28),
            end_date=date(2026, 8, 1),  # Inverted!
            views=100,
            estimated_minutes_watched=400,
            average_view_duration_seconds=240,
            average_view_percentage=40.0,
            likes=10,
            comments=1,
            shares=0,
            subscribers_gained=0,
            subscribers_lost=0,
        )
        db_session.add(invalid_period)
        db_session.commit()

    db_session.rollback()
    db_session.delete(user)
    db_session.commit()


@pytest.mark.integration
def test_sync_run_and_analysis_run_lifecycle_and_recommendations(db_session: Session) -> None:
    """Verify execution tracking, sample size heuristics, and deterministic recommendations."""
    user_repo = UserRepository(db_session)
    channel_repo = ChannelRepository(db_session)
    analysis_repo = AnalysisRepository(db_session)

    user = user_repo.create_user(
        email=f"audit_{uuid.uuid4().hex[:8]}@example.com", hashed_password="pw"
    )
    channel = channel_repo.upsert_channel(
        user_id=user.id,
        youtube_channel_id=f"UC_AUD_{uuid.uuid4().hex[:8]}",
        title="Canal Auditoría",
        uploads_playlist_id="UU_AUD",
    )
    db_session.commit()

    # 1. SyncRun lifecycle
    sync_run = analysis_repo.start_sync_run(
        channel_id=channel.id,
        sync_type="daily_analytics",
    )
    db_session.commit()
    assert sync_run.status == "running"

    completed_sync = analysis_repo.complete_sync_run(
        sync_run.id,
        records_processed=28,
        status="completed",
    )
    db_session.commit()
    assert completed_sync.status == "completed"
    assert completed_sync.records_processed == 28
    assert completed_sync.completed_at is not None

    # 2. AnalysisRun lifecycle (heuristic sample size N=24, window 28 days)
    analysis_run = analysis_repo.start_analysis_run(
        channel_id=channel.id,
        analysis_type="cohort_baseline",
        parameters={"window_days": 28, "target_metric": "views"},
    )
    db_session.commit()

    completed_analysis = analysis_repo.complete_analysis_run(
        analysis_run.id,
        status="completed",
        sample_size_n=24,
        summary_results={
            "median_views": 1540.0,
            "iqr_views": 620.0,
            "normality_test": "shapiro",
            "p_value": 0.034,
            "is_normal": False,
        },
    )
    db_session.commit()
    assert completed_analysis.sample_size_n == 24
    assert completed_analysis.summary_results["is_normal"] is False

    # 3. Recommendation recording with non-causal language and evidence
    rec = analysis_repo.record_recommendation(
        analysis_run_id=analysis_run.id,
        channel_id=channel.id,
        rule_code="REC_NON_NORMAL_BASELINE",
        title="Distribución asimétrica de visualizaciones",
        description=(
            "La distribución de visualizaciones presenta una marcada asimetría "
            "(p=0.034 en prueba de Shapiro-Wilk). Se adopta la mediana histórica "
            "(1540 vistas) como estadístico de referencia en lugar de la media aritmética."
        ),
        priority="info",
        metrics_evidence={"n": 24, "median": 1540.0, "shapiro_p": 0.034},
    )
    db_session.commit()

    recs = analysis_repo.list_recommendations(channel.id)
    assert len(recs) == 1
    assert recs[0].id == rec.id
    assert "causó" not in recs[0].description
    assert "provocó" not in recs[0].description

    db_session.delete(user)
    db_session.commit()
