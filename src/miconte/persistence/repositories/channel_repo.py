"""Channel catalog and public snapshot repository."""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from miconte.models.channel import Channel, ChannelPublicSnapshot


class ChannelRepository:
    """Repository managing Channel metadata and point-in-time public snapshots."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert_channel(
        self,
        *,
        user_id: uuid.UUID,
        youtube_channel_id: str,
        title: str,
        uploads_playlist_id: str,
        description: str | None = None,
        custom_url: str | None = None,
        published_at: datetime | None = None,
        thumbnail_url: str | None = None,
    ) -> Channel:
        stmt = select(Channel).where(Channel.youtube_channel_id == youtube_channel_id)
        channel = self.session.execute(stmt).scalar_one_or_none()

        if channel is None:
            channel = Channel(
                user_id=user_id,
                youtube_channel_id=youtube_channel_id,
                title=title,
                uploads_playlist_id=uploads_playlist_id,
                description=description,
                custom_url=custom_url,
                published_at=published_at,
                thumbnail_url=thumbnail_url,
            )
            self.session.add(channel)
        else:
            channel.user_id = user_id
            channel.title = title
            channel.uploads_playlist_id = uploads_playlist_id
            channel.description = description
            channel.custom_url = custom_url
            channel.published_at = published_at
            channel.thumbnail_url = thumbnail_url

        self.session.flush()
        return channel

    def get_by_id(self, channel_id: uuid.UUID) -> Channel | None:
        return self.session.get(Channel, channel_id)

    def get_by_youtube_id(self, youtube_channel_id: str) -> Channel | None:
        stmt = select(Channel).where(Channel.youtube_channel_id == youtube_channel_id)
        return self.session.execute(stmt).scalar_one_or_none()

    def list_by_user_id(self, user_id: uuid.UUID) -> list[Channel]:
        stmt = select(Channel).where(Channel.user_id == user_id).order_by(Channel.title.asc())
        return list(self.session.execute(stmt).scalars().all())

    def record_public_snapshot(
        self,
        *,
        channel_id: uuid.UUID,
        captured_at: datetime,
        view_count: int,
        subscriber_count: int | None,
        video_count: int,
    ) -> ChannelPublicSnapshot:
        stmt = select(ChannelPublicSnapshot).where(
            ChannelPublicSnapshot.channel_id == channel_id,
            ChannelPublicSnapshot.captured_at == captured_at,
        )
        snapshot = self.session.execute(stmt).scalar_one_or_none()
        if snapshot is None:
            snapshot = ChannelPublicSnapshot(
                channel_id=channel_id,
                captured_at=captured_at,
                view_count=view_count,
                subscriber_count=subscriber_count,
                video_count=video_count,
            )
            self.session.add(snapshot)
        else:
            snapshot.view_count = view_count
            snapshot.subscriber_count = subscriber_count
            snapshot.video_count = video_count

        self.session.flush()
        return snapshot

    def get_latest_public_snapshot(self, channel_id: uuid.UUID) -> ChannelPublicSnapshot | None:
        stmt = (
            select(ChannelPublicSnapshot)
            .where(ChannelPublicSnapshot.channel_id == channel_id)
            .order_by(ChannelPublicSnapshot.captured_at.desc())
            .limit(1)
        )
        return self.session.execute(stmt).scalar_one_or_none()

