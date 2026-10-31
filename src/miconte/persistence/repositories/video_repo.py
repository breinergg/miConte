"""Video catalog and historical public snapshot repository."""

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from miconte.models.video import Video, VideoPublicSnapshot


class VideoRepository:
    """Repository managing Video metadata and public statistic snapshots."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert_video(
        self,
        *,
        channel_id: uuid.UUID,
        youtube_video_id: str,
        title: str,
        published_at: datetime,
        duration_iso: str,
        duration_seconds: int,
        description: str | None = None,
    ) -> Video:
        stmt = select(Video).where(Video.youtube_video_id == youtube_video_id)
        video = self.session.execute(stmt).scalar_one_or_none()

        if video is None:
            video = Video(
                channel_id=channel_id,
                youtube_video_id=youtube_video_id,
                title=title,
                published_at=published_at,
                duration_iso=duration_iso,
                duration_seconds=duration_seconds,
                description=description,
            )
            self.session.add(video)
        else:
            video.channel_id = channel_id
            video.title = title
            video.published_at = published_at
            video.duration_iso = duration_iso
            video.duration_seconds = duration_seconds
            video.description = description

        self.session.flush()
        return video

    def get_by_id(self, video_id: uuid.UUID) -> Video | None:
        return self.session.get(Video, video_id)

    def get_by_youtube_id(self, youtube_video_id: str) -> Video | None:
        stmt = select(Video).where(Video.youtube_video_id == youtube_video_id)
        return self.session.execute(stmt).scalar_one_or_none()

    def list_by_channel_id(
        self,
        channel_id: uuid.UUID,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Video]:
        stmt = (
            select(Video)
            .where(Video.channel_id == channel_id)
            .order_by(Video.published_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(self.session.execute(stmt).scalars().all())

    def get_all_videos_for_channel(self, channel_id: uuid.UUID) -> list[Video]:
        """Fetch all videos belonging to a channel ordered by publication date."""
        stmt = (
            select(Video)
            .where(Video.channel_id == channel_id)
            .order_by(Video.published_at.desc())
        )
        return list(self.session.execute(stmt).scalars().all())

    def record_public_snapshot(
        self,
        *,
        video_id: uuid.UUID,
        captured_at: datetime,
        view_count: int,
        like_count: int | None,
        comment_count: int | None,
    ) -> VideoPublicSnapshot:
        # The schema constraint (like_count IS NULL OR like_count >= 0) does not permit
        # negative values.  When YouTube returns a negative like_count we must not store
        # it directly; instead we store NULL and record the original value in anomaly_notes
        # so the evidence is preserved without violating the constraint.
        is_anomalous = False
        anomaly_notes: str | None = None
        if like_count is not None and like_count < 0:
            anomaly_notes = (
                f"Negative like_count received from YouTube API: {like_count}. "
                "Stored as NULL to satisfy schema constraint. "
                "Requires technical investigation."
            )
            like_count = None
            is_anomalous = True

        stmt = select(VideoPublicSnapshot).where(
            VideoPublicSnapshot.video_id == video_id,
            VideoPublicSnapshot.captured_at == captured_at,
        )
        snapshot = self.session.execute(stmt).scalar_one_or_none()
        if snapshot is None:
            snapshot = VideoPublicSnapshot(
                video_id=video_id,
                captured_at=captured_at,
                view_count=view_count,
                like_count=like_count,
                comment_count=comment_count,
                is_anomalous=is_anomalous,
                anomaly_notes=anomaly_notes,
            )
            self.session.add(snapshot)
        else:
            snapshot.view_count = view_count
            snapshot.like_count = like_count
            snapshot.comment_count = comment_count
            snapshot.is_anomalous = is_anomalous
            snapshot.anomaly_notes = anomaly_notes

        self.session.flush()
        return snapshot

    def get_latest_public_snapshot(self, video_id: uuid.UUID) -> VideoPublicSnapshot | None:
        stmt = (
            select(VideoPublicSnapshot)
            .where(VideoPublicSnapshot.video_id == video_id)
            .order_by(VideoPublicSnapshot.captured_at.desc())
            .limit(1)
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def get_latest_snapshots_for_channel(
        self, channel_id: uuid.UUID,
    ) -> list[VideoPublicSnapshot]:
        """Fetch the latest snapshot per video for all videos in a channel.

        Uses a lateral-join-style subquery: for each video belonging to the
        channel, picks the snapshot row with the most recent captured_at.
        Returns an empty list when the channel has no videos or no snapshots.
        """
        latest_ts = (
            select(
                VideoPublicSnapshot.video_id,
                func.max(VideoPublicSnapshot.captured_at).label("max_captured"),
            )
            .join(Video, Video.id == VideoPublicSnapshot.video_id)
            .where(Video.channel_id == channel_id)
            .group_by(VideoPublicSnapshot.video_id)
            .subquery()
        )

        stmt = (
            select(VideoPublicSnapshot)
            .join(
                latest_ts,
                (VideoPublicSnapshot.video_id == latest_ts.c.video_id)
                & (VideoPublicSnapshot.captured_at == latest_ts.c.max_captured),
            )
        )
        return list(self.session.execute(stmt).scalars().all())

