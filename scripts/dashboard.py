"""Admin Dashboard for zMusic.

Provides an operational dashboard for monitoring channels, live streams,
agents, jobs, analytics, and system health.

Features:
- Channel overview with status
- Live stream health monitoring
- Agent job tracking
- Analytics snapshots
- System metrics
- Configuration references
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .analytics import get_analytics
from .config import AppConfig
from .database import get_connection
from .logging import get_logger
from .monitoring import get_monitor
from .youtube import get_youtube

logger = get_logger("zmusic.dashboard")


@dataclass
class ChannelDashboardInfo:
    """Dashboard information for a single channel."""

    channel_id: str
    channel_name: str
    status: str  # active, idle, error, stopped
    current_stream: str | None = None
    streams_today: int = 0
    total_viewer_hours: float = 0.0
    average_duration: float = 0.0
    last_stream: str | None = None


@dataclass
class StreamDashboardInfo:
    """Dashboard information for a single stream."""

    stream_id: str
    channel_id: str
    status: str  # live, degraded, stopped, error, preflight, live
    started_at: str | None = None
    ended_at: str | None = None
    duration_seconds: float = 0.0
    peak_viewers: int = 0
    average_view_duration: float = 0.0
    retention_rate: float = 0.0
    interruptions: int = 0
    reconnects: int = 0
    rtmp_status: str = "unknown"
    encoder_status: str = "unknown"


@dataclass
class AgentJobDashboard:
    """Dashboard information for an agent job."""

    job_id: str
    agent_name: str
    status: str  # created, planned, generating, validating, ready, completed, failed
    started_at: str | None = None
    completed_at: str | None = None
    duration_seconds: float = 0.0
    error: str | None = None
    payload_summary: dict[str, Any] | None = None


@dataclass
class SystemMetrics:
    """System-level metrics for the dashboard."""

    cpu_usage: float = 0.0
    memory_usage: float = 0.0
    disk_usage: float = 0.0
    active_streams: int = 0
    total_streams_today: int = 0
    active_agents: int = 0
    failed_agents: int = 0


class DashboardEngine:
    """Core dashboard engine that collects and aggregates all dashboard data."""

    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config or AppConfig()
        self._analytics = get_analytics()
        self._monitor = get_monitor()
        self._youtube = get_youtube()

    def get_channel_dashboard(self, channel_id: str) -> ChannelDashboardInfo:
        """Get dashboard data for a specific channel."""
        # Query database for channel info and stream statistics
        conn = get_connection()
        try:
            # Get channel basic info from organizations/channels tables
            row = conn.execute(
                """SELECT c.id, c.name 
                   FROM channels c 
                   WHERE c.id = ? AND c.deleted_at IS NULL""",
                (channel_id,),
            ).fetchone()

            if row is None:
                return ChannelDashboardInfo(
                    channel_id=channel_id,
                    channel_name="",
                    status="unknown",
                )

            channel_name = row["name"]

            # Get stream statistics for this channel
            stream_stats = conn.execute(
                """SELECT 
                    COUNT(*) as streams_today,
                    SUM(CASE WHEN started_at >= date('now') THEN 1 ELSE 0 END) as today_streams,
                    COALESCE(SUM(EXTRACT(EPOCHDURATION FROM (ended_at - started_at))), 0) as total_duration,
                    COALESCE(AVG(EXTRACT(EPOCHDURATION FROM (ended_at - started_at))), 0) as avg_duration
                  FROM stream_sessions 
                  WHERE stream_id IN (
                      SELECT stream_id FROM stream_sessions 
                      WHERE channel_id = ? AND deleted_at IS NULL
                  )""",
                (channel_id, channel_id),
            ).fetchone()

            # Get last stream
            last_stream = conn.execute(
                """SELECT started_at FROM stream_sessions 
                   WHERE channel_id = ? AND deleted_at IS NULL 
                   ORDER BY started_at DESC LIMIT 1""",
                (channel_id,),
            ).fetchone()

            # Determine status based on active streams
            active = conn.execute(
                """SELECT COUNT(*) FROM stream_sessions 
                   WHERE channel_id = ? AND ended_at IS NULL AND deleted_at IS NULL""",
                (channel_id,),
            ).fetchone()

            streams_today = stream_stats["streams_today"] if stream_stats else 0
            total_viewer_hours = (
                (stream_stats["total_duration"] or 0) / 3600.0 if stream_stats else 0.0
            )
            avg_duration = (
                (stream_stats["avg_duration"] or 0) / 60.0 if stream_stats else 0.0
            )

            status = "active" if (active["COUNT(*)"] or 0) > 0 else "idle"

            return ChannelDashboardInfo(
                channel_id=row["id"],
                channel_name=channel_name,
                status=status,
                current_stream=last_stream["started_at"] if last_stream else None,
                streams_today=streams_today,
                total_viewer_hours=round(total_viewer_hours, 2),
                average_duration=round(avg_duration, 2),
                last_stream=last_stream["started_at"] if last_stream else None,
            )
        finally:
            conn.close()

    def get_stream_dashboard(self, stream_id: str) -> StreamDashboardInfo:
        """Get dashboard data for a specific stream."""
        conn = get_connection()
        try:
            row = conn.execute(
                """SELECT 
                    ss.id, ss.channel_id, ss.started_at, ss.ended_at,
                    ss.peak_viewers, ss.watch_time_seconds,
                    ss.average_view_duration_seconds, ss.retention,
                    ss.interruptions
                  FROM stream_sessions ss
                  WHERE ss.id = ? AND ss.deleted_at IS NULL
                  ORDER BY ss.started_at DESC LIMIT 1""",
                (stream_id,),
            ).fetchone()

            if row is None:
                return StreamDashboardInfo(
                    stream_id=stream_id, channel_id="", status="not_found"
                )

            # Get RTMP/encoder status from monitoring
            monitor_info = self._monitor.get_stream_status(stream_id)

            started_at = row["started_at"]
            ended_at = row["ended_at"]
            duration_seconds = 0.0
            if started_at and ended_at:
                from datetime import datetime

                start_dt = datetime.fromisoformat(started_at)
                end_dt = datetime.fromisoformat(ended_at)
                duration_seconds = (end_dt - start_dt).total_seconds()

            return StreamDashboardInfo(
                stream_id=row["id"],
                channel_id=row["channel_id"] or "",
                status=monitor_info.get("status", "unknown"),
                started_at=started_at,
                ended_at=ended_at,
                duration_seconds=duration_seconds,
                peak_viewers=row["peak_viewers"] or 0,
                average_view_duration=row["average_view_duration_seconds"] or 0.0,
                retention_rate=row["retention"] or 0.0,
                interruptions=row["interruptions"] or 0,
                rtmp_status=monitor_info.get("rtmp_status", "unknown"),
                encoder_status=monitor_info.get("encoder_status", "unknown"),
            )
        finally:
            conn.close()

    def get_agent_jobs_dashboard(
        self, agent_name: str | None = None
    ) -> list[AgentJobDashboard]:
        """Get dashboard data for agent jobs."""
        # This would query a job table; for now return structure
        # In a full implementation, there would be an agent_jobs table
        jobs: list[AgentJobDashboard] = []

        # Placeholder: query from any existing job tracking
        conn = get_connection()
        try:
            # Check if agent_jobs table exists
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='agent_jobs'"
            ).fetchone()
            if tables:
                rows = conn.execute(
                    """SELECT job_id, agent_name, status, started_at, completed_at, 
                              duration_seconds, error, payload
                       FROM agent_jobs 
                       WHERE agent_name = ? OR ? IS NULL
                       ORDER BY started_at DESC LIMIT 20""",
                    (agent_name, agent_name),
                ).fetchall()
                for row in rows:
                    jobs.append(
                        AgentJobDashboard(
                            job_id=row["job_id"],
                            agent_name=row["agent_name"],
                            status=row["status"],
                            started_at=row["started_at"],
                            completed_at=row["completed_at"],
                            duration_seconds=row["duration_seconds"] or 0.0,
                            error=row["error"],
                            payload_summary=(
                                json.loads(row["payload"]) if row["payload"] else None
                            ),
                        )
                    )
        finally:
            conn.close()

        return jobs

    def get_system_metrics(self) -> SystemMetrics:
        """Get system-level metrics."""
        # Get active streams count
        conn = get_connection()
        try:
            active_streams = conn.execute(
                "SELECT COUNT(*) FROM stream_sessions WHERE ended_at IS NULL AND deleted_at IS NULL"
            ).fetchone()[0]

            total_today = conn.execute(
                """SELECT COUNT(*) FROM stream_sessions 
                   WHERE started_at >= date('now') AND deleted_at IS NULL""",
            ).fetchone()[0]
        finally:
            conn.close()

        return SystemMetrics(
            cpu_usage=(
                self._monitor.cpu_usage if hasattr(self._monitor, "cpu_usage") else 0.0
            ),
            memory_usage=(
                self._monitor.memory_usage
                if hasattr(self._monitor, "memory_usage")
                else 0.0
            ),
            disk_usage=(
                self._monitor.disk_usage
                if hasattr(self._monitor, "disk_usage")
                else 0.0
            ),
            active_streams=active_streams,
            total_streams_today=total_today,
            active_agents=0,  # Would query agent registry
            failed_agents=0,  # Would query agent error logs
        )

    def get_overview(self) -> dict[str, Any]:
        """Get complete dashboard overview."""
        conn = get_connection()
        try:
            # Total channels
            total_channels = conn.execute(
                "SELECT COUNT(*) FROM channels WHERE deleted_at IS NULL"
            ).fetchone()[0]

            # Active channels
            active_channels = conn.execute(
                """SELECT COUNT(DISTINCT c.id) 
                   FROM channels c 
                   JOIN stream_sessions ss ON ss.channel_id = c.id 
                   WHERE ss.ended_at IS NULL AND c.deleted_at IS NULL""",
            ).fetchone()[0]

            # Total streams ever
            total_streams = conn.execute(
                "SELECT COUNT(*) FROM stream_sessions WHERE deleted_at IS NULL"
            ).fetchone()[0]

            # Active streams
            active_streams = conn.execute(
                "SELECT COUNT(*) FROM stream_sessions WHERE ended_at IS NULL AND deleted_at IS NULL"
            ).fetchone()[0]

            # Recent activity - last 5 streams
            recent_streams = conn.execute(
                """SELECT ss.id, ss.channel_id, ss.started_at, ss.ended_at,
                          c.name as channel_name
                   FROM stream_sessions ss
                   JOIN channels c ON ss.channel_id = c.id
                   WHERE ss.deleted_at IS NULL
                   ORDER BY ss.started_at DESC LIMIT 5""",
            ).fetchall()

            # System metrics
            system = self.get_system_metrics()

            return {
                "total_channels": total_channels,
                "active_channels": active_channels,
                "total_streams": total_streams,
                "active_streams": active_streams,
                "system_metrics": {
                    "cpu_usage": system.cpu_usage,
                    "memory_usage": system.memory_usage,
                    "disk_usage": system.disk_usage,
                    "active_streams": system.active_streams,
                    "total_streams_today": system.total_streams_today,
                },
                "recent_streams": [
                    {
                        "id": s["id"],
                        "channel": s["channel_name"],
                        "started_at": s["started_at"],
                        "ended_at": s["ended_at"],
                    }
                    for s in recent_streams
                ],
            }
        finally:
            conn.close()


# Global instance
_dashboard: DashboardEngine | None = None


def get_dashboard(config: AppConfig | None = None) -> DashboardEngine:
    """Return the global dashboard engine (singleton)."""
    global _dashboard
    if _dashboard is None:
        _dashboard = DashboardEngine(config)
    return _dashboard


def main() -> None:
    """CLI entry point for dashboard."""
    import argparse

    parser = argparse.ArgumentParser(description="zMusic Admin Dashboard")
    parser.add_argument(
        "--overview", action="store_true", help="Show dashboard overview"
    )
    parser.add_argument("--channel", type=str, help="Show channel dashboard info")
    parser.add_argument("--stream", type=str, help="Show stream dashboard info")
    parser.add_argument("--system", action="store_true", help="Show system metrics")
    parser.add_argument("--agent-jobs", type=str, help="Show agent jobs for agent")

    args = parser.parse_args()

    dashboard = get_dashboard()

    if args.overview:
        overview = dashboard.get_overview()
        print(json.dumps(overview, indent=2, default=str))
    elif args.channel:
        ch = dashboard.get_channel_dashboard(args.channel)
        print(
            json.dumps(
                {
                    "channel_id": ch.channel_id,
                    "channel_name": ch.channel_name,
                    "status": ch.status,
                    "current_stream": ch.current_stream,
                    "streams_today": ch.streams_today,
                    "total_viewer_hours": ch.total_viewer_hours,
                    "average_duration": ch.average_duration,
                    "last_stream": ch.last_stream,
                },
                indent=2,
                default=str,
            )
        )
    elif args.stream:
        stream = dashboard.get_stream_dashboard(args.stream)
        print(
            json.dumps(
                {
                    "stream_id": stream.stream_id,
                    "channel_id": stream.channel_id,
                    "status": stream.status,
                    "started_at": stream.started_at,
                    "ended_at": stream.ended_at,
                    "duration_seconds": stream.duration_seconds,
                    "peak_viewers": stream.peak_viewers,
                    "average_view_duration": stream.average_view_duration,
                    "retention_rate": stream.retention_rate,
                    "interruptions": stream.interruptions,
                    "rtmp_status": stream.rtmp_status,
                    "encoder_status": stream.encoder_status,
                },
                indent=2,
                default=str,
            )
        )
    elif args.system:
        system = dashboard.get_system_metrics()
        print(
            json.dumps(
                {
                    "cpu_usage": system.cpu_usage,
                    "memory_usage": system.memory_usage,
                    "disk_usage": system.disk_usage,
                    "active_streams": system.active_streams,
                    "total_streams_today": system.total_streams_today,
                    "active_agents": system.active_agents,
                    "failed_agents": system.failed_agents,
                },
                indent=2,
                default=str,
            )
        )
    elif args.agent_jobs:
        jobs = dashboard.get_agent_jobs_dashboard(args.agent_jobs)
        print(
            json.dumps(
                [
                    {
                        "job_id": j.job_id,
                        "agent_name": j.agent_name,
                        "status": j.status,
                        "started_at": j.started_at,
                        "completed_at": j.completed_at,
                        "duration_seconds": j.duration_seconds,
                        "error": j.error,
                    }
                    for j in jobs
                ],
                indent=2,
                default=str,
            )
        )
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
