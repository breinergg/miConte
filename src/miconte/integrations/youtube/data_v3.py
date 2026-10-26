"""Production client for YouTube Data API v3."""

from datetime import datetime
from typing import Any

import httpx

from miconte.integrations.youtube.dto import (
    YouTubeChannelDTO,
    YouTubePlaylistItemDTO,
    YouTubeVideoDTO,
    parse_iso8601_duration_to_seconds,
)
from miconte.integrations.youtube.exceptions import (
    ResourceNotFoundError,
    YouTubeAPIError,
    parse_google_api_error,
)

_DATA_API_BASE_URL = "https://www.googleapis.com/youtube/v3"
_MAX_BATCH_SIZE = 50


class YouTubeDataClient:
    """Production client for YouTube Data API v3 operations."""

    def __init__(
        self,
        api_key: str | None = None,
        http_client: httpx.AsyncClient | None = None,
        base_url: str = _DATA_API_BASE_URL,
    ) -> None:
        self.api_key = api_key
        self._custom_client = http_client
        self.base_url = base_url.rstrip("/")

    async def _send_request(
        self,
        method: str,
        path: str,
        params: dict[str, Any],
        access_token: str | None = None,
    ) -> dict[str, Any]:
        """Execute HTTP request with authentication and typed error handling."""
        headers = {"Accept": "application/json"}
        req_params = dict(params)

        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        elif self.api_key:
            req_params["key"] = self.api_key
        else:
            raise YouTubeAPIError("Neither access_token nor api_key provided for YouTube Data API")

        url = f"{self.base_url}/{path.lstrip('/')}"

        client = self._custom_client or httpx.AsyncClient(timeout=30.0)
        try:
            resp = await client.request(method, url, params=req_params, headers=headers)
        except httpx.RequestError as exc:
            msg = f"HTTP transport error communicating with YouTube Data API: {exc}"
            raise YouTubeAPIError(msg) from exc
        finally:
            if self._custom_client is None:
                await client.aclose()

        if not resp.is_success:
            try:
                error_json = resp.json()
            except Exception:
                error_json = None
            raise parse_google_api_error(resp.status_code, error_json, resp.text)

        return resp.json()  # type: ignore[no-any-return]

    async def get_channel(
        self,
        channel_id: str | None = None,
        mine: bool = False,
        access_token: str | None = None,
    ) -> YouTubeChannelDTO:
        """Fetch channel metadata, uploads playlist ID, and public statistics.

        Must provide either channel_id or mine=True (with access_token).
        """
        params: dict[str, Any] = {
            "part": "snippet,contentDetails,statistics",
        }
        if mine:
            params["mine"] = "true"
            if not access_token:
                raise YouTubeAPIError("Querying mine=True requires an OAuth access_token")
        elif channel_id:
            params["id"] = channel_id
        else:
            raise YouTubeAPIError("Must specify either channel_id or mine=True")

        data = await self._send_request("GET", "channels", params=params, access_token=access_token)
        items = data.get("items", [])
        if not items:
            ident = "mine=true" if mine else f"id={channel_id}"
            raise ResourceNotFoundError(f"YouTube channel not found for {ident}", status_code=404)

        channel_item = items[0]
        snippet = channel_item.get("snippet", {})
        content_details = channel_item.get("contentDetails", {})
        statistics = channel_item.get("statistics", {})

        uploads_id = content_details.get("relatedPlaylists", {}).get("uploads")
        if not uploads_id:
            raise YouTubeAPIError("Channel response missing relatedPlaylists.uploads")

        published_raw = snippet.get("publishedAt")
        published_dt = (
            datetime.fromisoformat(published_raw.replace("Z", "+00:00"))
            if published_raw
            else None
        )

        thumbnails = snippet.get("thumbnails", {})
        thumb_url = (
            thumbnails.get("high", {}).get("url")
            or thumbnails.get("medium", {}).get("url")
            or thumbnails.get("default", {}).get("url")
        )

        hidden_subs = statistics.get("hiddenSubscriberCount", False)
        raw_subs = statistics.get("subscriberCount")
        subscriber_count = int(raw_subs) if raw_subs is not None and not hidden_subs else None

        raw_views = statistics.get("viewCount", "0")
        raw_videos = statistics.get("videoCount", "0")

        return YouTubeChannelDTO(
            youtube_channel_id=channel_item["id"],
            title=snippet.get("title", ""),
            uploads_playlist_id=uploads_id,
            description=snippet.get("description"),
            custom_url=snippet.get("customUrl"),
            published_at=published_dt,
            thumbnail_url=thumb_url,
            view_count=int(raw_views) if raw_views else 0,
            subscriber_count=subscriber_count,
            video_count=int(raw_videos) if raw_videos else 0,
        )

    async def list_playlist_items(
        self,
        playlist_id: str,
        page_token: str | None = None,
        max_results: int = _MAX_BATCH_SIZE,
        access_token: str | None = None,
    ) -> tuple[list[YouTubePlaylistItemDTO], str | None]:
        """Fetch items from a playlist (e.g., uploads playlist) with pagination support."""
        clamped_max = max(1, min(max_results, _MAX_BATCH_SIZE))
        params: dict[str, Any] = {
            "part": "snippet,contentDetails",
            "playlistId": playlist_id,
            "maxResults": clamped_max,
        }
        if page_token:
            params["pageToken"] = page_token

        data = await self._send_request(
            "GET", "playlistItems", params=params, access_token=access_token
        )
        next_page_token: str | None = data.get("nextPageToken")
        items = data.get("items", [])

        dtos: list[YouTubePlaylistItemDTO] = []
        for item in items:
            cd = item.get("contentDetails", {})
            vid_id = cd.get("videoId")
            if not vid_id:
                continue
            snip = item.get("snippet", {})
            pub_raw = snip.get("publishedAt")
            pub_dt = datetime.fromisoformat(pub_raw.replace("Z", "+00:00")) if pub_raw else None

            dtos.append(
                YouTubePlaylistItemDTO(
                    video_id=vid_id,
                    title=snip.get("title"),
                    published_at=pub_dt,
                    position=snip.get("position"),
                )
            )

        return dtos, next_page_token

    async def list_videos_batch(
        self,
        video_ids: list[str],
        access_token: str | None = None,
    ) -> list[YouTubeVideoDTO]:
        """Fetch video metadata and public stats in batches of up to 50 IDs."""
        if not video_ids:
            return []

        unique_ids = list(dict.fromkeys(video_ids))
        results: list[YouTubeVideoDTO] = []

        for i in range(0, len(unique_ids), _MAX_BATCH_SIZE):
            chunk = unique_ids[i : i + _MAX_BATCH_SIZE]
            params = {
                "part": "snippet,contentDetails,statistics",
                "id": ",".join(chunk),
            }
            data = await self._send_request(
                "GET", "videos", params=params, access_token=access_token
            )
            items = data.get("items", [])

            for item in items:
                snippet = item.get("snippet", {})
                content_details = item.get("contentDetails", {})
                statistics = item.get("statistics", {})

                pub_raw = snippet.get("publishedAt")
                pub_dt = (
                    datetime.fromisoformat(pub_raw.replace("Z", "+00:00"))
                    if pub_raw
                    else None
                )

                duration_iso = content_details.get("duration", "PT0S")
                duration_sec = parse_iso8601_duration_to_seconds(duration_iso)

                thumbnails = snippet.get("thumbnails", {})
                thumb_url = (
                    thumbnails.get("high", {}).get("url")
                    or thumbnails.get("medium", {}).get("url")
                    or thumbnails.get("default", {}).get("url")
                )

                raw_views = statistics.get("viewCount", "0")
                raw_likes = statistics.get("likeCount")
                raw_comments = statistics.get("commentCount")

                results.append(
                    YouTubeVideoDTO(
                        youtube_video_id=item["id"],
                        title=snippet.get("title", ""),
                        description=snippet.get("description"),
                        published_at=pub_dt,
                        duration_seconds=duration_sec,
                        duration_iso=duration_iso,
                        thumbnail_url=thumb_url,
                        tags=snippet.get("tags") or [],
                        category_id=snippet.get("categoryId"),
                        default_language=snippet.get("defaultLanguage"),
                        view_count=int(raw_views) if raw_views else 0,
                        like_count=int(raw_likes) if raw_likes is not None else None,
                        comment_count=int(raw_comments) if raw_comments is not None else None,
                    )
                )

        return results
