"""Repository for private analytical metrics time series and period aggregations."""

import uuid
from datetime import date

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from miconte.models.metrics import ChannelDailyMetric, VideoDailyMetric, VideoPeriodMetric
from miconte.models.video import Video


class MetricsRepository:
    """Repository handling private Analytics API v2 and Reporting API v1 metrics."""

    def __init__(self, session: Session) -> None:
        self.session = session

    # -------------------------------------------------------------------------
    # Channel Daily Metrics
    # -------------------------------------------------------------------------
    def record_channel_daily_metric(
        self,
        *,
        channel_id: uuid.UUID,
        metric_date: date,
        views: int,
        estimated_minutes_watched: int,
        average_view_duration_seconds: int,
        average_view_percentage: float,
        likes: int,
        comments: int,
        shares: int,
        subscribers_gained: int,
        subscribers_lost: int,
        is_anomalous: bool = False,
        anomaly_notes: str | None = None,
    ) -> ChannelDailyMetric:
        # Check contract: likes must be non-negative event count. If negative, isolate as anomaly.
        if likes < 0:
            is_anomalous = True
            anomaly_notes = (
                f"Negative likes count ({likes}) received from upstream; "
                "isolated as anomaly requiring technical investigation."
            )

        stmt = select(ChannelDailyMetric).where(
            ChannelDailyMetric.channel_id == channel_id,
            ChannelDailyMetric.metric_date == metric_date,
        )
        record = self.session.execute(stmt).scalar_one_or_none()

        if record is None:
            record = ChannelDailyMetric(
                channel_id=channel_id,
                metric_date=metric_date,
                views=views,
                estimated_minutes_watched=estimated_minutes_watched,
                average_view_duration_seconds=average_view_duration_seconds,
                average_view_percentage=average_view_percentage,
                likes=likes,
                comments=comments,
                shares=shares,
                subscribers_gained=subscribers_gained,
                subscribers_lost=subscribers_lost,
                is_anomalous=is_anomalous,
                anomaly_notes=anomaly_notes,
            )
            self.session.add(record)
        else:
            record.views = views
            record.estimated_minutes_watched = estimated_minutes_watched
            record.average_view_duration_seconds = average_view_duration_seconds
            record.average_view_percentage = average_view_percentage
            record.likes = likes
            record.comments = comments
            record.shares = shares
            record.subscribers_gained = subscribers_gained
            record.subscribers_lost = subscribers_lost
            record.is_anomalous = is_anomalous
            record.anomaly_notes = anomaly_notes

        self.session.flush()
        return record

    def list_channel_daily_metrics(
        self,
        channel_id: uuid.UUID,
        *,
        start_date: date,
        end_date: date,
    ) -> list[ChannelDailyMetric]:
        stmt = (
            select(ChannelDailyMetric)
            .where(
                ChannelDailyMetric.channel_id == channel_id,
                ChannelDailyMetric.metric_date >= start_date,
                ChannelDailyMetric.metric_date <= end_date,
            )
            .order_by(ChannelDailyMetric.metric_date.asc())
        )
        return list(self.session.execute(stmt).scalars().all())

    # -------------------------------------------------------------------------
    # Video Daily Metrics
    # -------------------------------------------------------------------------
    def record_video_daily_metric(
        self,
        *,
        video_id: uuid.UUID,
        metric_date: date,
        views: int,
        estimated_minutes_watched: int,
        average_view_duration_seconds: int,
        average_view_percentage: float,
        likes: int,
        comments: int,
        shares: int,
        subscribers_gained: int,
        subscribers_lost: int,
        thumbnail_impressions: int | None = None,
        thumbnail_ctr: float | None = None,
        reach_source: str | None = None,
        is_anomalous: bool = False,
        anomaly_notes: str | None = None,
    ) -> VideoDailyMetric:
        # Check contract: likes must be non-negative event count. If negative, isolate as anomaly.
        if likes < 0:
            is_anomalous = True
            anomaly_notes = (
                f"Negative likes count ({likes}) received from upstream; "
                "isolated as anomaly requiring technical investigation."
            )

        stmt = select(VideoDailyMetric).where(
            VideoDailyMetric.video_id == video_id,
            VideoDailyMetric.metric_date == metric_date,
        )
        record = self.session.execute(stmt).scalar_one_or_none()

        if record is None:
            record = VideoDailyMetric(
                video_id=video_id,
                metric_date=metric_date,
                views=views,
                estimated_minutes_watched=estimated_minutes_watched,
                average_view_duration_seconds=average_view_duration_seconds,
                average_view_percentage=average_view_percentage,
                likes=likes,
                comments=comments,
                shares=shares,
                subscribers_gained=subscribers_gained,
                subscribers_lost=subscribers_lost,
                thumbnail_impressions=thumbnail_impressions,
                thumbnail_ctr=thumbnail_ctr,
                reach_source=reach_source,
                is_anomalous=is_anomalous,
                anomaly_notes=anomaly_notes,
            )
            self.session.add(record)
        else:
            record.views = views
            record.estimated_minutes_watched = estimated_minutes_watched
            record.average_view_duration_seconds = average_view_duration_seconds
            record.average_view_percentage = average_view_percentage
            record.likes = likes
            record.comments = comments
            record.shares = shares
            record.subscribers_gained = subscribers_gained
            record.subscribers_lost = subscribers_lost
            record.thumbnail_impressions = thumbnail_impressions
            record.thumbnail_ctr = thumbnail_ctr
            record.reach_source = reach_source
            record.is_anomalous = is_anomalous
            record.anomaly_notes = anomaly_notes

        self.session.flush()
        return record

    def upsert_video_daily_reach(
        self,
        *,
        video_id: uuid.UUID,
        metric_date: date,
        thumbnail_impressions: int,
        thumbnail_ctr: float | None = None,
        reach_source: str = "reporting_api_v1",
    ) -> VideoDailyMetric:
        """Upsert reach metrics (impressions and CTR) into video_daily_metrics."""
        stmt = select(VideoDailyMetric).where(
            VideoDailyMetric.video_id == video_id,
            VideoDailyMetric.metric_date == metric_date,
        )
        record = self.session.execute(stmt).scalar_one_or_none()
        if record is None:
            record = VideoDailyMetric(
                video_id=video_id,
                metric_date=metric_date,
                views=0,
                estimated_minutes_watched=0,
                average_view_duration_seconds=0,
                average_view_percentage=0.0,
                likes=0,
                comments=0,
                shares=0,
                subscribers_gained=0,
                subscribers_lost=0,
                thumbnail_impressions=thumbnail_impressions,
                thumbnail_ctr=thumbnail_ctr,
                reach_source=reach_source,
            )
            self.session.add(record)
        else:
            record.thumbnail_impressions = thumbnail_impressions
            record.thumbnail_ctr = thumbnail_ctr
            record.reach_source = reach_source

        self.session.flush()
        return record

    def list_video_daily_metrics(
        self,
        video_id: uuid.UUID,
        *,
        start_date: date,
        end_date: date,
    ) -> list[VideoDailyMetric]:
        stmt = (
            select(VideoDailyMetric)
            .where(
                VideoDailyMetric.video_id == video_id,
                VideoDailyMetric.metric_date >= start_date,
                VideoDailyMetric.metric_date <= end_date,
            )
            .order_by(VideoDailyMetric.metric_date.asc())
        )
        return list(self.session.execute(stmt).scalars().all())

    # -------------------------------------------------------------------------
    # Video Period Aggregated Metrics
    # -------------------------------------------------------------------------
    def record_video_period_metric(
        self,
        *,
        video_id: uuid.UUID,
        start_date: date,
        end_date: date,
        views: int,
        estimated_minutes_watched: int,
        average_view_duration_seconds: int,
        average_view_percentage: float,
        likes: int,
        comments: int,
        shares: int,
        subscribers_gained: int,
        subscribers_lost: int,
        is_anomalous: bool = False,
        anomaly_notes: str | None = None,
    ) -> VideoPeriodMetric:
        if likes < 0:
            is_anomalous = True
            anomaly_notes = (
                f"Negative likes count ({likes}) received from upstream; "
                "isolated as anomaly requiring technical investigation."
            )

        stmt = select(VideoPeriodMetric).where(
            VideoPeriodMetric.video_id == video_id,
            VideoPeriodMetric.start_date == start_date,
            VideoPeriodMetric.end_date == end_date,
        )
        record = self.session.execute(stmt).scalar_one_or_none()

        if record is None:
            record = VideoPeriodMetric(
                video_id=video_id,
                start_date=start_date,
                end_date=end_date,
                views=views,
                estimated_minutes_watched=estimated_minutes_watched,
                average_view_duration_seconds=average_view_duration_seconds,
                average_view_percentage=average_view_percentage,
                likes=likes,
                comments=comments,
                shares=shares,
                subscribers_gained=subscribers_gained,
                subscribers_lost=subscribers_lost,
                is_anomalous=is_anomalous,
                anomaly_notes=anomaly_notes,
            )
            self.session.add(record)
        else:
            record.views = views
            record.estimated_minutes_watched = estimated_minutes_watched
            record.average_view_duration_seconds = average_view_duration_seconds
            record.average_view_percentage = average_view_percentage
            record.likes = likes
            record.comments = comments
            record.shares = shares
            record.subscribers_gained = subscribers_gained
            record.subscribers_lost = subscribers_lost
            record.is_anomalous = is_anomalous
            record.anomaly_notes = anomaly_notes

        self.session.flush()
        return record

    def get_video_period_metric(
        self,
        video_id: uuid.UUID,
        *,
        start_date: date,
        end_date: date,
    ) -> VideoPeriodMetric | None:
        stmt = select(VideoPeriodMetric).where(
            VideoPeriodMetric.video_id == video_id,
            VideoPeriodMetric.start_date == start_date,
            VideoPeriodMetric.end_date == end_date,
        )
        return self.session.execute(stmt).scalar_one_or_none()

    # -------------------------------------------------------------------------
    # Reporting API reach: restatement support
    # -------------------------------------------------------------------------

    def clear_reach_metrics_for_channel_period(
        self,
        channel_id: uuid.UUID,
        start_date: date,
        end_date: date,
    ) -> int:
        """NULL out reach fields for all video_daily_metrics rows in the given date range
        for the specified channel.

        Used before applying a Reporting API restatement so that metric_date rows absent
        from the newer report version do not retain stale impressions from the old version.
        Only affects reach fields (thumbnail_impressions, thumbnail_ctr, reach_source);
        analytics fields (views, likes, etc.) are untouched.
        Restricted to rows whose reach_source is 'reporting_api_v1'.
        Returns the count of rows cleared.
        """
        video_id_subq = (
            select(Video.id).where(Video.channel_id == channel_id).scalar_subquery()
        )
        stmt = (
            update(VideoDailyMetric)
            .where(
                VideoDailyMetric.video_id.in_(video_id_subq),
                VideoDailyMetric.metric_date >= start_date,
                VideoDailyMetric.metric_date <= end_date,
                VideoDailyMetric.reach_source == "reporting_api_v1",
            )
            .values(thumbnail_impressions=None, thumbnail_ctr=None, reach_source=None)
            .execution_options(synchronize_session="fetch")
        )
        from sqlalchemy.engine import CursorResult

        result: CursorResult[tuple[()]] = self.session.execute(stmt)  # type: ignore[assignment]
        self.session.flush()
        return result.rowcount

