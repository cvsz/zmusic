"""Application configuration management.

Reads environment variables with safe defaults, validates required settings,
and isolates secrets. No secrets are ever logged or committed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class DatabaseConfig:
    url: str = "sqlite:///data/stremdbc.db"
    pool_size: int = 5
    max_overflow: int = 10
    pool_timeout: int = 30


@dataclass(frozen=True)
class RedisConfig:
    url: str = "redis://localhost:6379/0"
    socket_timeout: int = 5
    socket_connect_timeout: int = 5


@dataclass(frozen=True)
class StreamConfig:
    rtmp_port: int = 1935
    http_port: int = 8080
    max_concurrent_streams: int = 5
    default_fps: int = 30
    default_resolution: str = "1080p"
    default_video_bitrate: str = "4500k"
    default_audio_bitrate: str = "160k"


@dataclass(frozen=True)
class SecurityConfig:
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    jwt_expiry_seconds: int = 3600
    rate_limit_per_minute: int = 60
    max_upload_size_mb: int = 500


@dataclass(frozen=True)
class YouTubeConfig:
    client_id: str = ""
    client_secret: str = ""
    redirect_uri: str = "http://localhost:8080/api/v1/youtube/callback"
    api_scope: str = "https://www.googleapis.com/auth/youtube.upload"


@dataclass(frozen=True)
class AppConfig:
    environment: str = "development"
    debug: bool = False
    log_level: str = "INFO"
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    redis: RedisConfig = field(default_factory=RedisConfig)
    stream: StreamConfig = field(default_factory=StreamConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    youtube: YouTubeConfig = field(default_factory=YouTubeConfig)


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name, str(default)).strip().lower()
    return value in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _env_str(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def load_config() -> AppConfig:
    """Load configuration from environment variables.

    Required secrets (JWT_SECRET, YouTube OAuth credentials) must be provided
    via environment variables — never hard-coded.
    """
    return AppConfig(
        environment=_env_str("ZMUSIC_ENV", "development"),
        debug=_env_bool("ZMUSIC_DEBUG", False),
        log_level=_env_str("ZMUSIC_LOG_LEVEL", "INFO"),
        database=DatabaseConfig(
            url=_env_str("ZMUSIC_DATABASE_URL", "sqlite:///data/zmusic.db"),
            pool_size=_env_int("ZMUSIC_DB_POOL_SIZE", 5),
            max_overflow=_env_int("ZMUSIC_DB_MAX_OVERFLOW", 10),
            pool_timeout=_env_int("ZMUSIC_DB_POOL_TIMEOUT", 30),
        ),
        redis=RedisConfig(
            url=_env_str("ZMUSIC_REDIS_URL", "redis://localhost:6379/0"),
            socket_timeout=_env_int("ZMUSIC_REDIS_SOCKET_TIMEOUT", 5),
            socket_connect_timeout=_env_int("ZMUSIC_REDIS_CONNECT_TIMEOUT", 5),
        ),
        stream=StreamConfig(
            rtmp_port=_env_int("ZMUSIC_RTMP_PORT", 1935),
            http_port=_env_int("ZMUSIC_HTTP_PORT", 8080),
            max_concurrent_streams=_env_int("ZMUSIC_MAX_CONCURRENT_STREAMS", 5),
            default_fps=_env_int("ZMUSIC_DEFAULT_FPS", 30),
            default_resolution=_env_str("ZMUSIC_DEFAULT_RESOLUTION", "1080p"),
            default_video_bitrate=_env_str("ZMUSIC_DEFAULT_VIDEO_BITRATE", "4500k"),
            default_audio_bitrate=_env_str("ZMUSIC_DEFAULT_AUDIO_BITRATE", "160k"),
        ),
        security=SecurityConfig(
            jwt_secret=_env_str("ZMUSIC_JWT_SECRET", ""),
            jwt_algorithm=_env_str("ZMUSIC_JWT_ALGORITHM", "HS256"),
            jwt_expiry_seconds=_env_int("ZMUSIC_JWT_EXPIRY_SECONDS", 3600),
            rate_limit_per_minute=_env_int("ZMUSIC_RATE_LIMIT_PER_MINUTE", 60),
            max_upload_size_mb=_env_int("ZMUSIC_MAX_UPLOAD_SIZE_MB", 500),
        ),
        youtube=YouTubeConfig(
            client_id=_env_str("ZMUSIC_YOUTUBE_CLIENT_ID", ""),
            client_secret=_env_str("ZMUSIC_YOUTUBE_CLIENT_SECRET", ""),
            redirect_uri=_env_str(
                "ZMUSIC_YOUTUBE_REDIRECT_URI",
                "http://localhost:8080/api/v1/youtube/callback",
            ),
            api_scope=_env_str(
                "ZMUSIC_YOUTUBE_API_SCOPE",
                "https://www.googleapis.com/auth/youtube.upload",
            ),
        ),
    )


def validate_config(config: AppConfig) -> list[str]:
    """Validate configuration. Returns list of error messages (empty if valid)."""
    errors: list[str] = []

    if config.environment not in {"development", "staging", "production"}:
        errors.append("ZMUSIC_ENV must be development, staging, or production")

    if config.environment == "production" and not config.security.jwt_secret:
        errors.append("ZMUSIC_JWT_SECRET is required in production")

    if config.stream.max_concurrent_streams < 1:
        errors.append("ZMUSIC_MAX_CONCURRENT_STREAMS must be >= 1")

    if config.database.pool_size < 1:
        errors.append("ZMUSIC_DB_POOL_SIZE must be >= 1")

    if config.security.rate_limit_per_minute < 1:
        errors.append("ZMUSIC_RATE_LIMIT_PER_MINUTE must be >= 1")

    if config.security.max_upload_size_mb < 1:
        errors.append("ZMUSIC_MAX_UPLOAD_SIZE_MB must be >= 1")

    return errors
