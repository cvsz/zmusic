"""Analytics collection and reporting for zMusic.

Collects stream and content analytics, generates snapshots, and produces
reports. All data is stored in the database and aggregated for dashboards.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .config import AppConfig
from .database import _local, get_connection, transaction
from .logging import get_logger

logger = get_logger("zmusic.analytics")


@dataclass(frozen=True)
class AnalyticsSnapshot:
    """A point-in-time analytics snapshot."""

    id: str
    analytics_id: str
    snapshot_data: dict[str, Any]
    created_at: str


@dataclass
class StreamMetrics:
    """Metrics for a single stream session."""

    stream_id: str
    channel_id: str
    started_at: str
    ended_at: str | None = None
    duration_seconds: float = 0.0
    peak_viewers: int = 0
    total_viewer_hours: float = 0.0
    average_view_duration: float = 0.0
    retention_rate: float = 0.0
    interruptions: int = 0
    reconnects: int = 0


class AnalyticsCollector:
    """Collects and aggregates analytics data."""

    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config

    def record_stream_session(
        self,
        stream_id: str,
        channel_id: str,
        started_at: str,
    ) -> str:
        """Record the start of a stream session. Returns the session ID."""
        session_id = str(uuid.uuid4())
        now = datetime.now(tz=UTC).isoformat()

        with transaction() as conn:
            conn.execute(
                """
                INSERT INTO stream_sessions
                (id, stream_id, channel_id, viewer_count, watch_time_seconds,
                 average_view_duration_seconds, retention, peak_viewers,
                 interruptions, started_at, ended_at)
                VALUES (?, ?, ?, 0, 0, 0, 0, 0, 0, ?, NULL)
                """,
                (session_id, stream_id, channel_id, started_at),
            )
            self._insert_event(
                conn,
                stream_id,
                "stream.started",
                {"session_id": session_id, "channel_id": channel_id},
            )

        logger.info(
            "Stream session recorded",
            extra={
                "session_id": session_id,
                "stream_id": stream_id,
                "channel_id": channel_id,
            },
        )
        return session_id

    def end_stream_session(
        self,
        session_id: str,
        ended_at: str | None = None,
    ) -> None:
        """End a stream session."""
        if ended_at is None:
            ended_at = datetime.now(tz=UTC).isoformat()

        with transaction() as conn:
            conn.execute(
                """
                UPDATE stream_sessions
                SET ended_at = ?
                WHERE id = ? AND deleted_at IS NULL
                """,
                (ended_at, session_id),
            )
            # Get stream_id for the event
            row = conn.execute(
                "SELECT stream_id FROM stream_sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            if row:
                self._insert_event(
                    conn,
                    row["stream_id"],
                    "stream.stopped",
                    {"session_id": session_id, "ended_at": ended_at},
                )

        logger.info(
            "Stream session ended",
            extra={"session_id": session_id, "ended_at": ended_at},
        )

    def record_viewer_count(
        self,
        session_id: str,
        viewer_count: int,
    ) -> None:
        """Record a viewer count sample for a session."""
        now = datetime.now(tz=UTC).isoformat()
        with transaction() as conn:
            conn.execute(
                """
                UPDATE stream_sessions
                SET peak_viewers = MAX(peak_viewers, ?),
                    watch_time_seconds = watch_time_seconds + ?
                WHERE id = ? AND deleted_at IS NULL
                """,
                (viewer_count, 60, session_id),  # Assume 60-second sample
            )
            row = conn.execute(
                "SELECT stream_id FROM stream_sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            if row:
                self._insert_event(
                    conn,
                    row["stream_id"],
                    "track.started",
                    {"session_id": session_id, "viewer_count": viewer_count},
                )

    def record_stream_event(
        self,
        stream_id: str,
        event_type: str,
        event_data: dict[str, Any] | None = None,
    ) -> None:
        """Record a domain event for a stream."""
        event_id = str(uuid.uuid4())
        now = datetime.now(tz=UTC).isoformat()
        with transaction() as conn:
            conn.execute(
                """
                INSERT INTO stream_events
                (id, stream_id, event_type, event_data, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    stream_id,
                    event_type,
                    json.dumps(event_data or {}),
                    now,
                ),
            )
        logger.debug(
            "Stream event recorded",
            extra={"stream_id": stream_id, "event_type": event_type},
        )

    def _insert_event(
        self,
        conn: Any,
        stream_id: str,
        event_type: str,
        event_data: dict[str, Any],
    ) -> None:
        """Insert a stream event within an existing transaction."""
        event_id = str(uuid.uuid4())
        now = datetime.now(tz=UTC).isoformat()
        conn.execute(
            """
            INSERT INTO stream_events
            (id, stream_id, event_type, event_data, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                event_id,
                stream_id,
                event_type,
                json.dumps(event_data),
                now,
            ),
        )

    def compute_stream_metrics(
        self,
        stream_id: str,
    ) -> StreamMetrics:
        """Compute aggregated metrics for a stream."""
        conn = get_connection()
        try:
            row = conn.execute(
                """
                SELECT stream_id, channel_id, started_at, ended_at,
                       peak_viewers, watch_time_seconds,
                       average_view_duration_seconds, retention,
                       interruptions
                FROM stream_sessions
                WHERE stream_id = ? AND deleted_at IS NULL
                ORDER BY started_at DESC
                LIMIT 1
                """,
                (stream_id,),
            ).fetchone()

            if row is None:
                return StreamMetrics(
                    stream_id=stream_id,
                    channel_id="",
                    started_at="",
                )

            started_at = row["started_at"]
            ended_at = row["ended_at"]
            duration_seconds = 0.0
            if ended_at:
                start_dt = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
                end_dt = datetime.fromisoformat(ended_at.replace("Z", "+00:00"))
                duration_seconds = (end_dt - start_dt).total_seconds()

            watch_time_seconds = row["watch_time_seconds"] or 0
            total_viewer_hours = watch_time_seconds / 3600.0

            return StreamMetrics(
                stream_id=row["stream_id"],
                channel_id=row["channel_id"],
                started_at=started_at,
                ended_at=ended_at,
                duration_seconds=duration_seconds,
                peak_viewers=row["peak_viewers"] or 0,
                total_viewer_hours=round(total_viewer_hours, 2),
                average_view_duration=row["average_view_duration_seconds"] or 0.0,
                retention_rate=row["retention"] or 0.0,
                interruptions=row["interruptions"] or 0,
            )
        finally:
            conn.close()
            _local.conn = None

    def record_analytics_snapshot(
        self,
        channel_id: str,
        date: str,
        snapshot_data: dict[str, Any],
    ) -> str:
        """Record an analytics snapshot for a channel on a date."""
        analytics_id = str(uuid.uuid4())
        snapshot_id = str(uuid.uuid4())
        now = datetime.now(tz=UTC).isoformat()

        with transaction() as conn:
            # Upsert analytics record
            existing = conn.execute(
                "SELECT id FROM analytics WHERE channel_id = ? AND date = ? AND deleted_at IS NULL",
                (channel_id, date),
            ).fetchone()
            if existing:
                analytics_id = existing["id"]
                conn.execute(
                    """
                    UPDATE analytics
                    SET total_streams = total_streams + ?,
                        total_viewer_hours = total_viewer_hours + ?,
                        peak_concurrent_viewers = MAX(peak_concurrent_viewers, ?),
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        snapshot_data.get("total_streams", 0),
                        snapshot_data.get("total_viewer_hours", 0.0),
                        snapshot_data.get("peak_concurrent_viewers", 0),
                        now,
                        analytics_id,
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO analytics
                    (id, channel_id, date, total_streams, total_viewer_hours,
                     peak_concurrent_viewers, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        analytics_id,
                        channel_id,
                        date,
                        snapshot_data.get("total_streams", 0),
                        snapshot_data.get("total_viewer_hours", 0.0),
                        snapshot_data.get("peak_concurrent_viewers", 0),
                        now,
                    ),
                )

            conn.execute(
                """
                INSERT INTO analytics_snapshots
                (id, analytics_id, snapshot_data, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    analytics_id,
                    json.dumps(snapshot_data),
                    now,
                ),
            )

        logger.info(
            "Analytics snapshot recorded",
            extra={
                "channel_id": channel_id,
                "date": date,
                "snapshot_id": snapshot_id,
            },
        )
        return snapshot_id

    def get_channel_analytics(
        self,
        channel_id: str,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[dict[str, Any]]:
        """Retrieve analytics records for a channel."""
        conn = get_connection()
        try:
            query = """
                SELECT id, channel_id, date, total_streams,
                       total_viewer_hours, peak_concurrent_viewers,
                       created_at
                FROM analytics
                WHERE channel_id = ? AND deleted_at IS NULL
            """
            params: list[str] = [channel_id]
            if start_date:
                query += " AND date >= ?"
                params.append(start_date)
            if end_date:
                query += " AND date <= ?"
                params.append(end_date)
            query += " ORDER BY date"

            rows = conn.execute(query, params).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def generate_post_stream_report(
        self,
        stream_id: str,
    ) -> dict[str, Any]:
        """Generate a post-stream report for a stream."""
        metrics = self.compute_stream_metrics(stream_id)
        conn = get_connection()
        try:
            events = conn.execute(
                """
                SELECT event_type, event_data, created_at
                FROM stream_events
                WHERE stream_id = ? AND deleted_at IS NULL
                ORDER BY created_at
                """,
                (stream_id,),
            ).fetchall()

            event_list = [
                {
                    "event_type": row["event_type"],
                    "event_data": json.loads(row["event_data"]),
                    "created_at": row["created_at"],
                }
                for row in events
            ]

            report = {
                "stream_id": stream_id,
                "generated_at": datetime.now(tz=UTC).isoformat(),
                "metrics": {
                    "duration_seconds": metrics.duration_seconds,
                    "peak_viewers": metrics.peak_viewers,
                    "total_viewer_hours": metrics.total_viewer_hours,
                    "average_view_duration": metrics.average_view_duration,
                    "retention_rate": metrics.retention_rate,
                    "interruptions": metrics.interruptions,
                },
                "events": event_list,
            }
            logger.info(
                "Post-stream report generated",
                extra={"stream_id": stream_id},
            )
            return report
        finally:
            conn.close()


# Global instance
_analytics: AnalyticsCollector | None = None


def get_analytics(config: AppConfig | None = None) -> AnalyticsCollector:
    """Return the global analytics collector (singleton)."""
    global _analytics
    if _analytics is None:
        _analytics = AnalyticsCollector(config)
    return _analytics
