"""Database layer for STREMDBC.

SQLite-based with WAL mode, UUID primary keys, foreign keys, indexes,
timestamps, and soft deletion. All schema changes must be migration-based.
"""

from __future__ import annotations

import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator

from .config import DatabaseConfig
from .logging import get_logger

logger = get_logger("zmusic.database")

_local = threading.local()
_config: DatabaseConfig = DatabaseConfig()


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _generate_uuid() -> str:
    return str(uuid.uuid4())


def _connect(db_path: str) -> sqlite3.Connection:
    if db_path.startswith("sqlite:///"):
        file_path = db_path[len("sqlite:///"):]
    elif db_path.startswith("sqlite://"):
        file_path = db_path[len("sqlite://"):]
    else:
        file_path = db_path

    parent = Path(file_path).parent
    if parent and not parent.exists():
        parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(file_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def get_connection() -> sqlite3.Connection:
    """Get a thread-local database connection."""
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = _connect(_config.url)
    return _local.conn


@contextmanager
def transaction() -> Generator[sqlite3.Connection, None, None]:
    """Context manager for database transactions with automatic rollback on error."""
    conn = get_connection()
    try:
        conn.execute("BEGIN")
        yield conn
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        logger.error("Database transaction rolled back due to error")
        raise


def init_db(config: DatabaseConfig) -> None:
    """Initialize the database schema. Idempotent — safe to run multiple times."""
    global _config
    _config = config

    # Close any existing connection before replacing
    if hasattr(_local, "conn") and _local.conn is not None:
        try:
            _local.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            _local.conn.close()
        except Exception:
            pass
        _local.conn = None

    conn = _connect(config.url)
    try:
        _create_tables(conn)
        _create_indexes(conn)
        # Store connection for reuse by get_connection()
        _local.conn = conn
        logger.info("Database initialized successfully", extra={"database_url": config.url})
    except Exception:
        conn.close()
        raise


def _create_tables(conn: sqlite3.Connection) -> None:
    statements = [
        """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'viewer',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            deleted_at TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS organizations (
            id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
            name TEXT NOT NULL,
            slug TEXT UNIQUE NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            deleted_at TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS channels (
            id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
            organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            programming_mode TEXT NOT NULL DEFAULT 'manual' CHECK (programming_mode IN ('manual', 'assisted', 'autonomous')),
            stream_resolution TEXT NOT NULL DEFAULT '1080p',
            stream_fps INTEGER NOT NULL DEFAULT 30,
            timezone TEXT NOT NULL DEFAULT 'UTC',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            deleted_at TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS channel_settings (
            id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
            channel_id TEXT NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
            config_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            deleted_at TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS agents (
            id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
            name TEXT NOT NULL,
            agent_type TEXT NOT NULL,
            config_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            deleted_at TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS agent_runs (
            id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
            agent_id TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
            status TEXT NOT NULL DEFAULT 'created' CHECK (status IN ('created', 'planned', 'generating', 'validating', 'ready', 'scheduled', 'streaming', 'completed', 'failed', 'retry_pending', 'recovering')),
            input_json TEXT NOT NULL DEFAULT '{}',
            output_json TEXT,
            error_message TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            started_at TEXT,
            completed_at TEXT,
            deleted_at TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS content (
            id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
            channel_id TEXT NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            description TEXT,
            state TEXT NOT NULL DEFAULT 'draft' CHECK (state IN ('draft', 'generating', 'validating', 'approved', 'ready', 'scheduled', 'active', 'completed', 'validation_failed', 'content_failed', 'stream_failed')),
            requires_approval INTEGER NOT NULL DEFAULT 0,
            approved_by TEXT,
            approved_at TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            deleted_at TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS playlists (
            id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
            channel_id TEXT NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            deleted_at TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS playlist_items (
            id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
            playlist_id TEXT NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
            track_id TEXT NOT NULL,
            position INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            deleted_at TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS tracks (
            id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
            title TEXT NOT NULL,
            artist TEXT,
            file_path TEXT,
            duration_seconds INTEGER,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            deleted_at TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS track_metadata (
            id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
            track_id TEXT NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
            key TEXT NOT NULL,
            value TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            deleted_at TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS track_rights (
            id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
            track_id TEXT NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
            ownership_verified INTEGER NOT NULL DEFAULT 0,
            license_valid_until TEXT,
            commercial_allowed INTEGER NOT NULL DEFAULT 0,
            youtube_allowed INTEGER NOT NULL DEFAULT 0,
            attribution_required INTEGER NOT NULL DEFAULT 0,
            geographic_restrictions TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            deleted_at TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS visual_assets (
            id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
            name TEXT NOT NULL,
            file_path TEXT NOT NULL,
            width INTEGER,
            height INTEGER,
            frame_rate REAL,
            duration_seconds INTEGER,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            deleted_at TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS audio_assets (
            id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
            name TEXT NOT NULL,
            file_path TEXT NOT NULL,
            duration_seconds INTEGER,
            sample_rate INTEGER,
            channels INTEGER,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            deleted_at TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS overlay_assets (
            id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
            name TEXT NOT NULL,
            file_path TEXT NOT NULL,
            width INTEGER,
            height INTEGER,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            deleted_at TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS scenes (
            id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
            name TEXT NOT NULL,
            config_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            deleted_at TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS compositions (
            id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
            content_id TEXT NOT NULL REFERENCES content(id) ON DELETE CASCADE,
            audio_playlist_id TEXT,
            visual_scene_id TEXT,
            overlay_id TEXT,
            now_playing INTEGER NOT NULL DEFAULT 0,
            transition TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            deleted_at TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS streams (
            id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
            channel_id TEXT NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
            composition_id TEXT REFERENCES compositions(id) ON DELETE SET NULL,
            youtube_broadcast_id TEXT,
            youtube_stream_id TEXT,
            state TEXT NOT NULL DEFAULT 'created' CHECK (state IN ('created', 'preflight', 'ready', 'starting', 'live', 'degraded', 'recovering', 'stopping', 'stopped', 'failed')),
            rtmp_url TEXT,
            stream_key TEXT,
            started_at TEXT,
            stopped_at TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            deleted_at TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS stream_sessions (
            id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
            stream_id TEXT NOT NULL REFERENCES streams(id) ON DELETE CASCADE,
            viewer_count INTEGER DEFAULT 0,
            watch_time_seconds INTEGER DEFAULT 0,
            average_view_duration_seconds REAL DEFAULT 0,
            retention REAL DEFAULT 0,
            peak_viewers INTEGER DEFAULT 0,
            interruptions INTEGER DEFAULT 0,
            started_at TEXT NOT NULL DEFAULT (datetime('now')),
            ended_at TEXT,
            deleted_at TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS stream_events (
            id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
            stream_id TEXT NOT NULL REFERENCES streams(id) ON DELETE CASCADE,
            event_type TEXT NOT NULL,
            event_data TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            deleted_at TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS stream_health (
            id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
            stream_id TEXT NOT NULL REFERENCES streams(id) ON DELETE CASCADE,
            rtmp_status TEXT NOT NULL DEFAULT 'unknown',
            video_fps INTEGER DEFAULT 0,
            bitrate_kbps INTEGER DEFAULT 0,
            dropped_frames REAL DEFAULT 0,
            audio_status TEXT NOT NULL DEFAULT 'unknown',
            encoder_status TEXT NOT NULL DEFAULT 'unknown',
            disk_usage_percent REAL DEFAULT 0,
            cpu_usage_percent REAL DEFAULT 0,
            memory_usage_percent REAL DEFAULT 0,
            recorded_at TEXT NOT NULL DEFAULT (datetime('now')),
            deleted_at TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS schedules (
            id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
            channel_id TEXT NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            cron_expression TEXT,
            timezone TEXT NOT NULL DEFAULT 'UTC',
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            deleted_at TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS schedule_items (
            id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
            schedule_id TEXT NOT NULL REFERENCES schedules(id) ON DELETE CASCADE,
            content_id TEXT NOT NULL REFERENCES content(id) ON DELETE CASCADE,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            deleted_at TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS youtube_accounts (
            id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
            user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            channel_id_youtube TEXT,
            access_token_encrypted TEXT,
            refresh_token_encrypted TEXT,
            token_expires_at TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            deleted_at TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS analytics (
            id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
            channel_id TEXT NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
            date TEXT NOT NULL,
            total_streams INTEGER DEFAULT 0,
            total_viewer_hours REAL DEFAULT 0,
            peak_concurrent_viewers INTEGER DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            deleted_at TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS analytics_snapshots (
            id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
            analytics_id TEXT NOT NULL REFERENCES analytics(id) ON DELETE CASCADE,
            snapshot_data TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            deleted_at TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
            type TEXT NOT NULL,
            priority INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'running', 'completed', 'failed', 'retry_pending')),
            attempt INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL DEFAULT 3,
            payload TEXT NOT NULL DEFAULT '{}',
            error TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            started_at TEXT,
            completed_at TEXT,
            deleted_at TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS job_attempts (
            id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
            job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
            attempt INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'completed', 'failed')),
            error TEXT,
            started_at TEXT NOT NULL DEFAULT (datetime('now')),
            completed_at TEXT,
            deleted_at TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS audit_logs (
            id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
            user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
            action TEXT NOT NULL,
            resource_type TEXT NOT NULL,
            resource_id TEXT,
            details TEXT NOT NULL DEFAULT '{}',
            ip_address TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            deleted_at TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS system_events (
            id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
            event_type TEXT NOT NULL,
            event_data TEXT NOT NULL DEFAULT '{}',
            severity TEXT NOT NULL DEFAULT 'info' CHECK (severity IN ('debug', 'info', 'warning', 'error', 'critical')),
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            deleted_at TEXT
        )
        """,
    ]

    for stmt in statements:
        conn.execute(stmt)

    _create_indexes(conn)


def _create_indexes(conn: sqlite3.Connection) -> None:
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)",
        "CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)",
        "CREATE INDEX IF NOT EXISTS idx_channels_org ON channels(organization_id)",
        "CREATE INDEX IF NOT EXISTS idx_agent_runs_agent ON agent_runs(agent_id)",
        "CREATE INDEX IF NOT EXISTS idx_agent_runs_status ON agent_runs(status)",
        "CREATE INDEX IF NOT EXISTS idx_content_channel ON content(channel_id)",
        "CREATE INDEX IF NOT EXISTS idx_content_state ON content(state)",
        "CREATE INDEX IF NOT EXISTS idx_playlists_channel ON playlists(channel_id)",
        "CREATE INDEX IF NOT EXISTS idx_playlist_items_playlist ON playlist_items(playlist_id)",
        "CREATE INDEX IF NOT EXISTS idx_tracks_deleted ON tracks(deleted_at)",
        "CREATE INDEX IF NOT EXISTS idx_track_rights_track ON track_rights(track_id)",
        "CREATE INDEX IF NOT EXISTS idx_streams_channel ON streams(channel_id)",
        "CREATE INDEX IF NOT EXISTS idx_streams_state ON streams(state)",
        "CREATE INDEX IF NOT EXISTS idx_stream_events_stream ON stream_events(stream_id)",
        "CREATE INDEX IF NOT EXISTS idx_stream_health_stream ON stream_health(stream_id)",
        "CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)",
        "CREATE INDEX IF NOT EXISTS idx_jobs_type ON jobs(type)",
        "CREATE INDEX IF NOT EXISTS idx_audit_logs_user ON audit_logs(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_system_events_type ON system_events(event_type)",
        "CREATE INDEX IF NOT EXISTS idx_system_events_severity ON system_events(severity)",
    ]
    for stmt in indexes:
        conn.execute(stmt)
