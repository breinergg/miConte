"""Video catalog and historical public snapshot repository."""

import uuid
from datetime import datetime

from sqlalchemy import select
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
            )
            self.session.add(snapshot)
        else:
            snapshot.view_count = view_count
            snapshot.like_count = like_count
            snapshot.comment_count = comment_count

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

