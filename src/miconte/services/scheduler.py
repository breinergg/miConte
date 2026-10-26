"""In-process periodic synchronization scheduler for development and single-worker runtimes.

Coordinates automated, periodic data synchronization across authorized YouTube channels,
enforcing concurrency locking per channel, quota bounds, and idempotent re-executions.
"""

import asyncio
import contextlib
import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from miconte.core.config import Settings
from miconte.models.channel import Channel
from miconte.models.user import OAuthConnection
from miconte.persistence.repositories.analysis_repo import AnalysisRepository
from miconte.persistence.session import create_db_session
from miconte.security.crypto import TokenEncryptionService
from miconte.services.oauth_service import OAuthService
from miconte.services.sync_dto import SchedulerStatusDTO, SyncRunResultDTO
from miconte.services.sync_service import SyncService

logger = logging.getLogger(__name__)


class SyncScheduler:
    """In-memory async scheduler coordinating periodic synchronization across channels."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._is_running = False
        self._task: asyncio.Task[None] | None = None
        self._channel_locks: dict[uuid.UUID, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()
        self._active_jobs: set[str] = set()
        self._last_check_at: datetime | None = None

    def _get_channel_lock(self, channel_id: uuid.UUID) -> asyncio.Lock:
        """Obtain or initialize an asynchronous concurrency lock for a specific channel."""
        if channel_id not in self._channel_locks:
            self._channel_locks[channel_id] = asyncio.Lock()
        return self._channel_locks[channel_id]

    async def start(self) -> None:
        """Start the periodic synchronization loop as a background asyncio task."""
        async with self._global_lock:
            if self._is_running:
                return
            if not self.settings.sync_enabled:
                logger.info(
                    "SyncScheduler is disabled via configuration (MICONTE_SYNC_ENABLED=False)"
                )
                return

            self._is_running = True
            self._task = asyncio.create_task(self._periodic_loop(), name="miconte-sync-scheduler")
            logger.info(
                "SyncScheduler started (interval: %d hours)",
                self.settings.sync_interval_hours,
            )

    async def stop(self) -> None:
        """Gracefully terminate the scheduler background task."""
        async with self._global_lock:
            if not self._is_running:
                return

            self._is_running = False
            if self._task and not self._task.done():
                self._task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._task
            self._task = None
            logger.info("SyncScheduler stopped")

    def get_status(self) -> SchedulerStatusDTO:
        """Expose current operational status and lock counts for monitoring."""
        return SchedulerStatusDTO(
            is_running=self._is_running,
            sync_interval_hours=self.settings.sync_interval_hours,
            active_jobs=sorted(self._active_jobs),
            last_check_at=self._last_check_at,
            channel_locks_active=len([lk for lk in self._channel_locks.values() if lk.locked()]),
        )

    async def trigger_channel_sync(
        self,
        *,
        user_id: uuid.UUID,
        channel_id: uuid.UUID,
        sync_types: list[str] | None = None,
        max_videos: int | None = None,
        session: Session | None = None,
    ) -> SyncRunResultDTO:
        """Execute channel synchronization under per-channel lock to prevent duplicate runs."""
        lock = self._get_channel_lock(channel_id)
        if lock.locked():
            raise RuntimeError(f"Synchronization for channel {channel_id} is already in progress")

        async with lock:
            job_key = f"sync:{channel_id}"
            self._active_jobs.add(job_key)
            try:
                # If caller passed a session, reuse it; otherwise allocate a short-lived session
                if session is not None:
                    return await self._run_sync_with_session(
                        session=session,
                        user_id=user_id,
                        channel_id=channel_id,
                        sync_types=sync_types,
                        max_videos=max_videos,
                    )

                for sess in create_db_session():
                    return await self._run_sync_with_session(
                        session=sess,
                        user_id=user_id,
                        channel_id=channel_id,
                        sync_types=sync_types,
                        max_videos=max_videos,
                    )
                raise RuntimeError("Failed to obtain database session for synchronization")
            finally:
                self._active_jobs.discard(job_key)

    async def _run_sync_with_session(
        self,
        session: Session,
        user_id: uuid.UUID,
        channel_id: uuid.UUID,
        sync_types: list[str] | None,
        max_videos: int | None,
    ) -> SyncRunResultDTO:
        crypto = TokenEncryptionService(
            primary_key=self.settings.token_encryption_key.get_secret_value(),
            primary_key_id=self.settings.token_encryption_key_id,
        )
        oauth_service = OAuthService(
            session=session,
            settings=self.settings,
            crypto_service=crypto,
        )
        service = SyncService(
            session=session,
            settings=self.settings,
            oauth_service=oauth_service,
        )
        return await service.sync_channel(
            user_id=user_id,
            channel_id=channel_id,
            sync_types=sync_types,
            max_videos=max_videos,
        )

    async def _periodic_loop(self) -> None:
        """Main loop periodically checking for channels due for sync."""
        while self._is_running:
            self._last_check_at = datetime.now(UTC)
            try:
                await self._check_and_run_due_channels()
            except Exception as exc:
                logger.error("Error in scheduler periodic execution cycle: %s", exc)

            # Sleep between cycles (minimum 60s for poll interval, default 1 hour)
            poll_seconds = min(3600, self.settings.sync_interval_hours * 3600)
            try:
                await asyncio.sleep(poll_seconds)
            except asyncio.CancelledError:
                break

    async def _check_and_run_due_channels(self) -> None:
        """Identify authorized channels whose last sync exceeds interval_hours."""
        for session in create_db_session():
            stmt = (
                select(Channel, OAuthConnection)
                .join(
                    OAuthConnection,
                    (OAuthConnection.user_id == Channel.user_id)
                    & (OAuthConnection.external_channel_id == Channel.youtube_channel_id)
                    & (OAuthConnection.platform == "youtube")
                    & (OAuthConnection.is_active.is_(True)),
                )
            )
            rows: list[tuple[Channel, OAuthConnection]] = list(session.execute(stmt).all())
            analysis_repo = AnalysisRepository(session)
            threshold = datetime.now(UTC) - timedelta(hours=self.settings.sync_interval_hours)

            for channel, _ in rows:
                latest_run = analysis_repo.get_latest_sync_run(channel.id)
                is_due = (
                    latest_run is None
                    or latest_run.completed_at is None
                    or latest_run.completed_at <= threshold
                )
                if is_due:
                    lock = self._get_channel_lock(channel.id)
                    if not lock.locked():
                        try:
                            await self.trigger_channel_sync(
                                user_id=channel.user_id,
                                channel_id=channel.id,
                                session=session,
                            )
                        except Exception as exc:
                            logger.warning(
                                "Scheduled sync failed for channel %s: %s",
                                channel.youtube_channel_id,
                                exc,
                            )


# Global scheduler singleton
default_scheduler = SyncScheduler(settings=Settings())
