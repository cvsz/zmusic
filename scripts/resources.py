"""Resource Management for zMusic.

Implements resource limits, worker concurrency, stream concurrency limits,
disk quotas, asset cleanup, temporary-file cleanup, and process supervision.

Before starting a stream:
  CHECK RESOURCES
        ↓
  CHECK ASSETS
        ↓
  CHECK RIGHTS
        ↓
  CHECK NETWORK
        ↓
  CHECK YOUTUBE
        ↓
  START
"""

from __future__ import annotations

import os
import shutil
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from .config import AppConfig
from .database import get_connection
from .logging import get_logger

logger = get_logger("zmusic.resources")


class ResourceType(Enum):
    """Types of resources that can be managed."""

    CPU = "cpu"
    MEMORY = "memory"
    DISK = "disk"
    STREAM = "stream"
    WORKER = "worker"
    NETWORK = "network"


class ResourceStatus(Enum):
    """Status of a resource check."""

    AVAILABLE = "available"
    LIMITED = "limited"
    EXHAUSTED = "exhausted"
    UNKNOWN = "unknown"


@dataclass
class ResourceLimit:
    """Definition of a resource limit."""

    resource_type: ResourceType
    max_value: float
    current_value: float = 0.0
    warning_threshold: float = 0.8  # 80% warning
    critical_threshold: float = 0.95  # 95% critical


@dataclass
class ResourceCheckResult:
    """Result of a resource check."""

    resource_type: ResourceType
    status: ResourceStatus
    current_value: float
    max_value: float
    available: float
    message: str = ""


@dataclass
class StreamResourceRequirements:
    """Resource requirements for starting a stream."""

    stream_id: str
    estimated_cpu_percent: float = 20.0
    estimated_memory_mb: float = 512.0
    estimated_disk_mb: float = 1024.0
    required_network_mbps: float = 5.0


class ResourceManager:
    """Manages system resources for streaming operations."""

    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config or AppConfig()

        # Default limits (can be configured via environment)
        self.limits: dict[ResourceType, ResourceLimit] = {
            ResourceType.CPU: ResourceLimit(
                ResourceType.CPU,
                max_value=self._get_cpu_limit(),
                warning_threshold=0.8,
                critical_threshold=0.95,
            ),
            ResourceType.MEMORY: ResourceLimit(
                ResourceType.MEMORY,
                max_value=self._get_memory_limit_mb(),
                warning_threshold=0.8,
                critical_threshold=0.95,
            ),
            ResourceType.DISK: ResourceLimit(
                ResourceType.DISK,
                max_value=self._get_disk_limit_mb(),
                warning_threshold=0.8,
                critical_threshold=0.95,
            ),
            ResourceType.STREAM: ResourceLimit(
                ResourceType.STREAM,
                max_value=self.config.stream.max_concurrent_streams,
                warning_threshold=0.8,
                critical_threshold=1.0,
            ),
            ResourceType.WORKER: ResourceLimit(
                ResourceType.WORKER,
                max_value=self._get_worker_limit(),
                warning_threshold=0.8,
                critical_threshold=0.95,
            ),
        }

        # Current usage tracking
        self._usage: dict[ResourceType, float] = {rt: 0.0 for rt in ResourceType}
        self._stream_usage: dict[str, StreamResourceRequirements] = {}
        self._lock = threading.Lock()

        # Start background monitoring
        self._monitoring = False
        self._monitor_thread: threading.Thread | None = None

    def _get_cpu_limit(self) -> float:
        """Get CPU limit (percent)."""
        return float(os.environ.get("ZMUSIC_CPU_LIMIT", "80.0"))

    def _get_memory_limit_mb(self) -> float:
        """Get memory limit (MB)."""
        return float(os.environ.get("ZMUSIC_MEMORY_LIMIT_MB", "4096.0"))

    def _get_disk_limit_mb(self) -> float:
        """Get disk limit (MB)."""
        return float(os.environ.get("ZMUSIC_DISK_LIMIT_MB", "10240.0"))

    def _get_worker_limit(self) -> float:
        """Get worker limit."""
        return float(os.environ.get("ZMUSIC_WORKER_LIMIT", "16.0"))

    def start_monitoring(self, interval: float = 5.0) -> None:
        """Start background resource monitoring."""
        if self._monitoring:
            return
        self._monitoring = True
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            args=(interval,),
            daemon=True,
        )
        self._monitor_thread.start()
        logger.info("Resource monitoring started")

    def stop_monitoring(self) -> None:
        """Stop background resource monitoring."""
        self._monitoring = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5.0)
        logger.info("Resource monitoring stopped")

    def _monitor_loop(self, interval: float) -> None:
        """Background monitoring loop."""
        while self._monitoring:
            try:
                self._update_usage()
                self._check_warnings()
            except Exception as e:  # noqa: BLE001
                logger.error("Resource monitoring error", extra={"error": str(e)})
            time.sleep(interval)

    def _update_usage(self) -> None:
        """Update current resource usage from system."""
        import psutil

        # CPU
        cpu_percent = psutil.cpu_percent(interval=0.1)
        with self._lock:
            self._usage[ResourceType.CPU] = cpu_percent

        # Memory
        memory = psutil.virtual_memory()
        memory_mb = memory.used / (1024 * 1024)
        with self._lock:
            self._usage[ResourceType.MEMORY] = memory_mb

        # Disk
        disk = shutil.disk_usage("/")
        disk_mb = disk.used / (1024 * 1024)
        with self._lock:
            self._usage[ResourceType.DISK] = disk_mb

        # Stream count
        conn = get_connection()
        try:
            active = conn.execute(
                "SELECT COUNT(*) FROM stream_sessions WHERE ended_at IS NULL AND deleted_at IS NULL"
            ).fetchone()[0]
            with self._lock:
                self._usage[ResourceType.STREAM] = float(active)
        except Exception:
            logger.warning("Failed to update stream usage", exc_info=True)
        finally:
            conn.close()

    def _check_warnings(self) -> None:
        """Check for resource warnings and log them."""
        for rt, limit in self.limits.items():
            current = self._usage.get(rt, 0.0)
            usage_ratio = current / limit.max_value if limit.max_value > 0 else 0.0

            if usage_ratio >= limit.critical_threshold:
                logger.critical(
                    f"Resource critical: {rt.value} at {usage_ratio:.1%}",
                    extra={
                        "resource": rt.value,
                        "current": current,
                        "max": limit.max_value,
                    },
                )
            elif usage_ratio >= limit.warning_threshold:
                logger.warning(
                    f"Resource warning: {rt.value} at {usage_ratio:.1%}",
                    extra={
                        "resource": rt.value,
                        "current": current,
                        "max": limit.max_value,
                    },
                )

    def check_resources(
        self, requirements: StreamResourceRequirements
    ) -> list[ResourceCheckResult]:
        """Check if resources are available for a stream."""
        results = []

        # CPU check
        cpu_current = self._usage.get(ResourceType.CPU, 0.0)
        cpu_limit = self.limits[ResourceType.CPU].max_value
        cpu_available = cpu_limit - cpu_current
        cpu_status = ResourceStatus.AVAILABLE
        if cpu_current + requirements.estimated_cpu_percent > cpu_limit * 0.95:
            cpu_status = ResourceStatus.EXHAUSTED
        elif cpu_current + requirements.estimated_cpu_percent > cpu_limit * 0.8:
            cpu_status = ResourceStatus.LIMITED

        results.append(
            ResourceCheckResult(
                resource_type=ResourceType.CPU,
                status=cpu_status,
                current_value=cpu_current,
                max_value=cpu_limit,
                available=cpu_available,
                message=f"CPU: {cpu_current:.1f}% used, {cpu_available:.1f}% available",
            )
        )

        # Memory check
        mem_current = self._usage.get(ResourceType.MEMORY, 0.0)
        mem_limit = self.limits[ResourceType.MEMORY].max_value
        mem_available = mem_limit - mem_current
        mem_status = ResourceStatus.AVAILABLE
        if mem_current + requirements.estimated_memory_mb > mem_limit * 0.95:
            mem_status = ResourceStatus.EXHAUSTED
        elif mem_current + requirements.estimated_memory_mb > mem_limit * 0.8:
            mem_status = ResourceStatus.LIMITED

        results.append(
            ResourceCheckResult(
                resource_type=ResourceType.MEMORY,
                status=mem_status,
                current_value=mem_current,
                max_value=mem_limit,
                available=mem_available,
                message=f"Memory: {mem_current:.1f}MB used, {mem_available:.1f}MB available",
            )
        )

        # Disk check
        disk_current = self._usage.get(ResourceType.DISK, 0.0)
        disk_limit = self.limits[ResourceType.DISK].max_value
        disk_available = disk_limit - disk_current
        disk_status = ResourceStatus.AVAILABLE
        if disk_current + requirements.estimated_disk_mb > disk_limit * 0.95:
            disk_status = ResourceStatus.EXHAUSTED
        elif disk_current + requirements.estimated_disk_mb > disk_limit * 0.8:
            disk_status = ResourceStatus.LIMITED

        results.append(
            ResourceCheckResult(
                resource_type=ResourceType.DISK,
                status=disk_status,
                current_value=disk_current,
                max_value=disk_limit,
                available=disk_available,
                message=f"Disk: {disk_current:.1f}MB used, {disk_available:.1f}MB available",
            )
        )

        # Stream count check
        stream_current = self._usage.get(ResourceType.STREAM, 0.0)
        stream_limit = self.limits[ResourceType.STREAM].max_value
        stream_available = stream_limit - stream_current
        stream_status = ResourceStatus.AVAILABLE
        if stream_current + 1 > stream_limit:
            stream_status = ResourceStatus.EXHAUSTED
        elif stream_current + 1 > stream_limit * 0.8:
            stream_status = ResourceStatus.LIMITED

        results.append(
            ResourceCheckResult(
                resource_type=ResourceType.STREAM,
                status=stream_status,
                current_value=stream_current,
                max_value=stream_limit,
                available=stream_available,
                message=f"Streams: {stream_current}/{stream_limit} active",
            )
        )

        return results

    def can_start_stream(
        self, requirements: StreamResourceRequirements
    ) -> tuple[bool, list[ResourceCheckResult]]:
        """Check if a stream can be started."""
        results = self.check_resources(requirements)
        can_start = all(r.status != ResourceStatus.EXHAUSTED for r in results)
        return can_start, results

    def reserve_stream_resources(
        self, stream_id: str, requirements: StreamResourceRequirements
    ) -> bool:
        """Reserve resources for a stream."""
        can_start, _results = self.can_start_stream(requirements)
        if not can_start:
            return False

        with self._lock:
            self._stream_usage[stream_id] = requirements
            # Update usage
            self._usage[ResourceType.CPU] += requirements.estimated_cpu_percent
            self._usage[ResourceType.MEMORY] += requirements.estimated_memory_mb
            self._usage[ResourceType.DISK] += requirements.estimated_disk_mb
            self._usage[ResourceType.STREAM] += 1.0

        logger.info(
            "Resources reserved for stream",
            extra={"stream_id": stream_id, "requirements": requirements.__dict__},
        )
        return True

    def release_stream_resources(self, stream_id: str) -> bool:
        """Release resources for a completed stream."""
        with self._lock:
            if stream_id not in self._stream_usage:
                return False

            requirements = self._stream_usage[stream_id]

            # Update usage
            self._usage[ResourceType.CPU] = max(
                0, self._usage[ResourceType.CPU] - requirements.estimated_cpu_percent
            )
            self._usage[ResourceType.MEMORY] = max(
                0, self._usage[ResourceType.MEMORY] - requirements.estimated_memory_mb
            )
            self._usage[ResourceType.DISK] = max(
                0, self._usage[ResourceType.DISK] - requirements.estimated_disk_mb
            )
            self._usage[ResourceType.STREAM] = max(
                0, self._usage[ResourceType.STREAM] - 1.0
            )

            del self._stream_usage[stream_id]

        logger.info("Resources released for stream", extra={"stream_id": stream_id})
        return True

    def get_resource_status(self) -> dict[str, Any]:
        """Get current resource status."""
        with self._lock:
            status = {}
            for rt, limit in self.limits.items():
                current = self._usage.get(rt, 0.0)
                status[rt.value] = {
                    "current": current,
                    "max": limit.max_value,
                    "available": limit.max_value - current,
                    "usage_percent": (
                        (current / limit.max_value * 100) if limit.max_value > 0 else 0
                    ),
                    "warning_threshold": limit.warning_threshold,
                    "critical_threshold": limit.critical_threshold,
                }
            return status


# Temp file management
class TempFileManager:
    """Manages temporary files with automatic cleanup."""

    def __init__(self, base_dir: str | None = None, max_age_hours: int = 24) -> None:
        self.base_dir = (
            Path(base_dir) if base_dir else Path(tempfile.gettempdir()) / "zmusic"
        )
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.max_age = max_age_hours * 3600  # seconds
        self._tracked_files: dict[str, float] = {}
        self._lock = threading.Lock()

    def create_temp_file(self, prefix: str = "zmusic_", suffix: str = ".tmp") -> str:
        """Create a tracked temporary file."""
        fd, path = tempfile.mkstemp(prefix=prefix, suffix=suffix, dir=self.base_dir)
        os.close(fd)
        with self._lock:
            self._tracked_files[path] = time.time()
        return path

    def create_temp_dir(self, prefix: str = "zmusic_") -> str:
        """Create a tracked temporary directory."""
        path = tempfile.mkdtemp(prefix=prefix, dir=self.base_dir)
        with self._lock:
            self._tracked_files[path] = time.time()
        return path

    def track_file(self, path: str) -> None:
        """Track an existing file for cleanup."""
        with self._lock:
            self._tracked_files[path] = time.time()

    def untrack_file(self, path: str) -> bool:
        """Stop tracking a file."""
        with self._lock:
            if path in self._tracked_files:
                del self._tracked_files[path]
                return True
            return False

    def cleanup_old_files(self) -> int:
        """Remove tracked files older than max_age."""
        now = time.time()
        cleaned = 0
        with self._lock:
            for path, created in list(self._tracked_files.items()):
                if now - created > self.max_age:
                    try:
                        p = Path(path)
                        if p.is_file():
                            p.unlink()
                        elif p.is_dir():
                            shutil.rmtree(p)
                        cleaned += 1
                        del self._tracked_files[path]
                    except Exception:
                        logger.warning("Failed to clean up file", exc_info=True)
        return cleaned

    def get_tracked_count(self) -> int:
        """Get count of tracked files."""
        with self._lock:
            return len(self._tracked_files)


# Process supervision
class ProcessSupervisor:
    """Supervises child processes with health checks and restart logic."""

    def __init__(self, max_restarts: int = 3, restart_delay: float = 5.0) -> None:
        self.max_restarts = max_restarts
        self.restart_delay = restart_delay
        self._processes: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def register_process(
        self, name: str, pid: int, restart_callback: Callable | None = None
    ) -> None:
        """Register a process for supervision."""
        with self._lock:
            self._processes[name] = {
                "pid": pid,
                "restarts": 0,
                "started_at": time.time(),
                "last_check": time.time(),
                "restart_callback": restart_callback,
                "healthy": True,
            }

    def unregister_process(self, name: str) -> bool:
        """Unregister a process."""
        with self._lock:
            if name in self._processes:
                del self._processes[name]
                return True
            return False

    def check_process(self, name: str) -> bool:
        """Check if a process is still running."""
        import psutil

        with self._lock:
            if name not in self._processes:
                return False

            proc_info = self._processes[name]
            try:
                proc = psutil.Process(proc_info["pid"])
                if proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE:
                    proc_info["last_check"] = time.time()
                    proc_info["healthy"] = True
                    return True
            except psutil.NoSuchProcess:
                pass

            proc_info["healthy"] = False
            return False

    def restart_process(self, name: str) -> bool:
        """Attempt to restart a failed process."""
        with self._lock:
            if name not in self._processes:
                return False

            proc_info = self._processes[name]
            if proc_info["restarts"] >= self.max_restarts:
                logger.error("Max restarts exceeded", extra={"proc_name": name})
                return False

            if proc_info["restart_callback"]:
                try:
                    new_pid = proc_info["restart_callback"]()
                    proc_info["pid"] = new_pid
                    proc_info["restarts"] += 1
                    proc_info["started_at"] = time.time()
                    proc_info["healthy"] = True
                    logger.info(
                        "Process restarted",
                        extra={"proc_name": name, "restarts": proc_info["restarts"]},
                    )
                    return True
                except Exception as e:  # noqa: BLE001
                    logger.error(
                        "Restart failed", extra={"proc_name": name, "error": str(e)}
                    )
                    return False
            return False


# Global instances
_resource_manager: ResourceManager | None = None
_temp_file_manager: TempFileManager | None = None
_process_supervisor: ProcessSupervisor | None = None


def get_resource_manager(config: AppConfig | None = None) -> ResourceManager:
    """Get the global resource manager (singleton)."""
    global _resource_manager
    if _resource_manager is None:
        _resource_manager = ResourceManager(config)
    return _resource_manager


def get_temp_file_manager(base_dir: str | None = None) -> TempFileManager:
    """Get the global temp file manager (singleton)."""
    global _temp_file_manager
    if _temp_file_manager is None:
        _temp_file_manager = TempFileManager(base_dir)
    return _temp_file_manager


def get_process_supervisor() -> ProcessSupervisor:
    """Get the global process supervisor (singleton)."""
    global _process_supervisor
    if _process_supervisor is None:
        _process_supervisor = ProcessSupervisor()
    return _process_supervisor


# --- Pre-flight Check Function ---


def preflight_check(
    stream_id: str, requirements: StreamResourceRequirements
) -> tuple[bool, dict[str, Any]]:
    """Run complete pre-flight checks before starting a stream."""
    manager = get_resource_manager()

    # 1. Check resources
    resource_results = manager.check_resources(requirements)
    can_start = all(r.status != ResourceStatus.EXHAUSTED for r in resource_results)

    # 2. Check assets exist (placeholder)
    assets_ok = True  # Would check database for required assets

    # 3. Check rights (placeholder)
    rights_ok = True  # Would check rights database

    # 4. Check network (placeholder)
    network_ok = True  # Would test RTMP endpoint connectivity

    # 5. Check YouTube (placeholder)
    youtube_ok = True  # Would check YouTube API

    all_ok = can_start and assets_ok and rights_ok and network_ok and youtube_ok

    return all_ok, {
        "resources": [r.__dict__ for r in resource_results],
        "assets_ok": assets_ok,
        "rights_ok": rights_ok,
        "network_ok": network_ok,
        "youtube_ok": youtube_ok,
        "can_start": all_ok,
    }


# --- Example Usage ---
#
# manager = get_resource_manager()
# manager.start_monitoring()
#
# requirements = StreamResourceRequirements(
#     stream_id="stream-001",
#     estimated_cpu_percent=25.0,
#     estimated_memory_mb=1024.0,
#     estimated_disk_mb=2048.0,
# )
#
# # Pre-flight check
# ok, details = preflight_check("stream-001", requirements)
# if ok:
#     manager.reserve_stream_resources("stream-001", requirements)
#     # Start stream...
#     # On completion:
#     manager.release_stream_resources("stream-001")
