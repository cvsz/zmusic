"""Channel Configuration for zMusic.

Each channel is independently configurable with music, visual, stream,
and scheduling settings. Configuration is stored in the database and
can be versioned.

Example configuration:
```yaml
channel:
  name: "Night Radio"
  programming:
    mode: "autonomous"
  music:
    genres:
      - lofi
      - ambient
      - chill
  visual:
    theme: "rainy_city"
  stream:
    resolution: "1080p"
    fps: 30
  schedule:
    timezone: "Asia/Bangkok"
```
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from .config import AppConfig
from .database import get_connection, transaction
from .logging import get_logger
from .validation import validate_channel_config

logger = get_logger("zmusic.channel")


class ProgrammingMode(Enum):
    """Channel programming mode."""

    MANUAL = "manual"
    ASSISTED = "assisted"
    AUTONOMOUS = "autonomous"


class StreamResolution(Enum):
    """Supported stream resolutions."""

    RES_480P = "480p"
    RES_720P = "720p"
    RES_1080P = "1080p"


@dataclass
class MusicConfig:
    """Music programming configuration."""

    genres: list[str] = field(default_factory=list)
    mood: str | None = None
    bpm_range: tuple | None = None
    energy_curve: str | None = None
    transition_style: str = "crossfade"
    min_track_duration: int = 60
    max_track_duration: int = 600


@dataclass
class VisualConfig:
    """Visual programming configuration."""

    theme: str = "default"
    camera_motion: str = "slow"
    loop_duration_seconds: int = 1200
    overlay_style: str = "minimal"
    custom_assets: list[str] = field(default_factory=list)


@dataclass
class StreamConfig:
    """Stream output configuration."""

    resolution: str = "1080p"
    fps: int = 30
    video_bitrate: str = "4500k"
    audio_bitrate: str = "160k"
    encoder: str = "libx264"
    keyframe_interval: int = 60


@dataclass
class ScheduleConfig:
    """Schedule configuration."""

    timezone: str = "UTC"
    autonomous_hours: int | None = None  # For 24/7 mode


@dataclass
class ChannelConfig:
    """Complete channel configuration."""

    channel_id: str
    name: str
    description: str = ""
    programming_mode: ProgrammingMode = ProgrammingMode.MANUAL
    music: MusicConfig = field(default_factory=MusicConfig)
    visual: VisualConfig = field(default_factory=VisualConfig)
    stream: StreamConfig = field(default_factory=StreamConfig)
    schedule: ScheduleConfig = field(default_factory=ScheduleConfig)
    created_at: str = field(default_factory=lambda: datetime.now(tz=UTC).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(tz=UTC).isoformat())
    version: int = 1


class ChannelManager:
    """Manages channel configurations in the database."""

    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config or AppConfig()

    def create_channel(
        self, config: ChannelConfig, organization_id: str = "org-default"
    ) -> ChannelConfig:
        """Create a new channel configuration."""
        # Validate configuration
        validation = validate_channel_config(self._to_dict(config))
        if not validation.valid:
            raise ValueError(f"Invalid channel configuration: {validation.errors}")

        with transaction() as conn:
            conn.execute(
                """INSERT INTO channels (id, organization_id, name, description, config, created_at, updated_at, version)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    config.channel_id,
                    organization_id,
                    config.name,
                    config.description,
                    json.dumps(self._to_dict(config)),
                    config.created_at,
                    config.updated_at,
                    config.version,
                ),
            )
        logger.info(
            "Channel created",
            extra={"channel_id": config.channel_id, "name": config.name},
        )
        return config

    def get_channel(self, channel_id: str) -> ChannelConfig | None:
        """Get channel configuration by ID."""
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT id, name, description, config FROM channels WHERE id = ? AND deleted_at IS NULL",
                (channel_id,),
            ).fetchone()
            if not row:
                return None
            return self._from_db_row(row)
        finally:
            # Do NOT close connection here - let the caller manage connection lifecycle
            # The thread-local connection is reused across calls
            pass

    def update_channel(self, channel_id: str, updates: dict[str, Any]) -> ChannelConfig:
        """Update channel configuration."""
        existing = self.get_channel(channel_id)
        if not existing:
            raise ValueError(f"Channel not found: {channel_id}")

        # Merge updates
        updated = self._merge_config(existing, updates)
        updated.updated_at = datetime.now(tz=UTC).isoformat()
        updated.version += 1

        # Validate
        validation = validate_channel_config(self._to_dict(updated))
        if not validation.valid:
            raise ValueError(f"Invalid channel configuration: {validation.errors}")

        with transaction() as conn:
            conn.execute(
                """UPDATE channels SET name = ?, description = ?, config = ?, updated_at = ?, version = ?
                   WHERE id = ? AND deleted_at IS NULL""",
                (
                    updated.name,
                    updated.description,
                    json.dumps(self._to_dict(updated)),
                    updated.updated_at,
                    updated.version,
                    channel_id,
                ),
            )
        logger.info(
            "Channel updated",
            extra={"channel_id": channel_id, "version": updated.version},
        )
        return updated

    def delete_channel(self, channel_id: str) -> bool:
        """Soft delete a channel."""
        with transaction() as conn:
            cursor = conn.execute(
                "UPDATE channels SET deleted_at = ? WHERE id = ? AND deleted_at IS NULL",
                (datetime.now(tz=UTC).isoformat(), channel_id),
            )
            return cursor.rowcount > 0

    def list_channels(self, organization_id: str | None = None) -> list[ChannelConfig]:
        """List all channels, optionally filtered by organization."""
        conn = get_connection()
        try:
            if organization_id:
                rows = conn.execute(
                    "SELECT id, name, description, config FROM channels WHERE organization_id = ? AND deleted_at IS NULL",
                    (organization_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, name, description, config FROM channels WHERE deleted_at IS NULL"
                ).fetchall()
            return [self._from_db_row(row) for row in rows]
        finally:
            conn.close()

    def get_channel_config_dict(self, channel_id: str) -> dict[str, Any] | None:
        """Get raw channel config as dictionary."""
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT config FROM channels WHERE id = ? AND deleted_at IS NULL",
                (channel_id,),
            ).fetchone()
            if not row:
                return None
            return json.loads(row["config"])
        finally:
            conn.close()

    def _to_dict(self, config: ChannelConfig) -> dict[str, Any]:
        """Convert ChannelConfig to dictionary for storage/validation."""
        return {
            "name": config.name,
            "programming": {"mode": config.programming_mode.value},
            "music": {
                "genres": config.music.genres,
                "mood": config.music.mood,
                "bpm_range": config.music.bpm_range,
                "energy_curve": config.music.energy_curve,
                "transition_style": config.music.transition_style,
            },
            "visual": {
                "theme": config.visual.theme,
                "camera_motion": config.visual.camera_motion,
                "loop_duration_seconds": config.visual.loop_duration_seconds,
                "overlay_style": config.visual.overlay_style,
            },
            "stream": {
                "resolution": config.stream.resolution,
                "fps": config.stream.fps,
                "video_bitrate": config.stream.video_bitrate,
                "audio_bitrate": config.stream.audio_bitrate,
                "encoder": config.stream.encoder,
            },
            "schedule": {
                "timezone": config.schedule.timezone,
            },
        }

    def _from_db_row(self, row) -> ChannelConfig:
        """Reconstruct ChannelConfig from database row."""
        config_dict = json.loads(row["config"])
        return ChannelConfig(
            channel_id=row["id"],
            name=row["name"],
            description=row["description"] or "",
            programming_mode=ProgrammingMode(
                config_dict.get("programming", {}).get("mode", "manual")
            ),
            music=MusicConfig(**config_dict.get("music", {})),
            visual=VisualConfig(**config_dict.get("visual", {})),
            stream=StreamConfig(**config_dict.get("stream", {})),
            schedule=ScheduleConfig(**config_dict.get("schedule", {})),
        )

    def _merge_config(
        self, existing: ChannelConfig, updates: dict[str, Any]
    ) -> ChannelConfig:
        """Merge updates into existing configuration."""
        # This is a simplified merge - in production would use deep merge
        merged = ChannelConfig(
            channel_id=existing.channel_id,
            name=updates.get("name", existing.name),
            description=updates.get("description", existing.description),
            programming_mode=ProgrammingMode(
                updates.get("programming_mode", existing.programming_mode.value)
            ),
            music=MusicConfig(
                **{**existing.music.__dict__, **updates.get("music", {})}
            ),
            visual=VisualConfig(
                **{**existing.visual.__dict__, **updates.get("visual", {})}
            ),
            stream=StreamConfig(
                **{**existing.stream.__dict__, **updates.get("stream", {})}
            ),
            schedule=ScheduleConfig(
                **{**existing.schedule.__dict__, **updates.get("schedule", {})}
            ),
            created_at=existing.created_at,
            updated_at=existing.updated_at,
            version=existing.version,
        )
        return merged


# Global instance
_channel_manager: ChannelManager | None = None


def get_channel_manager(config: AppConfig | None = None) -> ChannelManager:
    """Get the global channel manager (singleton)."""
    global _channel_manager
    if _channel_manager is None:
        _channel_manager = ChannelManager(config)
    return _channel_manager


# --- Example Usage ---
#
# manager = get_channel_manager()
#
# # Create a new channel
# config = ChannelConfig(
#     channel_id="ch-night-radio",
#     name="Night Radio",
#     description="Late night lofi beats",
#     programming_mode=ProgrammingMode.AUTONOMOUS,
#     music=MusicConfig(genres=["lofi", "ambient", "chill"], mood="calm"),
#     visual=VisualConfig(theme="rainy_city", camera_motion="slow"),
#     stream=StreamConfig(resolution="1080p", fps=30),
#     schedule=ScheduleConfig(timezone="Asia/Bangkok"),
# )
# manager.create_channel(config)
#
# # Get channel
# channel = manager.get_channel("ch-night-radio")
# print(channel.name, channel.programming_mode)
#
# # Update channel
# manager.update_channel("ch-night-radio", {"music": {"genres": ["lofi", "ambient"]}})
#
# # List all channels
# channels = manager.list_channels()
