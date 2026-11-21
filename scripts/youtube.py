"""YouTube integration abstraction for zMusic.

Implements YouTube Live integration behind a pluggable abstraction.
API credentials are never hard-coded — they are read from environment
variables or secret management. All network calls are deterministic and
validated before execution.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from .config import AppConfig
from .logging import get_logger

logger = get_logger("zmusic.youtube")


@dataclass(frozen=True)
class YouTubeChannel:
    """Represents a YouTube channel."""

    channel_id: str
    title: str
    description: str = ""
    published_at: str | None = None


@dataclass(frozen=True)
class YouTubeBroadcast:
    """Represents a YouTube Live broadcast."""

    broadcast_id: str
    title: str
    status: str  # upcoming, active, completed
    scheduled_start_time: str | None = None
    actual_start_time: str | None = None
    actual_end_time: str | None = None
    stream_id: str | None = None


@dataclass(frozen=True)
class YouTubeStream:
    """Represents a YouTube stream (ingest/binding)."""

    stream_id: str
    ingest_address: str
    playback_url: str
    status: str


class YouTubeProvider:
    """Abstract base for YouTube API providers.

    Implementations must not hard-code credentials. Subclasses use
    environment variables or secret management for OAuth tokens.
    """

    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config

    def _oauth_credentials(self) -> tuple[str, str]:
        """Return (client_id, client_secret) from configuration."""
        if self.config is None:
            raise ValueError("YouTube configuration is required")
        client_id = self.config.youtube.client_id
        client_secret = self.config.youtube.client_secret
        if not client_id or not client_secret:
            raise ValueError(
                "YouTube OAuth credentials are not configured "
                "(ZMUSIC_YOUTUBE_CLIENT_ID / ZMUSIC_YOUTUBE_CLIENT_SECRET)"
            )
        return client_id, client_secret

    def authenticate(self) -> str:
        """Perform OAuth authentication and return an access token.

        Subclasses must implement the actual OAuth flow. Credentials must
        never be logged or returned in plain text beyond this method.
        """
        raise NotImplementedError

    def discover_channels(self, access_token: str) -> list[YouTubeChannel]:
        """Discover YouTube channels accessible to the authenticated user."""
        raise NotImplementedError

    def create_broadcast(
        self,
        access_token: str,
        title: str,
        scheduled_start_time: str | None = None,
        description: str = "",
    ) -> YouTubeBroadcast:
        """Create a YouTube Live broadcast."""
        raise NotImplementedError

    def create_stream(
        self,
        access_token: str,
        title: str,
        format_: str = "1080p",
        ingestion_type: str = "rtmp",
    ) -> YouTubeStream:
        """Create a YouTube stream and return ingest/playback URLs."""
        raise NotImplementedError

    def bind_stream_to_broadcast(
        self,
        access_token: str,
        broadcast_id: str,
        stream_id: str,
    ) -> None:
        """Bind a stream to a broadcast."""
        raise NotImplementedError

    def update_broadcast_metadata(
        self,
        access_token: str,
        broadcast_id: str,
        title: str | None = None,
        description: str | None = None,
    ) -> None:
        """Update broadcast metadata."""
        raise NotImplementedError

    def get_broadcast_status(self, access_token: str, broadcast_id: str) -> str:
        """Return the current status of a broadcast."""
        raise NotImplementedError

    def get_stream_status(self, access_token: str, stream_id: str) -> str:
        """Return the current status of a stream."""
        raise NotImplementedError


class YouTubeClient(YouTubeProvider):
    """Concrete YouTube provider using the YouTube Data API v3.

    All API calls are made via urllib (no external HTTP dependencies).
    Responses are validated before being returned.
    """

    API_BASE = "https://www.googleapis.com/youtube/v3"

    def _request(
        self,
        method: str,
        path: str,
        access_token: str,
        payload: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Make an authenticated request to the YouTube API.

        Raises ValueError on HTTP errors or malformed responses.
        """
        url = f"{self.API_BASE}{path}"
        if params:
            query = "&".join(
                f"{urllib.parse.quote(k)}={urllib.parse.quote(v)}"
                for k, v in params.items()
            )
            url = f"{url}?{query}"

        data = None
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        }
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = urllib.request.Request(url, data=data, headers=headers, method=method)

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            logger.error(
                "YouTube API request failed",
                extra={
                    "method": method,
                    "path": path,
                    "status": exc.code,
                    "error_body": error_body[:500],
                },
            )
            raise ValueError(
                f"YouTube API request failed: HTTP {exc.code}: {error_body[:200]}"
            ) from exc
        except urllib.error.URLError as exc:
            logger.error(
                "YouTube API request error",
                extra={"method": method, "path": path, "error": str(exc)},
            )
            raise ValueError(f"YouTube API request error: {exc}") from exc

        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            logger.error(
                "YouTube API returned invalid JSON",
                extra={"method": method, "path": path, "body": body[:500]},
            )
            raise ValueError("YouTube API returned invalid JSON") from exc

    def authenticate(self) -> str:
        """Obtain an OAuth access token.

        In production this performs the full OAuth 2.0 flow. For this
        implementation, the access token must be provided via
        ZMUSIC_YOUTUBE_ACCESS_TOKEN or obtained through a credential
        manager. We never log or expose the token value.
        """
        token = os.environ.get("ZMUSIC_YOUTUBE_ACCESS_TOKEN", "")
        if not token:
            raise ValueError(
                "YouTube access token is not configured "
                "(ZMUSIC_YOUTUBE_ACCESS_TOKEN). Run the OAuth flow first."
            )
        self._oauth_credentials()  # Validate client credentials exist
        logger.info("YouTube authentication succeeded")
        return token

    def discover_channels(self, access_token: str) -> list[YouTubeChannel]:
        """Discover channels accessible to the authenticated user."""
        data = self._request(
            "GET",
            "/channels",
            access_token,
            params={
                "part": "id,snippet",
                "mine": "true",
                "maxResults": "50",
            },
        )

        channels: list[YouTubeChannel] = []
        for item in data.get("items", []):
            snippet = item.get("snippet", {})
            channels.append(
                YouTubeChannel(
                    channel_id=item.get("id", ""),
                    title=snippet.get("title", ""),
                    description=snippet.get("description", ""),
                    published_at=snippet.get("publishedAt"),
                )
            )
        logger.info(
            "YouTube channels discovered",
            extra={"channel_count": len(channels)},
        )
        return channels

    def create_broadcast(
        self,
        access_token: str,
        title: str,
        scheduled_start_time: str | None = None,
        description: str = "",
    ) -> YouTubeBroadcast:
        """Create a YouTube Live broadcast."""
        body: dict[str, Any] = {
            "snippet": {
                "title": title,
                "description": description,
            },
            "status": {
                "privacyStatus": "public",
                "madeForKids": False,
            },
        }
        if scheduled_start_time:
            body["status"]["publishAt"] = scheduled_start_time

        data = self._request(
            "POST",
            "/liveBroadcasts",
            access_token,
            payload=body,
            params={"part": "id,snippet,status,contentDetails"},
        )

        snippet = data.get("snippet", {})
        status = data.get("status", {})
        content_details = data.get("contentDetails", {})
        stream_id = content_details.get("boundStreamId")

        broadcast = YouTubeBroadcast(
            broadcast_id=data.get("id", ""),
            title=snippet.get("title", title),
            status=status.get("lifeCycleStatus", "unknown"),
            scheduled_start_time=status.get("scheduledStartTime"),
            actual_start_time=status.get("actualStartTime"),
            actual_end_time=status.get("actualEndTime"),
            stream_id=stream_id,
        )
        logger.info(
            "YouTube broadcast created",
            extra={
                "broadcast_id": broadcast.broadcast_id,
                "title": broadcast.title,
                "status": broadcast.status,
            },
        )
        return broadcast

    def create_stream(
        self,
        access_token: str,
        title: str,
        format_: str = "1080p",
        ingestion_type: str = "rtmp",
    ) -> YouTubeStream:
        """Create a YouTube stream."""
        body = {
            "snippet": {
                "title": title,
            },
            "cdn": {
                "format": format_,
                "ingestionType": ingestion_type,
            },
        }

        data = self._request(
            "POST",
            "/liveStreams",
            access_token,
            payload=body,
            params={"part": "id,snippet,cdn,status"},
        )

        cdn = data.get("cdn", {})
        ingestion_info = cdn.get("ingestionInfo", {})
        return YouTubeStream(
            stream_id=data.get("id", ""),
            ingest_address=ingestion_info.get("ingestionAddress", ""),
            playback_url=ingestion_info.get("playbackUrl", ""),
            status=data.get("status", {}).get("streamStatus", "unknown"),
        )

    def bind_stream_to_broadcast(
        self,
        access_token: str,
        broadcast_id: str,
        stream_id: str,
    ) -> None:
        """Bind a stream to a broadcast."""
        self._request(
            "POST",
            "/liveBroadcasts/bind",
            access_token,
            params={
                "part": "id",
                "id": broadcast_id,
                "streamId": stream_id,
            },
        )
        logger.info(
            "YouTube stream bound to broadcast",
            extra={
                "broadcast_id": broadcast_id,
                "stream_id": stream_id,
            },
        )

    def update_broadcast_metadata(
        self,
        access_token: str,
        broadcast_id: str,
        title: str | None = None,
        description: str | None = None,
    ) -> None:
        """Update broadcast metadata."""
        body: dict[str, Any] = {"id": broadcast_id}
        snippet: dict[str, Any] = {}
        if title is not None:
            snippet["title"] = title
        if description is not None:
            snippet["description"] = description
        if snippet:
            body["snippet"] = snippet

        self._request(
            "PUT",
            "/liveBroadcasts",
            access_token,
            payload=body,
            params={"part": "id,snippet"},
        )
        logger.info(
            "YouTube broadcast metadata updated",
            extra={"broadcast_id": broadcast_id},
        )

    def get_broadcast_status(self, access_token: str, broadcast_id: str) -> str:
        """Return the current lifecycle status of a broadcast."""
        data = self._request(
            "GET",
            "/liveBroadcasts",
            access_token,
            params={"part": "status", "id": broadcast_id},
        )
        items = data.get("items", [])
        if not items:
            raise ValueError(f"Broadcast not found: {broadcast_id}")
        return items[0].get("status", {}).get("lifeCycleStatus", "unknown")

    def get_stream_status(self, access_token: str, stream_id: str) -> str:
        """Return the current status of a stream."""
        data = self._request(
            "GET",
            "/liveStreams",
            access_token,
            params={"part": "status", "id": stream_id},
        )
        items = data.get("items", [])
        if not items:
            raise ValueError(f"Stream not found: {stream_id}")
        return items[0].get("status", {}).get("streamStatus", "unknown")


class YouTubeIntegration:
    """High-level YouTube integration orchestrator.

    Coordinates broadcast creation, stream binding, and status monitoring
    through a YouTubeProvider abstraction. All credentials are isolated
    and never logged.
    """

    def __init__(self, provider: YouTubeProvider | None = None) -> None:
        self.provider = provider or YouTubeClient()
        self._access_token: str | None = None

    def authenticate(self) -> str:
        """Authenticate with YouTube and cache the access token."""
        self._access_token = self.provider.authenticate()
        return self._access_token

    def _token(self) -> str:
        if self._access_token is None:
            self._access_token = self.provider.authenticate()
        return self._access_token

    def create_live_stream_setup(
        self,
        title: str,
        scheduled_start_time: str | None = None,
        description: str = "",
    ) -> dict[str, Any]:
        """Create a complete YouTube live stream setup.

        Creates a broadcast, creates a stream, binds them together, and
        returns the ingest address and playback URL for the stream engine.
        """
        token = self._token()

        broadcast = self.provider.create_broadcast(
            access_token=token,
            title=title,
            scheduled_start_time=scheduled_start_time,
            description=description,
        )

        stream = self.provider.create_stream(
            access_token=token,
            title=title,
        )

        self.provider.bind_stream_to_broadcast(
            access_token=token,
            broadcast_id=broadcast.broadcast_id,
            stream_id=stream.stream_id,
        )

        result = {
            "broadcast_id": broadcast.broadcast_id,
            "broadcast_status": broadcast.status,
            "stream_id": stream.stream_id,
            "stream_status": stream.status,
            "ingest_address": stream.ingest_address,
            "playback_url": stream.playback_url,
            "scheduled_start_time": broadcast.scheduled_start_time,
        }
        logger.info(
            "YouTube live stream setup complete",
            extra={
                "broadcast_id": broadcast.broadcast_id,
                "stream_id": stream.stream_id,
                "has_ingest_address": bool(stream.ingest_address),
            },
        )
        return result

    def check_broadcast_health(self, broadcast_id: str) -> dict[str, Any]:
        """Check the health/status of a broadcast."""
        token = self._token()
        status = self.provider.get_broadcast_status(token, broadcast_id)
        return {
            "broadcast_id": broadcast_id,
            "status": status,
            "is_live": status == "active",
            "is_completed": status == "completed",
        }


# Global instance
_youtube: YouTubeIntegration | None = None


def get_youtube() -> YouTubeIntegration:
    """Return the global YouTube integration (singleton)."""
    global _youtube
    if _youtube is None:
        _youtube = YouTubeIntegration()
    return _youtube
