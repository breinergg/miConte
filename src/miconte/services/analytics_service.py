"""Application service that bridges persistence with statistics and recommendations.

Responsibilities:
  - Enforce user ownership (IDOR prevention) for all channel-scoped operations.
  - Aggregate raw daily metrics into statistical inputs.
  - Delegate all statistical computation to miconte.statistics.
  - Delegate all rule evaluation to miconte.recommendations.
  - Persist AnalysisRun records and triggered Recommendations.

No FastAPI dependencies here.  Callers (e.g. API routers) inject the Session.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import numpy as np
from sqlalchemy.orm import Session

from miconte.core.config import Settings, get_settings
from miconte.models.analysis import Recommendation
from miconte.models.channel import Channel
from miconte.models.video import Video
from miconte.persistence.repositories.analysis_repo import AnalysisRepository
from miconte.persistence.repositories.channel_repo import ChannelRepository
from miconte.persistence.repositories.metrics_repo import MetricsRepository
from miconte.persistence.repositories.video_repo import VideoRepository
from miconte.recommendations import evaluate_rules
from miconte.recommendations._models import RecommendationSignal
from miconte.recommendations._rules import MIN_BASELINE_N
from miconte.statistics import compute_ci_95, describe

# ─── Public constants ─────────────────────────────────────────────────────────
DEFAULT_ANALYTICS_PERIOD_DAYS: int = 30
DEFAULT_RECOMMENDATIONS_PERIOD_DAYS: int = 30

COMPLIANCE_NOTICE: str = (
    "AVISO DE CUMPLIMIENTO: miConte aún no cuenta con la verificación de Google Cloud OAuth. "
    "Las métricas derivadas de datos reales de YouTube solo deben mostrarse a usuarios "
    "autenticados con acceso a su propio canal, y no deben redistribuirse públicamente "
    "hasta completar la verificación OAuth de Google Cloud."
)


# ─── Errors ───────────────────────────────────────────────────────────────────

class AnalyticsServiceError(Exception):
    pass


class ChannelNotFoundError(AnalyticsServiceError):
    def __init__(self, channel_id: uuid.UUID) -> None:
        super().__init__(f"Channel '{channel_id}' not found or does not belong to this user.")
        self.channel_id = channel_id


class VideoNotFoundError(AnalyticsServiceError):
    def __init__(self, video_id: uuid.UUID) -> None:
        super().__init__(f"Video '{video_id}' not found or does not belong to this channel.")
        self.video_id = video_id


class AnalyticsNotAvailableError(AnalyticsServiceError):
    """Raised when analytics from real YouTube data is requested but not yet authorized.

    Two independent requirements must be met before enabling this service:

    1. Google OAuth app verification — required when the application requests sensitive
       or restricted scopes, or when it exits the testing/limited-access phase and is
       published for external users. Verification must be completed with Google Cloud
       Console before real user data is processed in production.

    2. YouTube Data API derived-metrics compliance — the YouTube API Services Terms of
       Service and the Additional Terms for Derived Data impose specific obligations on
       applications that compute, store, or display metrics derived from API data
       (e.g. engagement rates, view-percentage aggregates, CTR). miConte must request
       the applicable permissions for its analytics use case and obtain acceptance from
       Google before these features can be enabled for real data.

    Neither approval has been obtained yet. Enable only after both are formally
    confirmed. Set MICONTE_ANALYTICS_REAL_DATA_ENABLED=true at that point.
    """

    MESSAGE: str = (
        "La analítica derivada de datos reales de YouTube no está disponible. "
        "Se deben cumplir dos requisitos independientes antes de habilitarla: "
        "(1) Verificación de la aplicación OAuth de Google, cuando corresponda "
        "según los scopes solicitados y las condiciones de publicación; "
        "(2) Cumplimiento de los requisitos de YouTube Data API para métricas "
        "derivadas, incluyendo la solicitud y aceptación de los permisos "
        "aplicables al caso de uso analítico de miConte. "
        "Ninguna de estas aprobaciones ha sido obtenida todavía. "
        "Contacta al administrador del sistema para más información. "
        "Env var: MICONTE_ANALYTICS_REAL_DATA_ENABLED=true "
        "(solo tras obtener ambas aprobaciones formales)."
    )

    def __init__(self) -> None:
        super().__init__(self.MESSAGE)


# ─── Service result dataclasses ───────────────────────────────────────────────

@dataclass
class ChannelSnapshotData:
    captured_at: str | None
    view_count: int | None
    subscriber_count: int | None
    video_count: int | None


@dataclass
class ChannelSummaryData:
    channel_id: uuid.UUID
    youtube_channel_id: str
    title: str
    description: str | None
    custom_url: str | None
    thumbnail_url: str | None
    snapshot: ChannelSnapshotData | None
    compliance_notice: str


@dataclass
class VideoSnapshotData:
    captured_at: str | None
    view_count: int | None
    like_count: int | None
    comment_count: int | None


@dataclass
class VideoSummaryData:
    video_id: uuid.UUID
    youtube_video_id: str
    title: str
    published_at: str
    duration_seconds: int
    snapshot: VideoSnapshotData | None


@dataclass
class MetricStats:
    """Descriptive statistics for a numeric metric series."""
    n: int
    mean: float | None
    median: float | None
    std: float | None
    min_val: float | None
    max_val: float | None
    ci_95: tuple[float, float] | None
    limitations: list[str] = field(default_factory=list)


@dataclass
class ChannelAnalyticsData:
    channel_id: uuid.UUID
    period_start: date
    period_end: date
    n_days_with_data: int
    views_stats: MetricStats
    apv_stats: MetricStats
    er_stats: MetricStats
    nsc_1k_stats: MetricStats
    compliance_notice: str


@dataclass
class RecommendationData:
    recommendation_id: uuid.UUID
    rule_code: str
    title: str
    description: str
    priority: str
    metrics_evidence: dict[str, Any]
    created_at: str
    video_id: uuid.UUID | None


@dataclass
class RecommendationsRunData:
    analysis_run_id: uuid.UUID
    n_videos_analyzed: int
    n_rules_triggered: int
    recommendations: list[RecommendationData]
    compliance_notice: str


@dataclass
class VideoMetricPoint:
    metric_key: str
    value: float | None
    unit: str
    limitations: list[str] = field(default_factory=list)


@dataclass
class VideoAnalyticsData:
    video_id: uuid.UUID
    channel_id: uuid.UUID
    title: str
    duration_seconds: int
    period_start: date
    period_end: date
    n_days_with_data: int
    metrics: list[VideoMetricPoint]
    compliance_notice: str


# ─── Service ─────────────────────────────────────────────────────────────────

class AnalyticsService:
    """Orchestrates analytics and recommendations for a single HTTP request."""

    def __init__(self, session: Session, settings: Settings | None = None) -> None:
        self._session = session
        self._settings = settings or get_settings()
        self._channel_repo = ChannelRepository(session)
        self._video_repo = VideoRepository(session)
        self._metrics_repo = MetricsRepository(session)
        self._analysis_repo = AnalysisRepository(session)

    # ── Compliance gate ───────────────────────────────────────────────────────

    def _require_real_data_enabled(self) -> None:
        """Raise AnalyticsNotAvailableError unless MICONTE_ANALYTICS_REAL_DATA_ENABLED=true.

        Must be called at the top of every public method that accesses or returns
        data derived from real YouTube APIs.  The pure rules engine (miconte.recommendations)
        and tests using synthetic data are not subject to this gate.
        """
        if not self._settings.analytics_real_data_enabled:
            raise AnalyticsNotAvailableError()

    # ── Ownership guard ──────────────────────────────────────────────────────

    def _verify_channel(self, user_id: uuid.UUID, channel_id: uuid.UUID) -> Channel:
        channel = self._channel_repo.get_by_id(channel_id)
        if channel is None or channel.user_id != user_id:
            raise ChannelNotFoundError(channel_id)
        return channel

    def _verify_video(self, channel_id: uuid.UUID, video_id: uuid.UUID) -> Video:
        video = self._video_repo.get_by_id(video_id)
        if video is None or video.channel_id != channel_id:
            raise VideoNotFoundError(video_id)
        return video

    # ── Public methods ────────────────────────────────────────────────────────

    def get_channel_summary(
        self,
        user_id: uuid.UUID,
        channel_id: uuid.UUID,
    ) -> ChannelSummaryData:
        """Return channel metadata with the latest public snapshot."""
        self._require_real_data_enabled()
        channel = self._verify_channel(user_id, channel_id)
        snap = self._channel_repo.get_latest_public_snapshot(channel_id)

        snapshot_data: ChannelSnapshotData | None = None
        if snap is not None:
            snapshot_data = ChannelSnapshotData(
                captured_at=snap.captured_at.isoformat(),
                view_count=snap.view_count,
                subscriber_count=snap.subscriber_count,
                video_count=snap.video_count,
            )

        return ChannelSummaryData(
            channel_id=channel.id,
            youtube_channel_id=channel.youtube_channel_id,
            title=channel.title,
            description=channel.description,
            custom_url=channel.custom_url,
            thumbnail_url=channel.thumbnail_url,
            snapshot=snapshot_data,
            compliance_notice=COMPLIANCE_NOTICE,
        )

    def get_video_list(
        self,
        user_id: uuid.UUID,
        channel_id: uuid.UUID,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[VideoSummaryData]:
        """Return a paginated list of videos with latest public snapshots."""
        self._require_real_data_enabled()
        self._verify_channel(user_id, channel_id)
        videos = self._video_repo.list_by_channel_id(channel_id, limit=limit, offset=offset)

        result: list[VideoSummaryData] = []
        for video in videos:
            snap = self._video_repo.get_latest_public_snapshot(video.id)
            snap_data: VideoSnapshotData | None = None
            if snap is not None:
                snap_data = VideoSnapshotData(
                    captured_at=snap.captured_at.isoformat(),
                    view_count=snap.view_count,
                    like_count=snap.like_count,
                    comment_count=snap.comment_count,
                )
            result.append(VideoSummaryData(
                video_id=video.id,
                youtube_video_id=video.youtube_video_id,
                title=video.title,
                published_at=video.published_at.isoformat(),
                duration_seconds=video.duration_seconds,
                snapshot=snap_data,
            ))

        return result

    def get_channel_analytics(
        self,
        user_id: uuid.UUID,
        channel_id: uuid.UUID,
        *,
        period_days: int = DEFAULT_ANALYTICS_PERIOD_DAYS,
    ) -> ChannelAnalyticsData:
        """Aggregate and describe channel daily metrics over the requested period."""
        self._require_real_data_enabled()
        self._verify_channel(user_id, channel_id)
        period_end = date.today()
        period_start = period_end - timedelta(days=period_days - 1)

        daily = self._metrics_repo.list_channel_daily_metrics(
            channel_id, start_date=period_start, end_date=period_end
        )

        if not daily:
            empty_stats = MetricStats(
                n=0, mean=None, median=None, std=None,
                min_val=None, max_val=None, ci_95=None,
                limitations=["Sin datos de métricas diarias para el período solicitado"],
            )
            return ChannelAnalyticsData(
                channel_id=channel_id,
                period_start=period_start,
                period_end=period_end,
                n_days_with_data=0,
                views_stats=empty_stats,
                apv_stats=empty_stats,
                er_stats=empty_stats,
                nsc_1k_stats=empty_stats,
                compliance_notice=COMPLIANCE_NOTICE,
            )

        views_arr = [float(d.views) for d in daily]
        apv_arr = [d.average_view_percentage / 100.0 for d in daily]
        er_arr = [
            (d.likes + d.comments + d.shares) / max(d.views, 1)
            for d in daily
        ]
        nsc_arr = [
            (d.subscribers_gained - d.subscribers_lost) / max(d.views, 1) * 1000
            for d in daily
        ]

        return ChannelAnalyticsData(
            channel_id=channel_id,
            period_start=period_start,
            period_end=period_end,
            n_days_with_data=len(daily),
            views_stats=_make_metric_stats(views_arr),
            apv_stats=_make_metric_stats(apv_arr),
            er_stats=_make_metric_stats(er_arr),
            nsc_1k_stats=_make_metric_stats(nsc_arr),
            compliance_notice=COMPLIANCE_NOTICE,
        )

    def list_recommendations(
        self,
        user_id: uuid.UUID,
        channel_id: uuid.UUID,
        *,
        limit: int = 50,
    ) -> list[RecommendationData]:
        """Return persisted recommendations for a channel (most recent first)."""
        self._require_real_data_enabled()
        self._verify_channel(user_id, channel_id)
        recs = self._analysis_repo.list_recommendations(channel_id, limit=limit)
        return [_rec_to_data(r) for r in recs]

    def run_recommendations(
        self,
        user_id: uuid.UUID,
        channel_id: uuid.UUID,
    ) -> RecommendationsRunData:
        """Run the full recommendations analysis for a channel and persist results.

        Steps:
        1. Fetch all videos + their daily metrics for the last 30 days.
        2. Compute per-video metrics (APV, CTR, ER, NSC_1k, velocity_24h).
        3. Compute channel baseline medians across all videos with data.
        4. Build a RecommendationSignal per video and evaluate rules.
        5. Persist AnalysisRun + triggered Recommendations.
        6. Return a summary.
        """
        self._require_real_data_enabled()
        self._verify_channel(user_id, channel_id)
        period_end = date.today()
        period_start = period_end - timedelta(days=DEFAULT_RECOMMENDATIONS_PERIOD_DAYS - 1)

        videos = self._video_repo.get_all_videos_for_channel(channel_id)

        # Compute per-video aggregate metrics over the period
        video_metrics: list[dict[str, Any]] = []
        for video in videos:
            daily = self._metrics_repo.list_video_daily_metrics(
                video.id, start_date=period_start, end_date=period_end
            )
            if not daily:
                continue
            metrics = _aggregate_video_daily(video, daily)
            metrics["video_id"] = video.id
            video_metrics.append(metrics)

        n_videos = len(video_metrics)

        # Compute channel baseline medians (for comparison rules)
        channel_apv_median = _median_of(
            [m["apv"] for m in video_metrics if m.get("apv") is not None]
        )
        channel_ctr_median = _median_of(
            [m["ctr"] for m in video_metrics if m.get("ctr") is not None]
        )
        channel_er_median = _median_of(
            [m["er"] for m in video_metrics if m.get("er") is not None]
        )
        # velocity_24h baseline: median of first-day raw views
        first_day_views = [
            m["first_day_views"]
            for m in video_metrics
            if m.get("first_day_views") is not None
        ]
        channel_velocity_median = (
            float(np.median(first_day_views))
            if len(first_day_views) >= MIN_BASELINE_N
            else None
        )

        # Persist analysis run
        analysis_run = self._analysis_repo.start_analysis_run(
            channel_id=channel_id,
            analysis_type="cohort_baseline",
            parameters={
                "period_start": period_start.isoformat(),
                "period_end": period_end.isoformat(),
                "n_videos_analyzed": n_videos,
            },
        )

        all_recommendations: list[RecommendationData] = []
        n_triggered = 0

        for vm in video_metrics:
            vid = vm["video_id"]

            # Normalize velocity: video's first-day views / channel median first-day views
            velocity_24h: float | None = None
            if (
                vm.get("first_day_views") is not None
                and channel_velocity_median is not None
                and channel_velocity_median > 0
            ):
                velocity_24h = float(vm["first_day_views"]) / channel_velocity_median

            signal = RecommendationSignal(
                channel_id=channel_id,
                video_id=vid,
                apv=vm.get("apv"),
                ctr=vm.get("ctr"),
                er=vm.get("er"),
                nsc_1k=vm.get("nsc_1k"),
                velocity_24h=velocity_24h,
                channel_apv_median=channel_apv_median,
                channel_ctr_median=channel_ctr_median,
                channel_er_median=channel_er_median,
                channel_velocity_median=channel_velocity_median,
                n_videos_baseline=n_videos,
                period_start=period_start,
                period_end=period_end,
            )

            results = evaluate_rules(signal)
            for result in results:
                if not result.triggered:
                    continue
                n_triggered += 1
                rec = self._analysis_repo.record_recommendation(
                    analysis_run_id=analysis_run.id,
                    channel_id=channel_id,
                    video_id=vid,
                    rule_code=result.rule_code,
                    title=result.title,
                    description=result.description,
                    priority=result.priority,
                    metrics_evidence=result.metrics_evidence,
                )
                all_recommendations.append(RecommendationData(
                    recommendation_id=rec.id,
                    rule_code=rec.rule_code,
                    title=rec.title,
                    description=rec.description,
                    priority=rec.priority,
                    metrics_evidence=rec.metrics_evidence,
                    created_at=rec.created_at.isoformat(),
                    video_id=rec.video_id,
                ))

        self._analysis_repo.complete_analysis_run(
            analysis_run.id,
            status="completed",
            sample_size_n=n_videos,
            summary_results={
                "n_videos_analyzed": n_videos,
                "n_rules_triggered": n_triggered,
                "channel_apv_median": channel_apv_median,
                "channel_ctr_median": channel_ctr_median,
                "channel_er_median": channel_er_median,
                "channel_velocity_median": channel_velocity_median,
            },
        )
        self._session.commit()

        return RecommendationsRunData(
            analysis_run_id=analysis_run.id,
            n_videos_analyzed=n_videos,
            n_rules_triggered=n_triggered,
            recommendations=all_recommendations,
            compliance_notice=COMPLIANCE_NOTICE,
        )

    def get_video_analytics(
        self,
        user_id: uuid.UUID,
        channel_id: uuid.UUID,
        video_id: uuid.UUID,
        *,
        period_days: int = DEFAULT_ANALYTICS_PERIOD_DAYS,
    ) -> VideoAnalyticsData:
        """Compute analytics metrics for a single video over the requested period."""
        self._require_real_data_enabled()
        self._verify_channel(user_id, channel_id)
        video = self._verify_video(channel_id, video_id)

        period_end = date.today()
        period_start = period_end - timedelta(days=period_days - 1)

        daily = self._metrics_repo.list_video_daily_metrics(
            video_id, start_date=period_start, end_date=period_end
        )

        if not daily:
            return VideoAnalyticsData(
                video_id=video_id,
                channel_id=channel_id,
                title=video.title,
                duration_seconds=video.duration_seconds,
                period_start=period_start,
                period_end=period_end,
                n_days_with_data=0,
                metrics=[VideoMetricPoint(
                    metric_key="no_data",
                    value=None,
                    unit="n/a",
                    limitations=["Sin datos de métricas diarias para el período solicitado"],
                )],
                compliance_notice=COMPLIANCE_NOTICE,
            )

        agg = _aggregate_video_daily(video, daily)

        metrics: list[VideoMetricPoint] = []

        if agg.get("apv") is not None:
            metrics.append(VideoMetricPoint(
                metric_key="average_percentage_viewed",
                value=agg["apv"],
                unit="ratio",
                limitations=["APV ponderado por visualizaciones diarias"],
            ))

        if agg.get("ctr") is not None:
            metrics.append(VideoMetricPoint(
                metric_key="click_through_rate",
                value=agg["ctr"],
                unit="ratio",
                limitations=["CTR promediado sobre días con datos de impresiones disponibles"],
            ))

        if agg.get("er") is not None:
            metrics.append(VideoMetricPoint(
                metric_key="engagement_rate",
                value=agg["er"],
                unit="ratio",
            ))

        if agg.get("nsc_1k") is not None:
            metrics.append(VideoMetricPoint(
                metric_key="net_subscriber_conversion_per_1k",
                value=agg["nsc_1k"],
                unit="subscribers_per_1k_views",
            ))

        metrics.append(VideoMetricPoint(
            metric_key="total_views",
            value=float(agg.get("total_views", 0)),
            unit="views",
        ))

        return VideoAnalyticsData(
            video_id=video_id,
            channel_id=channel_id,
            title=video.title,
            duration_seconds=video.duration_seconds,
            period_start=period_start,
            period_end=period_end,
            n_days_with_data=len(daily),
            metrics=metrics,
            compliance_notice=COMPLIANCE_NOTICE,
        )


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _aggregate_video_daily(
    video: Video,
    daily: list[Any],
) -> dict[str, Any]:
    """Compute aggregate scalar metrics from a list of VideoDailyMetric rows."""
    total_views = sum(m.views for m in daily)
    total_likes = sum(m.likes for m in daily)
    total_comments = sum(m.comments for m in daily)
    total_shares = sum(m.shares for m in daily)
    total_subs_gained = sum(m.subscribers_gained for m in daily)
    total_subs_lost = sum(m.subscribers_lost for m in daily)

    # APV: views-weighted average of average_view_percentage (stored as %, convert to ratio)
    apv: float | None = None
    if total_views > 0 and video.duration_seconds and video.duration_seconds > 0:
        weighted_pct = sum(m.views * m.average_view_percentage for m in daily) / total_views
        apv = weighted_pct / 100.0

    # CTR: simple mean of non-null thumbnail_ctr values
    ctr_values = [m.thumbnail_ctr for m in daily if m.thumbnail_ctr is not None]
    ctr: float | None = float(np.mean(ctr_values)) if ctr_values else None

    # ER: totals-based
    er: float | None = None
    if total_views > 0:
        er = (total_likes + total_comments + total_shares) / total_views

    # NSC_1k: totals-based
    nsc_1k: float | None = None
    if total_views > 0:
        nsc_1k = (total_subs_gained - total_subs_lost) / total_views * 1000.0

    # Velocity anchor: first day's raw views (earliest date in the series)
    sorted_daily = sorted(daily, key=lambda m: m.metric_date)
    first_day_views: float | None = float(sorted_daily[0].views) if sorted_daily else None

    return {
        "apv": apv,
        "ctr": ctr,
        "er": er,
        "nsc_1k": nsc_1k,
        "total_views": total_views,
        "first_day_views": first_day_views,
    }


def _median_of(values: list[float]) -> float | None:
    if not values:
        return None
    return float(np.median(values))


def _make_metric_stats(values: list[float]) -> MetricStats:
    """Build a MetricStats from a list of float values using miconte.statistics."""
    if not values:
        return MetricStats(
            n=0, mean=None, median=None, std=None,
            min_val=None, max_val=None, ci_95=None,
            limitations=["Sin datos para calcular estadísticas"],
        )

    s = describe(values)
    ci = compute_ci_95(values)

    return MetricStats(
        n=s.n,
        mean=s.mean,
        median=s.median,
        std=s.std,
        min_val=s.min_val,
        max_val=s.max_val,
        ci_95=ci,
        limitations=s.limitations,
    )


def _rec_to_data(rec: Recommendation) -> RecommendationData:
    return RecommendationData(
        recommendation_id=rec.id,
        rule_code=rec.rule_code,
        title=rec.title,
        description=rec.description,
        priority=rec.priority,
        metrics_evidence=rec.metrics_evidence,
        created_at=rec.created_at.isoformat(),
        video_id=rec.video_id,
    )
