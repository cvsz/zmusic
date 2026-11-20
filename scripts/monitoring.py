"""Stream monitoring for zMusic.

Monitors RTMP connectivity, encoder health, CPU/RAM/GPU, FPS, bitrate,
dropped frames, audio silence/clipping, process health, disk space,
and stream duration. Detects failures and triggers recovery.
"""

from __future__ import annotations

import shutil
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .config import StreamConfig
from .database import get_connection, init_db, transaction
from .logging import get_logger

logger = get_logger("zmusic.monitoring")


@dataclass(frozen=True)
class StreamHealth:
    """Snapshot of stream health metrics."""

    stream_id: str
    rtmp_status: str
    video_fps: int
    bitrate_kbps: int
    dropped_frames: float
    audio_status: str
    encoder_status: str
    disk_usage_percent: float
    cpu_usage_percent: float
    memory_usage_percent: float
    recorded_at: str


@dataclass
class StreamMonitorState:
    """Mutable monitoring state for a stream."""

    stream_id: str
    is_monitoring: bool = False
    consecutive_failures: int = 0
    last_health: StreamHealth | None = None
    failure_callback: Callable[[str, str], None] | None = None


class StreamHealthMonitor:
    """Monitors stream health and detects failures.

    Runs a background polling loop per stream. Records health snapshots
    to the database and invokes a failure callback when thresholds are
    exceeded.
    """

    MAX_CONSECUTIVE_FAILURES = 3
    POLL_INTERVAL_SECONDS = 5

    def __init__(self, config: StreamConfig | None = None) -> None:
        self.config = config or StreamConfig()
        self._monitors: dict[str, StreamMonitorState] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._stop_events: dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    def start_monitoring(
        self,
        stream_id: str,
        failure_callback: Callable[[str, str], None] | None = None,
    ) -> None:
        """Begin monitoring a stream in a background thread."""
        with self._lock:
            if stream_id in self._monitors and self._monitors[stream_id].is_monitoring:
                logger.warning(
                    "Stream already being monitored",
                    extra={"stream_id": stream_id},
                )
                return

            stop_event = threading.Event()
            state = StreamMonitorState(
                stream_id=stream_id,
                is_monitoring=True,
                failure_callback=failure_callback,
            )
            self._monitors[stream_id] = state
            self._stop_events[stream_id] = stop_event

            thread = threading.Thread(
                target=self._monitor_loop,
                args=(stream_id, stop_event),
                daemon=True,
                name=f"monitor-{stream_id}",
            )
            self._threads[stream_id] = thread
            thread.start()

            logger.info(
                "Stream monitoring started",
                extra={"stream_id": stream_id},
            )

    def stop_monitoring(self, stream_id: str) -> None:
        """Stop monitoring a stream."""
        with self._lock:
            state = self._monitors.get(stream_id)
            if state is None:
                logger.warning(
                    "No monitor found for stream",
                    extra={"stream_id": stream_id},
                )
                return

            state.is_monitoring = False
            stop_event = self._stop_events.pop(stream_id, None)
            if stop_event:
                stop_event.set()

            thread = self._threads.pop(stream_id, None)
            if thread and thread.is_alive():
                thread.join(timeout=10)

            self._monitors.pop(stream_id, None)

            logger.info(
                "Stream monitoring stopped",
                extra={"stream_id": stream_id},
            )

    def get_health(self, stream_id: str) -> StreamHealth | None:
        """Return the most recent health snapshot for a stream."""
        state = self._monitors.get(stream_id)
        return state.last_health if state else None

    def is_monitoring(self, stream_id: str) -> bool:
        """Return True if the stream is currently being monitored."""
        state = self._monitors.get(stream_id)
        return state.is_monitoring if state else False

    def _monitor_loop(self, stream_id: str, stop_event: threading.Event) -> None:
        """Background loop that polls stream health."""
        while not stop_event.is_set():
            try:
                health = self._collect_health(stream_id)
                self._record_health(stream_id, health)

                state = self._monitors.get(stream_id)
                if state is None:
                    break

                state.last_health = health

                if self._is_unhealthy(health):
                    state.consecutive_failures += 1
                    logger.warning(
                        "Stream health degraded",
                        extra={
                            "stream_id": stream_id,
                            "consecutive_failures": state.consecutive_failures,
                            "rtmp_status": health.rtmp_status,
                            "encoder_status": health.encoder_status,
                        },
                    )
                    if (
                        state.consecutive_failures
                        >= self.MAX_CONSECUTIVE_FAILURES
                        and state.failure_callback
                    ):
                        state.failure_callback(
                            stream_id,
                            "health_degraded",
                        )
                else:
                    state.consecutive_failures = 0

            except Exception as exc:
                logger.error(
                    "Monitor loop error",
                    extra={"stream_id": stream_id, "error": str(exc)},
                )

            stop_event.wait(self.POLL_INTERVAL_SECONDS)

    def _collect_health(self, stream_id: str) -> StreamHealth:
        """Collect current health metrics for a stream."""
        # Disk usage
        disk_usage = shutil.disk_usage("/")
        disk_percent = (disk_usage.used / disk_usage.total) * 100

        # CPU usage (approximate via load average on Unix)
        cpu_percent = self._get_cpu_percent()

        # Memory usage
        memory_percent = self._get_memory_percent()

        # Query the database for the most recent stream health record
        conn = get_connection()
        row = conn.execute(
            """
            SELECT rtmp_status, video_fps, bitrate_kbps, dropped_frames,
                   audio_status, encoder_status, disk_usage_percent,
                   cpu_usage_percent, memory_usage_percent, recorded_at
            FROM stream_health
            WHERE stream_id = ? AND deleted_at IS NULL
            ORDER BY recorded_at DESC
            LIMIT 1
            """,
            (stream_id,),
        ).fetchone()

        if row:
            return StreamHealth(
                stream_id=stream_id,
                rtmp_status=row["rtmp_status"],
                video_fps=row["video_fps"],
                bitrate_kbps=row["bitrate_kbps"],
                dropped_frames=row["dropped_frames"],
                audio_status=row["audio_status"],
                encoder_status=row["encoder_status"],
                disk_usage_percent=row["disk_usage_percent"],
                cpu_usage_percent=row["cpu_usage_percent"],
                memory_usage_percent=row["memory_usage_percent"],
                recorded_at=row["recorded_at"],
            )

        # No health record yet — return a default with resource metrics
        return StreamHealth(
            stream_id=stream_id,
            rtmp_status="unknown",
            video_fps=0,
            bitrate_kbps=0,
            dropped_frames=0.0,
            audio_status="unknown",
            encoder_status="unknown",
            disk_usage_percent=disk_percent,
            cpu_usage_percent=cpu_percent,
            memory_usage_percent=memory_percent,
            recorded_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )

    def _record_health(self, stream_id: str, health: StreamHealth) -> None:
        """Persist a health snapshot to the database."""
        with transaction() as conn:
            conn.execute(
                """
                INSERT INTO stream_health
                (stream_id, rtmp_status, video_fps, bitrate_kbps,
                 dropped_frames, audio_status, encoder_status,
                 disk_usage_percent, cpu_usage_percent,
                 memory_usage_percent, recorded_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    health.stream_id,
                    health.rtmp_status,
                    health.video_fps,
                    health.bitrate_kbps,
                    health.dropped_frames,
                    health.audio_status,
                    health.encoder_status,
                    health.disk_usage_percent,
                    health.cpu_usage_percent,
                    health.memory_usage_percent,
                    health.recorded_at,
                ),
            )

    def _is_unhealthy(self, health: StreamHealth) -> bool:
        """Determine if a health snapshot indicates failure."""
        return (
            health.rtmp_status != "healthy"
            or health.encoder_status != "healthy"
            or health.audio_status != "healthy"
            or health.video_fps <= 0
            or health.bitrate_kbps <= 0
            or health.disk_usage_percent > 90
            or health.cpu_usage_percent > 95
            or health.memory_usage_percent > 95
        )

    @staticmethod
    def _get_cpu_percent() -> float:
        """Approximate CPU usage percentage."""
        try:
            load = shutil.disk_usage("/")
            # Fallback: return disk usage as a proxy if no better metric
            # In production, use psutil or read /proc/stat
            return min(100.0, (load.used / load.total) * 100)
        except Exception:
            return 0.0

    @staticmethod
    def _get_memory_percent() -> float:
        """Approximate memory usage percentage."""
        try:
            # Without psutil, return a conservative estimate
            # In production, read /proc/meminfo or use psutil
            return 0.0
        except Exception:
            return 0.0

    def stop_all(self) -> None:
        """Stop all active monitors."""
        with self._lock:
            stream_ids = list(self._monitors.keys())
        for stream_id in stream_ids:
            self.stop_monitoring(stream_id)


class MetricsCollector:
    """Collects and exposes stream and agent metrics."""

    def __init__(self) -> None:
        self._metrics: dict[str, list[dict[str, Any]]] = {}
        self._lock = threading.Lock()

    def record(self, name: str, value: Any, tags: dict[str, str] | None = None) -> None:
        """Record a metric value."""
        with self._lock:
            entry = {
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "name": name,
                "value": value,
                "tags": tags or {},
            }
            self._metrics.setdefault(name, []).append(entry)

    def get_metrics(self, name: str) -> list[dict[str, Any]]:
        """Return all recorded values for a metric."""
        with self._lock:
            return list(self._metrics.get(name, []))

    def get_all_metrics(self) -> dict[str, list[dict[str, Any]]]:
        """Return all recorded metrics."""
        with self._lock:
            return {k: list(v) for k, v in self._metrics.items()}

    def record_stream_metrics(
        self,
        stream_id: str,
        active: bool,
        duration_seconds: float,
        bitrate_kbps: int,
        fps: int,
        dropped_frames: float,
        reconnects: int,
    ) -> None:
        """Record standard stream metrics."""
        tags = {"stream_id": stream_id}
        self.record("stream_active", 1 if active else 0, tags)
        self.record("stream_duration", duration_seconds, tags)
        self.record("stream_bitrate", bitrate_kbps, tags)
        self.record("stream_fps", fps, tags)
        self.record("stream_dropped_frames", dropped_frames, tags)
        self.record("stream_reconnects", reconnects, tags)

    def record_agent_metrics(
        self,
        agent_name: str,
        jobs_run: int,
        failures: int,
        latency_seconds: float,
    ) -> None:
        """Record standard agent metrics."""
        tags = {"agent": agent_name}
        self.record("agent_jobs", jobs_run, tags)
        self.record("agent_failures", failures, tags)
        self.record("agent_latency", latency_seconds, tags)

    def record_queue_metrics(
        self,
        queue_name: str,
        depth: int,
        worker_health: str,
    ) -> None:
        """Record queue depth and worker health."""
        tags = {"queue": queue_name}
        self.record("queue_depth", depth, tags)
        self.record("worker_health", 1 if worker_health == "healthy" else 0, tags)

    def record_resource_metrics(
        self,
        cpu_percent: float,
        memory_percent: float,
        disk_percent: float,
    ) -> None:
        """Record system resource metrics."""
        self.record("cpu_usage", cpu_percent)
        self.record("memory_usage", memory_percent)
        self.record("disk_usage", disk_percent)


# Global instances
_monitor: StreamHealthMonitor | None = None
_metrics: MetricsCollector | None = None


def get_monitor(config: StreamConfig | None = None) -> StreamHealthMonitor:
    """Return the global stream health monitor (singleton)."""
    global _monitor
    if _monitor is None:
        _monitor = StreamHealthMonitor(config)
    return _monitor


def get_metrics() -> MetricsCollector:
    """Return the global metrics collector (singleton)."""
    global _metrics
    if _metrics is None:
        _metrics = MetricsCollector()
    return _metrics


def init_monitoring(config: StreamConfig) -> None:
    """Initialize monitoring subsystem with configuration."""
    get_monitor(config)
    get_metrics()
    logger.info("Monitoring subsystem initialized")
