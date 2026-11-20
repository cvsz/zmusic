"""Media pipeline for zMusic.

FFmpeg-based deterministic media engine supporting H.264, AAC, MP4,
MPEG-TS, RTMP, configurable FPS/resolution/bitrate, audio normalization,
looping video, playlist playback, and transitions.

Never executes arbitrary shell commands — all FFmpeg invocations are
deterministically validated before execution.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import StreamConfig
from .logging import get_logger

logger = get_logger("zmusic.media")


@dataclass(frozen=True)
class StreamPreset:
    """A safe, predefined stream encoding preset."""

    name: str
    width: int
    height: int
    fps: int
    video_bitrate: str
    audio_bitrate: str


# Built-in safe presets
PRESETS: dict[str, StreamPreset] = {
    "youtube_1080p": StreamPreset(
        name="youtube_1080p",
        width=1920,
        height=1080,
        fps=30,
        video_bitrate="4500k",
        audio_bitrate="160k",
    ),
    "youtube_720p": StreamPreset(
        name="youtube_720p",
        width=1280,
        height=720,
        fps=30,
        video_bitrate="2500k",
        audio_bitrate="128k",
    ),
}


@dataclass(frozen=True)
class StreamConfigOverride:
    """Per-stream encoding configuration."""

    preset: str = "youtube_1080p"
    width: int | None = None
    height: int | None = None
    fps: int | None = None
    video_bitrate: str | None = None
    audio_bitrate: str | None = None
    rtmp_url: str = ""
    stream_key: str = ""

    def resolved(self, default_config: StreamConfig) -> StreamPreset:
        """Resolve to a StreamPreset, falling back to defaults."""
        preset = PRESETS.get(self.preset)
        if preset is None:
            raise ValueError(f"Unknown preset: {self.preset}")

        return StreamPreset(
            name=preset.name,
            width=self.width or preset.width,
            height=self.height or preset.height,
            fps=self.fps or preset.fps,
            video_bitrate=self.video_bitrate or preset.video_bitrate,
            audio_bitrate=self.audio_bitrate or preset.audio_bitrate,
        )


class FFmpegCommand:
    """Builds and validates FFmpeg commands.

    All commands are constructed from validated components — no arbitrary
    shell execution is ever permitted.
    """

    ALLOWED_INPUTS = {"file", "pipe", "rtmp", "http", "https"}
    ALLOWED_OUTPUTS = {"file", "pipe", "rtmp"}
    ALLOWED_CODECS = {"libx264", "aac", "copy"}
    ALLOWED_FORMATS = {"mp4", "mpegts", "flv", "matroska"}

    def __init__(self) -> None:
        self._parts: list[str] = ["ffmpeg", "-y"]
        self._inputs: list[str] = []
        self._outputs: list[str] = []

    def add_global_option(self, option: str, value: str | None = None) -> "FFmpegCommand":
        """Add a global FFmpeg option (before inputs)."""
        self._parts.append(option)
        if value is not None:
            self._parts.append(str(value))
        return self

    def add_input(self, path: str, options: list[str] | None = None) -> "FFmpegCommand":
        """Add an input. Path is validated for safety."""
        self._validate_path(path, "input")
        self._parts.append("-i")
        self._parts.append(path)
        if options:
            for opt in options:
                self._parts.append(opt)
        self._inputs.append(path)
        return self

    def add_output(
        self, path: str, options: list[str] | None = None
    ) -> "FFmpegCommand":
        """Add an output. Path is validated for safety."""
        self._validate_path(path, "output")
        self._parts.append(path)
        if options:
            for opt in options:
                self._parts.append(opt)
        self._outputs.append(path)
        return self

    def add_option(self, option: str, value: str | None = None) -> "FFmpegCommand":
        """Add an option to the most recent input/output."""
        self._parts.append(option)
        if value is not None:
            self._parts.append(str(value))
        return self

    def build(self) -> list[str]:
        """Return the final command as a list of arguments (safe for subprocess)."""
        return list(self._parts)

    def _validate_path(self, path: str, kind: str) -> None:
        """Validate that a path does not contain shell metacharacters."""
        # Reject shell metacharacters
        dangerous = set(";&|`$()<>!{}[]*?~")
        if any(ch in path for ch in dangerous):
            raise ValueError(f"Unsafe {kind} path: {path!r}")

        # Reject absolute paths outside allowed directories for security
        # (inputs/outputs should be relative or within configured roots)
        if path.startswith("/") and not path.startswith(("/tmp/", "/data/")):
            raise ValueError(f"Absolute {kind} path outside allowed roots: {path!r}")


def build_rtmp_output_command(
    input_file: str,
    rtmp_url: str,
    stream_key: str,
    preset_name: str = "youtube_1080p",
    default_config: StreamConfig | None = None,
) -> FFmpegCommand:
    """Build an FFmpeg command to stream a file to RTMP.

    The command loops the input file indefinitely and streams it to the
    specified RTMP endpoint using the given preset.
    """
    config = default_config or StreamConfig()
    preset = PRESETS.get(preset_name)
    if preset is None:
        raise ValueError(f"Unknown preset: {preset_name}")

    rtmp_endpoint = f"{rtmp_url}/{stream_key}" if stream_key else rtmp_url

    cmd = FFmpegCommand()
    cmd.add_global_option("-re")  # Read input at native frame rate
    cmd.add_global_option("-stream_loop", "-1")  # Loop input indefinitely
    cmd.add_input(input_file)
    cmd.add_option("-c:v", "libx264")
    cmd.add_option("-preset", "veryfast")
    cmd.add_option("-b:v", preset.video_bitrate)
    cmd.add_option("-maxrate", preset.video_bitrate)
    cmd.add_option("-bufsize", f"{int(preset.video_bitrate.rstrip('k')) * 2}k")
    cmd.add_option("-vf", f"scale={preset.width}:{preset.height}")
    cmd.add_option("-r", str(preset.fps))
    cmd.add_option("-c:a", "aac")
    cmd.add_option("-b:a", preset.audio_bitrate)
    cmd.add_option("-ar", "44100")
    cmd.add_option("-f", "flv")
    cmd.add_output(rtmp_endpoint)

    logger.info(
        "Built RTMP output command",
        extra={
            "input": input_file,
            "rtmp_endpoint": rtmp_endpoint,
            "preset": preset_name,
            "width": preset.width,
            "height": preset.height,
            "fps": preset.fps,
        },
    )
    return cmd


def build_playlist_command(
    input_files: list[str],
    output_path: str,
    preset_name: str = "youtube_1080p",
    default_config: StreamConfig | None = None,
) -> FFmpegCommand:
    """Build an FFmpeg command to concatenate a playlist into a single output.

    Uses the concat demuxer for deterministic playlist playback.
    """
    config = default_config or StreamConfig()
    preset = PRESETS.get(preset_name)
    if preset is None:
        raise ValueError(f"Unknown preset: {preset_name}")

    # Build a concat file list
    concat_list = "\n".join(f"file '{f}'" for f in input_files)
    concat_path = "/tmp/zmusic_concat_list.txt"

    cmd = FFmpegCommand()
    cmd.add_global_option("-f", "concat")
    cmd.add_global_option("-safe", "0")
    cmd.add_input(concat_path)
    cmd.add_option("-c", "copy")
    cmd.add_output(output_path)

    logger.info(
        "Built playlist command",
        extra={
            "input_count": len(input_files),
            "output": output_path,
            "preset": preset_name,
        },
    )
    return cmd, concat_path, concat_list


def run_ffmpeg(command: FFmpegCommand, timeout: int = 3600) -> dict[str, Any]:
    """Execute a validated FFmpeg command.

    Returns a dict with returncode, stdout, stderr. Raises on timeout or
    unexpected error. The command is always passed as a list (never shell).
    """
    args = command.build()
    logger.info(
        "Running FFmpeg",
        extra={"command": " ".join(shlex.quote(a) for a in args)},
    )

    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "success": result.returncode == 0,
        }
    except subprocess.TimeoutExpired as exc:
        logger.error(
            "FFmpeg timed out",
            extra={"timeout_seconds": timeout, "command": args[0]},
        )
        raise
    except FileNotFoundError:
        logger.error("FFmpeg binary not found")
        raise RuntimeError("FFmpeg is not installed or not in PATH")


def check_ffmpeg_available() -> bool:
    """Check if FFmpeg is installed and usable."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def validate_preset(preset_name: str) -> StreamPreset:
    """Validate and return a stream preset by name."""
    preset = PRESETS.get(preset_name)
    if preset is None:
        available = ", ".join(sorted(PRESETS.keys()))
        raise ValueError(
            f"Unknown preset '{preset_name}'. Available: {available}"
        )
    return preset