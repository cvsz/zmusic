"""Validation layer for zMusic.

Provides deterministic input validation that agents must pass before
executing critical operations. All validation results are schema-based
and explicitly rejected if malformed.

Never allow an LLM to directly control critical infrastructure without
validation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ValidationResult:
    """Result of a validation check."""

    valid: bool
    errors: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def with_error(self, message: str) -> ValidationResult:
        """Add an error message and return new instance."""
        return ValidationResult(
            valid=False,
            errors=(*self.errors, message),
            warnings=self.warnings,
        )

    def with_warning(self, message: str) -> ValidationResult:
        """Add a warning message and return new instance."""
        return ValidationResult(
            valid=self.valid,
            errors=self.errors,
            warnings=(*self.warnings, message),
        )


# --- Channel Configuration Validation ---


def validate_channel_config(config: dict[str, Any]) -> ValidationResult:
    """Validate channel configuration dictionary.

    Required fields:
    - name: str
    - programming.mode: str
    - music.genres: list[str]
    - visual.theme: str
    - stream.resolution: str
    - stream.fps: int
    - schedule.timezone: str
    """
    errors: list[str] = []

    # Validate name
    name = config.get("name")
    if not name or not isinstance(name, str) or name.strip() == "":
        errors.append("channel.name must be a non-empty string")

    # Validate programming mode
    programming = config.get("programming", {})
    mode = programming.get("mode")
    valid_modes = {"manual", "assisted", "autonomous"}
    if not mode or mode not in valid_modes:
        errors.append(f"programming.mode must be one of {valid_modes}")

    # Validate music genres
    music = config.get("music", {})
    genres = music.get("genres", [])
    if not isinstance(genres, list) or len(genres) == 0:
        errors.append("music.genres must be a non-empty list")
    else:
        for g in genres:
            if not isinstance(g, str) or g.strip() == "":
                errors.append(f"music.genres item must be a non-empty string: {g}")

    # Validate visual theme
    visual = config.get("visual", {})
    theme = visual.get("theme")
    if not theme or not isinstance(theme, str) or theme.strip() == "":
        errors.append("visual.theme must be a non-empty string")

    # Validate stream resolution
    stream = config.get("stream", {})
    resolution = stream.get("resolution")
    valid_resolutions = {"720p", "1080p", "480p"}
    if resolution not in valid_resolutions:
        errors.append(f"stream.resolution must be one of {valid_resolutions}")

    # Validate fps
    fps = stream.get("fps")
    if not isinstance(fps, int) or fps <= 0:
        errors.append("stream.fps must be a positive integer")

    # Validate timezone
    schedule = config.get("schedule", {})
    timezone = schedule.get("timezone")
    if not timezone or not isinstance(timezone, str) or timezone.strip() == "":
        errors.append("schedule.timezone must be a non-empty string")

    valid = len(errors) == 0
    return ValidationResult(valid=valid, errors=tuple(errors))


# --- Track/Rights Validation ---


def validate_track_rights(track: dict[str, Any]) -> ValidationResult:
    """Validate track rights dictionary.

    Required fields:
    - track_id: str
    - youtube_allowed: bool
    - commercial_allowed: bool
    - license_valid_until: str | None
    - attribution_required: bool
    """
    errors: list[str] = []

    track_id = track.get("track_id")
    if not track_id or not isinstance(track_id, str) or track_id.strip() == "":
        errors.append("track.track_id must be a non-empty string")

    youtube_allowed = track.get("youtube_allowed")
    if not isinstance(youtube_allowed, bool):
        errors.append("track.youtube_allowed must be a boolean")

    commercial_allowed = track.get("commercial_allowed")
    if not isinstance(commercial_allowed, bool):
        errors.append("track.commercial_allowed must be a boolean")

    license_valid_until = track.get("license_valid_until")
    if license_valid_until is not None:
        if not isinstance(license_valid_until, str):
            errors.append("track.license_valid_until must be a string or null")
        elif license_valid_until.strip() == "":
            errors.append("track.license_valid_until must not be an empty string")

    attribution_required = track.get("attribution_required")
    if not isinstance(attribution_required, bool):
        errors.append("track.attribution_required must be a boolean")

    valid = len(errors) == 0
    return ValidationResult(valid=valid, errors=tuple(errors))


# --- Stream Configuration Validation ---


def validate_stream_config(config: dict[str, Any]) -> ValidationResult:
    """Validate stream configuration dictionary.

    Required fields:
    - stream_id: str
    - channel_id: str
    - resolution: str (valid preset)
    - fps: int (positive)
    - bitrate: str (valid format)
    - encoder: str (valid encoder)
    """
    errors: list[str] = []

    stream_id = config.get("stream_id")
    if not stream_id or not isinstance(stream_id, str) or stream_id.strip() == "":
        errors.append("stream.stream_id must be a non-empty string")

    channel_id = config.get("channel_id")
    if not channel_id or not isinstance(channel_id, str) or channel_id.strip() == "":
        errors.append("stream.channel_id must be a non-empty string")

    resolution = config.get("resolution")
    valid_resolutions = {"720p", "1080p", "480p"}
    if resolution not in valid_resolutions:
        errors.append(f"stream.resolution must be one of {valid_resolutions}")

    fps = config.get("fps")
    if not isinstance(fps, int) or fps <= 0:
        errors.append("stream.fps must be a positive integer")

    bitrate = config.get("bitrate")
    if not bitrate or not isinstance(bitrate, str) or bitrate.strip() == "":
        errors.append("stream.bitrate must be a non-empty string")

    encoder = config.get("encoder")
    valid_encoders = {
        "libx264",
        "libx265",
        "mpeg2_videotoolbox",
        "h264_vaapi",
        "h264_vda",
    }
    if encoder not in valid_encoders:
        errors.append(f"stream.encoder must be one of {valid_encoders}")

    valid = len(errors) == 0
    return ValidationResult(valid=valid, errors=tuple(errors))


# --- Agent Output Validation ---


def validate_agent_output(agent_name: str, output: dict[str, Any]) -> ValidationResult:
    """Validate that agent output conforms to expected schema.

    Every agent must produce structured output that passes validation.
    Malformed responses are rejected.

    Args:
        agent_name: Name of the agent that produced the output
        output: The agent's output dictionary

    Returns:
        ValidationResult indicating if the output is valid
    """
    errors: list[str] = []

    if not isinstance(output, dict):
        errors.append(f"{agent_name} output must be a dictionary")
        return ValidationResult(valid=False, errors=tuple(errors))

    if "agent" not in output:
        errors.append(f"{agent_name} output missing required 'agent' field")

    if "version" not in output:
        errors.append(f"{agent_name} output missing required 'version' field")

    if "status" not in output:
        errors.append(f"{agent_name} output missing required 'status' field")

    if "status" in output and output["status"] not in {"success", "failed", "warning"}:
        errors.append(f"{agent_name} status must be one of: success, failed, warning")

    # Agent-specific validations
    if agent_name == "music_director":
        if "plan" not in output:
            errors.append("music_director output missing 'plan' field")
        elif not isinstance(output["plan"], dict):
            errors.append("music_director 'plan' must be a dictionary")

    if agent_name == "rights_validator":
        if "rights" not in output:
            errors.append("rights_validator output missing 'rights' field")
        elif not isinstance(output.get("rights"), dict):
            errors.append("rights_validator 'rights' must be a dictionary")

    if agent_name == "scheduler":
        if "schedule" not in output:
            errors.append("scheduler output missing 'schedule' field")

    if agent_name == "metadata":
        if "title" not in output:
            errors.append("metadata output missing 'title' field")

    valid = len(errors) == 0
    return ValidationResult(valid=valid, errors=tuple(errors))


# --- Main Validation Entrypoint ---


def validate_for_production(operation: str, data: dict[str, Any]) -> ValidationResult:
    """Validate data before a production operation.

    Args:
        operation: Type of operation (channel_config, track_rights, stream_config, agent_output)
        data: Data to validate

    Returns:
        ValidationResult indicating if the data is valid for production
    """
    if operation == "channel_config":
        return validate_channel_config(data)
    elif operation == "track_rights":
        return validate_track_rights(data)
    elif operation == "stream_config":
        return validate_stream_config(data)
    elif operation == "agent_output":
        # agent_name inferred from data if possible, otherwise generic
        agent_name = data.get("agent", "unknown")
        return validate_agent_output(agent_name, data)
    else:
        return ValidationResult(
            valid=False, errors=(f"Unknown operation type: {operation}",)
        )
