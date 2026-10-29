"""Domain synchronization engine for YouTube channels, catalog, and metrics.

Coordinates Data API v3, Analytics API v2, and Reporting API v1 ingestion,
strictly adhering to idempotency, historical snapshot preservation, and quota limits.
"""

import asyncio
import json
import logging
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy.orm import Session

from miconte.core.config import Settings
from miconte.integrations.youtube.analytics_v2 import YouTubeAnalyticsClient
from miconte.integrations.youtube.data_v3 import YouTubeDataClient
from miconte.integrations.youtube.exceptions import (
    InsufficientPermissionsError,
    InvalidQueryError,
    YouTubeAPIError,
)
from miconte.integrations.youtube.reporting_v1 import YouTubeReportingClient
from miconte.models.channel import Channel
from miconte.persistence.repositories.analysis_repo import AnalysisRepository
from miconte.persistence.repositories.channel_repo import ChannelRepository
from miconte.persistence.repositories.metrics_repo import MetricsRepository
from miconte.persistence.repositories.user_repo import UserRepository
from miconte.persistence.repositories.video_repo import VideoRepository
from miconte.security.exceptions import SecurityAuthorizationError
from miconte.services.oauth_service import OAuthService
from miconte.services.sync_dto import (
    SynchronizableChannelDTO,
    SyncRunResultDTO,
    SyncStageResultDTO,
)

logger = logging.getLogger(__name__)

DEFAULT_ANALYTICS_METRICS = [
    "views",
    "estimatedMinutesWatched",
    "averageViewDuration",
    "averageViewPercentage",
    "subscribersGained",
    "subscribersLost",
    "likes",
    "comments",
    "shares",
]


class SyncService:
    """Domain service managing end-to-end synchronization of YouTube channels and metrics."""

    def __init__(
        self,
        session: Session,
        settings: Settings,
        oauth_service: OAuthService,
        data_client: YouTubeDataClient | None = None,
        analytics_client: YouTubeAnalyticsClient | None = None,
        reporting_client: YouTubeReportingClient | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.oauth_service = oauth_service
        self.http_client = http_client

        self.data_client = data_client or YouTubeDataClient(http_client=http_client)
        self.analytics_client = analytics_client or YouTubeAnalyticsClient(http_client=http_client)
        self.reporting_client = reporting_client or YouTubeReportingClient(http_client=http_client)

        self.channel_repo = ChannelRepository(session)
        self.video_repo = VideoRepository(session)
        self.metrics_repo = MetricsRepository(session)
        self.analysis_repo = AnalysisRepository(session)
        self.user_repo = UserRepository(session)

    async def _with_retry(
        self,
        coro_fn: Any,
        operation_name: str,
        max_retries: int = 3,
        base_delay: float = 0.05,
    ) -> Any:
        """Execute async network call with exponential backoff for transient errors."""
        for attempt in range(1, max_retries + 1):
            try:
                return await coro_fn()
            except (InsufficientPermissionsError, SecurityAuthorizationError, InvalidQueryError):
                # Non-recoverable authorization and query errors fail fast
                raise
            except YouTubeAPIError as exc:
                if exc.status_code == 429 or "quotaExceeded" in str(exc):
                    raise
                if exc.status_code and exc.status_code >= 500 and attempt < max_retries:
                    await asyncio.sleep(base_delay * (2 ** (attempt - 1)))
                    continue
                raise
            except (httpx.RequestError, TimeoutError) as exc:
                if attempt < max_retries:
                    await asyncio.sleep(base_delay * (2 ** (attempt - 1)))
                    continue
                raise YouTubeAPIError(
                    f"Network transport error during {operation_name}: {exc}"
                ) from exc

    def list_user_synchronizable_channels(
        self, user_id: uuid.UUID
    ) -> list[SynchronizableChannelDTO]:
        """List channels owned by the user, indicating OAuth connection health and last sync."""
        channels = self.channel_repo.list_by_user_id(user_id)
        result: list[SynchronizableChannelDTO] = []
        for ch in channels:
            conn = self.user_repo.get_oauth_connection(
                user_id=user_id,
                external_channel_id=ch.youtube_channel_id,
                platform="youtube",
            )
            is_connected = conn is not None and conn.is_active
            latest_run = self.analysis_repo.get_latest_sync_run(ch.id)
            result.append(
                SynchronizableChannelDTO(
                    channel_id=ch.id,
                    youtube_channel_id=ch.youtube_channel_id,
                    title=ch.title,
                    is_oauth_connected=is_connected,
                    last_sync_at=latest_run.completed_at if latest_run else None,
                    last_sync_status=latest_run.status if latest_run else None,
                    uploads_playlist_id=ch.uploads_playlist_id,
                )
            )
        return result

    async def sync_channel(
        self,
        *,
        user_id: uuid.UUID,
        channel_id: uuid.UUID,
        sync_types: list[str] | None = None,
        captured_at: datetime | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        max_videos: int | None = None,
    ) -> SyncRunResultDTO:
        """Execute synchronization for a channel across requested stages."""
        observation_time = captured_at or datetime.now(UTC)
        requested_stages = set(
            sync_types
            or [
                "metadata",
                "public_snapshots",
                "analytics_daily",
                "analytics_period",
                "reporting_reach",
            ]
        )
        all_default_stages = {
            "metadata",
            "public_snapshots",
            "analytics_daily",
            "analytics_period",
            "reporting_reach",
        }
        if requested_stages >= all_default_stages or len(requested_stages) > 3:
            resolved_sync_type = "full"
        else:
            resolved_sync_type = ",".join(sorted(requested_stages))[:64]

        # 1. Authorize ownership and existence
        channel = self.channel_repo.get_by_id(channel_id)
        if not channel or channel.user_id != user_id:
            raise SecurityAuthorizationError(
                f"Channel {channel_id} does not exist or is not owned by user {user_id}"
            )

        # 2. Retrieve valid, fresh access token
        try:
            access_token = await self.oauth_service.get_valid_access_token(
                user_id=user_id,
                external_channel_id=channel.youtube_channel_id,
            )
        except Exception as exc:
            # Record failed sync run immediately
            run = self.analysis_repo.start_sync_run(
                channel_id=channel.id,
                sync_type=resolved_sync_type,
                status="failed",
            )
            self.analysis_repo.complete_sync_run(
                run.id,
                records_processed=0,
                status="failed",
                error_message=f"Authentication error: {exc}",
                completed_at=datetime.now(UTC),
            )
            self.session.commit()
            return SyncRunResultDTO(
                sync_run_id=run.id,
                channel_id=channel.id,
                sync_type=resolved_sync_type,
                status="failed",
                started_at=run.started_at,
                completed_at=datetime.now(UTC),
                records_processed=0,
                stages=[
                    SyncStageResultDTO(
                        stage="auth",
                        status="failed",
                        records_processed=0,
                        details=f"Failed to obtain valid OAuth token: {exc}",
                    )
                ],
                error_message=f"OAuth authorization failure: {exc}",
                is_recoverable=False,
            )

        # 3. Start audit record
        sync_run = self.analysis_repo.start_sync_run(
            channel_id=channel.id,
            sync_type=resolved_sync_type,
            status="running",
        )
        self.session.commit()

        stages_result: list[SyncStageResultDTO] = []
        total_records_processed = 0
        overall_error: str | None = None
        has_partial_issues = False
        is_recoverable = False

        # Define analytics date window (account for 48h consolidation latency)
        today = date.today()
        resolved_end = end_date or (today - timedelta(days=2))
        resolved_start = start_date or (
            resolved_end - timedelta(days=self.settings.sync_analytics_days)
        )
        if resolved_start > resolved_end:
            resolved_start = resolved_end - timedelta(days=7)

        limit_videos = max_videos or self.settings.sync_max_videos_per_channel

        try:
            # Stage A: Channel Metadata and Public Snapshot
            if "metadata" in requested_stages or "public_snapshots" in requested_stages:
                stage_dto, count = await self._sync_channel_metadata_and_snapshot(
                    channel=channel,
                    access_token=access_token,
                    captured_at=observation_time,
                    include_snapshot="public_snapshots" in requested_stages,
                )
                stages_result.append(stage_dto)
                total_records_processed += count

            # Stage B: Video Catalog and Public Snapshots
            if "metadata" in requested_stages or "public_snapshots" in requested_stages:
                stage_dto, count = await self._sync_videos_and_snapshots(
                    channel=channel,
                    access_token=access_token,
                    captured_at=observation_time,
                    max_videos=limit_videos,
                    include_snapshots="public_snapshots" in requested_stages,
                )
                stages_result.append(stage_dto)
                total_records_processed += count

            # Stage C: Channel Daily Metrics (YouTube Analytics API v2)
            if "analytics_daily" in requested_stages:
                stage_dto, count = await self._sync_channel_daily_analytics(
                    channel=channel,
                    access_token=access_token,
                    start_date=resolved_start,
                    end_date=resolved_end,
                )
                stages_result.append(stage_dto)
                total_records_processed += count
                if stage_dto.status == "partially_succeeded":
                    has_partial_issues = True

            # Stage D: Video Period & Daily Analytics (Analytics API v2)
            if "analytics_period" in requested_stages:
                stage_dto, count = await self._sync_video_period_analytics(
                    channel=channel,
                    access_token=access_token,
                    start_date=resolved_start,
                    end_date=resolved_end,
                )
                stages_result.append(stage_dto)
                total_records_processed += count
                if stage_dto.status == "partially_succeeded":
                    has_partial_issues = True

            # Stage E: Reporting API v1 Bulk Reach Reports
            if "reporting_reach" in requested_stages:
                stage_dto, count = await self._sync_reporting_reach(
                    channel=channel,
                    access_token=access_token,
                )
                stages_result.append(stage_dto)
                total_records_processed += count
                if stage_dto.status in ("pending", "partially_succeeded"):
                    has_partial_issues = True

            self.session.commit()

        except (InsufficientPermissionsError, SecurityAuthorizationError) as exc:
            self.session.rollback()
            overall_error = f"Authorization error: {exc}"
            is_recoverable = False
        except YouTubeAPIError as exc:
            self.session.rollback()
            overall_error = f"YouTube API error: {exc}"
            is_recoverable = (
                exc.status_code is not None and (exc.status_code >= 500 or exc.status_code == 429)
            )
        except Exception as exc:
            self.session.rollback()
            overall_error = f"Unexpected error during synchronization: {exc}"
            is_recoverable = True

        # Determine final status
        now_dt = datetime.now(UTC)
        if overall_error:
            final_status = "failed"
            summary_json = json.dumps(
                {
                    "error": overall_error,
                    "stages": [s.model_dump() for s in stages_result],
                }
            )
        elif has_partial_issues:
            final_status = "partially_succeeded"
            summary_json = json.dumps(
                {
                    "stages": [s.model_dump() for s in stages_result],
                    "records_processed": total_records_processed,
                }
            )
        else:
            final_status = "succeeded"
            summary_json = json.dumps(
                {
                    "stages": [s.model_dump() for s in stages_result],
                    "records_processed": total_records_processed,
                }
            )

        # Update sync_runs record
        self.analysis_repo.complete_sync_run(
            sync_run_id=sync_run.id,
            records_processed=total_records_processed,
            status=final_status,
            error_message=summary_json,
            completed_at=now_dt,
        )
        self.session.commit()

        return SyncRunResultDTO(
            sync_run_id=sync_run.id,
            channel_id=channel.id,
            sync_type=resolved_sync_type,
            status=final_status,
            started_at=sync_run.started_at,
            completed_at=now_dt,
            records_processed=total_records_processed,
            stages=stages_result,
            error_message=overall_error,
            is_recoverable=is_recoverable,
        )

    async def _sync_channel_metadata_and_snapshot(
        self,
        *,
        channel: Channel,
        access_token: str,
        captured_at: datetime,
        include_snapshot: bool,
    ) -> tuple[SyncStageResultDTO, int]:
        """Fetch channel metadata from Data API v3 and persist point-in-time public snapshot."""
        ch_dto = await self._with_retry(
            lambda: self.data_client.get_channel(
                channel_id=channel.youtube_channel_id,
                access_token=access_token,
            ),
            operation_name="channels.get",
        )

        # Update channel catalog
        self.channel_repo.upsert_channel(
            user_id=channel.user_id,
            youtube_channel_id=ch_dto.youtube_channel_id,
            title=ch_dto.title,
            uploads_playlist_id=ch_dto.uploads_playlist_id,
            description=ch_dto.description,
            custom_url=ch_dto.custom_url,
            published_at=ch_dto.published_at,
            thumbnail_url=ch_dto.thumbnail_url,
        )

        records_count = 1
        if include_snapshot:
            self.channel_repo.record_public_snapshot(
                channel_id=channel.id,
                captured_at=captured_at,
                view_count=ch_dto.view_count,
                subscriber_count=ch_dto.subscriber_count,
                video_count=ch_dto.video_count,
            )
            records_count += 1

        self.session.flush()
        return (
            SyncStageResultDTO(
                stage="channel_metadata_and_snapshot",
                status="succeeded",
                records_processed=records_count,
                details=(
                    "Channel metadata updated and public snapshot recorded at "
                    f"{captured_at.isoformat()}"
                ),
            ),
            records_count,
        )

    async def _sync_videos_and_snapshots(
        self,
        *,
        channel: Channel,
        access_token: str,
        captured_at: datetime,
        max_videos: int,
        include_snapshots: bool,
    ) -> tuple[SyncStageResultDTO, int]:
        """Enumerate videos via uploads playlist and fetch details in batches of up to 50."""
        playlist_id = channel.uploads_playlist_id
        if not playlist_id:
            return (
                SyncStageResultDTO(
                    stage="videos_catalog",
                    status="failed",
                    records_processed=0,
                    details="Channel is missing uploads_playlist_id",
                ),
                0,
            )

        # 1. Paginate playlist items to retrieve video IDs
        collected_video_ids: list[str] = []
        next_page: str | None = None

        while len(collected_video_ids) < max_videos:
            remaining = max_videos - len(collected_video_ids)
            fetch_size = min(50, remaining)
            curr_token = next_page

            async def _fetch(
                tok: str | None = curr_token,
                size: int = fetch_size,
            ) -> tuple[list[Any], str | None]:
                return await self.data_client.list_playlist_items(
                    playlist_id=playlist_id,
                    page_token=tok,
                    max_results=size,
                    access_token=access_token,
                )

            items, next_page = await self._with_retry(
                _fetch,
                operation_name="playlistItems.list",
            )
            if not items:
                break

            for it in items:
                collected_video_ids.append(it.video_id)

            if not next_page:
                break

        if not collected_video_ids:
            return (
                SyncStageResultDTO(
                    stage="videos_catalog",
                    status="succeeded",
                    records_processed=0,
                    details="No published videos found in uploads playlist",
                ),
                0,
            )

        # 2. Fetch video details in chunks of 50
        video_dtos = await self._with_retry(
            lambda: self.data_client.list_videos_batch(
                video_ids=collected_video_ids,
                access_token=access_token,
            ),
            operation_name="videos.list_batch",
        )

        records_count = 0
        for v in video_dtos:
            if not v.published_at:
                continue

            video_entity = self.video_repo.upsert_video(
                channel_id=channel.id,
                youtube_video_id=v.youtube_video_id,
                title=v.title,
                published_at=v.published_at,
                duration_iso=v.duration_iso,
                duration_seconds=v.duration_seconds,
                description=v.description,
            )
            records_count += 1

            if include_snapshots:
                self.video_repo.record_public_snapshot(
                    video_id=video_entity.id,
                    captured_at=captured_at,
                    view_count=v.view_count,
                    like_count=v.like_count,
                    comment_count=v.comment_count,
                )
                records_count += 1

        self.session.flush()
        return (
            SyncStageResultDTO(
                stage="videos_catalog",
                status="succeeded",
                records_processed=records_count,
                details=f"Synchronized {len(video_dtos)} videos and snapshots",
            ),
            records_count,
        )

    async def _sync_channel_daily_analytics(
        self,
        *,
        channel: Channel,
        access_token: str,
        start_date: date,
        end_date: date,
    ) -> tuple[SyncStageResultDTO, int]:
        """Query and persist channel daily time series from YouTube Analytics API v2."""
        try:
            report = await self._with_retry(
                lambda: self.analytics_client.query_report(
                    access_token=access_token,
                    start_date=start_date,
                    end_date=end_date,
                    metrics=DEFAULT_ANALYTICS_METRICS,
                    dimensions=["day"],
                ),
                operation_name="reports.query_channel_daily",
            )
        except Exception as exc:
            return (
                SyncStageResultDTO(
                    stage="analytics_daily",
                    status="partially_succeeded",
                    records_processed=0,
                    details=f"Channel daily analytics query failed or returned no data: {exc}",
                ),
                0,
            )

        headers = [h.name for h in report.column_headers]
        if "day" not in headers:
            return (
                SyncStageResultDTO(
                    stage="analytics_daily",
                    status="succeeded",
                    records_processed=0,
                    details="Analytics report contained no daily dimension rows",
                ),
                0,
            )

        records_count = 0
        for row in report.rows:
            row_dict = dict(zip(headers, row, strict=False))
            day_str = str(row_dict.get("day", ""))
            if not day_str:
                continue

            try:
                row_date = date.fromisoformat(day_str)
            except ValueError:
                continue

            views = int(row_dict.get("views") or 0)
            minutes = int(row_dict.get("estimatedMinutesWatched") or 0)
            duration = int(row_dict.get("averageViewDuration") or 0)
            percentage = float(row_dict.get("averageViewPercentage") or 0.0)
            subs_gained = int(row_dict.get("subscribersGained") or 0)
            subs_lost = int(row_dict.get("subscribersLost") or 0)
            likes = int(row_dict.get("likes") or 0)
            comments = int(row_dict.get("comments") or 0)
            shares = int(row_dict.get("shares") or 0)

            self.metrics_repo.record_channel_daily_metric(
                channel_id=channel.id,
                metric_date=row_date,
                views=views,
                estimated_minutes_watched=minutes,
                average_view_duration_seconds=duration,
                average_view_percentage=percentage,
                likes=likes,
                comments=comments,
                shares=shares,
                subscribers_gained=subs_gained,
                subscribers_lost=subs_lost,
            )
            records_count += 1

        self.session.flush()
        return (
            SyncStageResultDTO(
                stage="analytics_daily",
                status="succeeded",
                records_processed=records_count,
                details=(
                    f"Persisted {records_count} channel daily metrics rows "
                    f"({start_date} to {end_date})"
                ),
            ),
            records_count,
        )

    async def _sync_video_period_analytics(
        self,
        *,
        channel: Channel,
        access_token: str,
        start_date: date,
        end_date: date,
    ) -> tuple[SyncStageResultDTO, int]:
        """Query and persist aggregated metrics per video over the window (dimensions=video)."""
        try:
            report = await self._with_retry(
                lambda: self.analytics_client.query_report(
                    access_token=access_token,
                    start_date=start_date,
                    end_date=end_date,
                    metrics=DEFAULT_ANALYTICS_METRICS,
                    dimensions=["video"],
                    sort="-views",
                    max_results=200,
                ),
                operation_name="reports.query_video_period",
            )
        except Exception as exc:
            return (
                SyncStageResultDTO(
                    stage="analytics_period",
                    status="partially_succeeded",
                    records_processed=0,
                    details=f"Video period metrics query failed: {exc}",
                ),
                0,
            )

        headers = [h.name for h in report.column_headers]
        if "video" not in headers:
            return (
                SyncStageResultDTO(
                    stage="analytics_period",
                    status="succeeded",
                    records_processed=0,
                    details="Video period report contained no video dimension rows",
                ),
                0,
            )

        records_count = 0
        for row in report.rows:
            row_dict = dict(zip(headers, row, strict=False))
            yt_video_id = str(row_dict.get("video", ""))
            if not yt_video_id:
                continue

            video = self.video_repo.get_by_youtube_id(yt_video_id)
            if not video:
                continue

            views = int(row_dict.get("views") or 0)
            minutes = int(row_dict.get("estimatedMinutesWatched") or 0)
            duration = int(row_dict.get("averageViewDuration") or 0)
            percentage = float(row_dict.get("averageViewPercentage") or 0.0)
            subs_gained = int(row_dict.get("subscribersGained") or 0)
            subs_lost = int(row_dict.get("subscribersLost") or 0)
            likes = int(row_dict.get("likes") or 0)
            comments = int(row_dict.get("comments") or 0)
            shares = int(row_dict.get("shares") or 0)

            self.metrics_repo.record_video_period_metric(
                video_id=video.id,
                start_date=start_date,
                end_date=end_date,
                views=views,
                estimated_minutes_watched=minutes,
                average_view_duration_seconds=duration,
                average_view_percentage=percentage,
                likes=likes,
                comments=comments,
                shares=shares,
                subscribers_gained=subs_gained,
                subscribers_lost=subs_lost,
            )
            records_count += 1

        self.session.flush()
        return (
            SyncStageResultDTO(
                stage="analytics_period",
                status="succeeded",
                records_processed=records_count,
                details=(
                    f"Persisted {records_count} video period metric aggregates "
                    f"({start_date} to {end_date})"
                ),
            ),
            records_count,
        )

    async def _sync_reporting_reach(
        self,
        *,
        channel: Channel,
        access_token: str,
    ) -> tuple[SyncStageResultDTO, int]:
        """Manage Reporting API v1 jobs and download reach reports without blocking the worker."""
        report_type = "channel_reach_basic_a1"

        # 1. Check existing jobs for reach report
        try:
            jobs = await self._with_retry(
                lambda: self.reporting_client.list_jobs(access_token=access_token),
                operation_name="reporting.list_jobs",
            )
        except Exception as exc:
            return (
                SyncStageResultDTO(
                    stage="reporting_reach",
                    status="partially_succeeded",
                    records_processed=0,
                    details=f"Failed to list Reporting API jobs: {exc}",
                ),
                0,
            )

        reach_job = next((j for j in jobs if j.report_type_id == report_type), None)
        if not reach_job:
            try:
                reach_job = await self._with_retry(
                    lambda: self.reporting_client.create_job(
                        access_token=access_token,
                        report_type_id=report_type,
                        name=f"miConte {channel.youtube_channel_id} Reach",
                    ),
                    operation_name="reporting.create_job",
                )
            except Exception as exc:
                return (
                    SyncStageResultDTO(
                        stage="reporting_reach",
                        status="partially_succeeded",
                        records_processed=0,
                        details=f"Failed to create Reporting API job '{report_type}': {exc}",
                    ),
                    0,
                )

        # 2. Check generated reports for this job
        try:
            reports = await self._with_retry(
                lambda: self.reporting_client.list_reports(
                    access_token=access_token,
                    job_id=reach_job.job_id,
                ),
                operation_name="reporting.list_reports",
            )
        except Exception as exc:
            return (
                SyncStageResultDTO(
                    stage="reporting_reach",
                    status="partially_succeeded",
                    records_processed=0,
                    details=f"Failed to query reports for job {reach_job.job_id}: {exc}",
                ),
                0,
            )

        if not reports:
            # Normal 48-hour latency window
            return (
                SyncStageResultDTO(
                    stage="reporting_reach",
                    status="pending",
                    records_processed=0,
                    details=(
                        "Reach report job is active; awaiting 48-hour initial report generation "
                        "by YouTube"
                    ),
                ),
                0,
            )

        # 3. Identify reports that have not been ingested yet, including restatement detection.
        # A restatement is a new YouTube report_id covering the same (start, end) period with a
        # strictly newer create_time. Only the newer version is allowed through; equal or older
        # create_times for an already-ingested period are skipped to avoid downgrading data.
        processed_ids = self.analysis_repo.get_processed_report_ids(channel.id)
        new_reports = []
        restatement_ids: set[str] = set()  # report_ids that replace an already-ingested period
        for rep in reports:
            if rep.report_id in processed_ids:
                # Exact same report already committed — skip unconditionally.
                continue
            if rep.start_time and rep.end_time:
                existing = self.analysis_repo.get_latest_ingestion_for_period(
                    channel.id, rep.start_time, rep.end_time, job_id=rep.job_id
                )
                if existing is not None:
                    # An ingestion exists for this period. Allow only if this report is strictly
                    # newer; otherwise skip to avoid replacing good data with an older version.
                    if (
                        rep.create_time is not None
                        and existing.report_create_time is not None
                        and rep.create_time > existing.report_create_time
                    ):
                        new_reports.append(rep)
                        restatement_ids.add(rep.report_id)
                    # If either create_time is absent we cannot compare versions; skip safely.
                    continue
            new_reports.append(rep)

        if not new_reports:
            return (
                SyncStageResultDTO(
                    stage="reporting_reach",
                    status="succeeded",
                    records_processed=0,
                    details=(
                        f"All {len(reports)} generated reach reports have already been ingested"
                    ),
                ),
                0,
            )

        total_rows_updated = 0
        newly_processed_count = 0

        for rep in new_reports:
            download_url = rep.download_url

            async def _download(url: str = download_url) -> Any:
                return await self.reporting_client.download_report_csv(
                    access_token=access_token,
                    download_url=url,
                )

            try:
                rows = await self._with_retry(
                    _download,
                    operation_name=f"reporting.download_csv_{rep.report_id}",
                )
            except Exception as exc:
                logger.warning(
                    "Failed to download or validate CSV for report %s: %s",
                    rep.report_id,
                    exc,
                )
                continue

            # For restatements, clear existing reach data for the period before inserting
            # the new rows. This prevents metric_date rows absent from the newer report
            # version from retaining stale impressions from the superseded version.
            if rep.report_id in restatement_ids and rep.start_time and rep.end_time:
                period_start_date = rep.start_time.date()
                # end_time is exclusive per the YouTube Reporting API contract: first
                # extract the date, then subtract 1 to get the last covered metric_date.
                period_end_date = rep.end_time.date() - timedelta(days=1)
                self.metrics_repo.clear_reach_metrics_for_channel_period(
                    channel_id=channel.id,
                    start_date=period_start_date,
                    end_date=period_end_date,
                )

            rows_for_this_report = 0
            for row in rows:
                video = self.video_repo.get_by_youtube_id(row.video_id)
                if not video:
                    continue

                self.metrics_repo.upsert_video_daily_reach(
                    video_id=video.id,
                    metric_date=row.date,
                    thumbnail_impressions=row.video_thumbnail_impressions,
                    thumbnail_ctr=row.video_thumbnail_impressions_ctr,
                    reach_source="reporting_api_v1",
                )
                rows_for_this_report += 1

            # Persist the ingestion record only after all rows have been flushed.
            # Written inside the same transaction as the metrics: if the outer handler
            # rolls back, this record disappears too — the report will be re-attempted.
            self.analysis_repo.record_report_ingestion(
                channel_id=channel.id,
                report_id=rep.report_id,
                job_id=rep.job_id,
                report_period_start=rep.start_time,
                report_period_end=rep.end_time,
                report_create_time=rep.create_time,
                rows_ingested=rows_for_this_report,
            )
            total_rows_updated += rows_for_this_report
            newly_processed_count += 1

        self.session.flush()
        return (
            SyncStageResultDTO(
                stage="reporting_reach",
                status="succeeded",
                records_processed=total_rows_updated,
                details=(
                    f"Ingested {total_rows_updated} reach rows across "
                    f"{newly_processed_count} report files"
                ),
            ),
            total_rows_updated,
        )
