"""Worker Architecture for zMusic.

Provides asynchronous worker system with queues, concurrency control,
retries with exponential backoff, and job tracking.

Suggested queues:
  - content-generation
  - music-processing
  - visual-processing
  - composition
  - stream-start
  - stream-stop
  - stream-monitor
  - analytics
  - optimization
  - recovery

Every job has:
  - job_id
  - type
  - priority
  - status
  - attempt
  - created_at
  - started_at
  - completed_at
  - error
  - payload
"""

from __future__ import annotations

import heapq
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from .logging import get_logger

logger = get_logger("zmusic.worker")


class JobStatus(Enum):
    """Job status states."""

    CREATED = "created"
    QUEUED = "queued"
    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRY_PENDING = "retry_pending"
    CANCELLED = "cancelled"


class JobPriority(Enum):
    """Job priority levels."""

    LOW = 0
    NORMAL = 50
    HIGH = 100
    CRITICAL = 200


@dataclass(frozen=True)
class Job:
    """Job definition with all metadata."""

    job_id: str
    job_type: str
    payload: dict[str, Any]
    priority: int = JobPriority.NORMAL.value
    status: JobStatus = JobStatus.CREATED
    attempt: int = 0
    max_attempts: int = 3
    created_at: str = field(default_factory=lambda: datetime.now(tz=UTC).isoformat())
    started_at: str | None = None
    completed_at: str | None = None
    error: str | None = None
    tags: dict[str, str] = field(default_factory=dict)

    def with_status(self, status: JobStatus) -> Job:
        """Return a new job with updated status."""
        return Job(
            job_id=self.job_id,
            job_type=self.job_type,
            payload=self.payload,
            priority=self.priority,
            status=status,
            attempt=self.attempt,
            max_attempts=self.max_attempts,
            created_at=self.created_at,
            started_at=self.started_at,
            completed_at=self.completed_at,
            error=self.error,
            tags=self.tags,
        )

    def with_attempt(
        self, attempt: int, started_at: str | None = None, error: str | None = None
    ) -> Job:
        """Return a new job with updated attempt."""
        return Job(
            job_id=self.job_id,
            job_type=self.job_type,
            payload=self.payload,
            priority=self.priority,
            status=self.status,
            attempt=attempt,
            max_attempts=self.max_attempts,
            created_at=self.created_at,
            started_at=started_at or self.started_at,
            completed_at=self.completed_at,
            error=error,
            tags=self.tags,
        )


@dataclass
class WorkerConfig:
    """Configuration for a worker pool."""

    queue_name: str
    max_workers: int = 4
    max_retries: int = 3
    base_retry_delay: float = 1.0  # seconds
    max_retry_delay: float = 60.0  # seconds
    retry_multiplier: float = 2.0
    shutdown_timeout: float = 30.0


# Predefined queue configurations
QUEUE_CONFIGS: dict[str, WorkerConfig] = {
    "content-generation": WorkerConfig("content-generation", max_workers=2),
    "music-processing": WorkerConfig("music-processing", max_workers=3),
    "visual-processing": WorkerConfig("visual-processing", max_workers=3),
    "composition": WorkerConfig("composition", max_workers=2),
    "stream-start": WorkerConfig("stream-start", max_workers=4),
    "stream-stop": WorkerConfig("stream-stop", max_workers=2),
    "stream-monitor": WorkerConfig("stream-monitor", max_workers=1),
    "analytics": WorkerConfig("analytics", max_workers=2),
    "optimization": WorkerConfig("optimization", max_workers=1),
    "recovery": WorkerConfig("recovery", max_workers=2),
}


class JobQueue:
    """Thread-safe job queue with priority support using heapq."""

    def __init__(self, name: str) -> None:
        self.name = name
        self._heap: list[tuple] = []
        self._lock = threading.Lock()
        self._pending: dict[str, Job] = {}  # job_id -> Job (for tracking)
        self._sequence = 0  # For tiebreaking priority

    def enqueue(self, job: Job) -> None:
        """Add a job to the queue."""
        with self._lock:
            self._pending[job.job_id] = job
            self._sequence += 1
            # Use negative priority for max-heap behavior (higher priority first)
            # Use sequence as tiebreaker to ensure FIFO for same priority
            heapq.heappush(self._heap, (-job.priority, self._sequence, job.job_id, job))

    def dequeue(self, timeout: float = 1.0) -> Job | None:
        """Get the next job from the queue."""
        end_time = time.time() + timeout
        while time.time() < end_time:
            with self._lock:
                if self._heap:
                    _, _, _, job = heapq.heappop(self._heap)
                    if job.job_id in self._pending:
                        self._pending[job.job_id] = job
                        return job
            time.sleep(0.01)
        return None

    def get_job(self, job_id: str) -> Job | None:
        """Get a job by ID."""
        with self._lock:
            return self._pending.get(job_id)

    def update_job(self, job: Job) -> None:
        """Update a job's status in tracking."""
        with self._lock:
            self._pending[job.job_id] = job

    def remove_job(self, job_id: str) -> bool:
        """Remove a job from tracking."""
        with self._lock:
            if job_id in self._pending:
                del self._pending[job_id]
                return True
            return False

    def size(self) -> int:
        """Return approximate queue size."""
        with self._lock:
            return len(self._heap)

    def list_pending(self) -> list[Job]:
        """List all pending jobs."""
        with self._lock:
            return list(self._pending.values())


class Worker:
    """Worker that processes jobs from a queue."""

    def __init__(
        self,
        queue: JobQueue,
        handler: Callable[[Job], Any],
        config: WorkerConfig,
        worker_id: str,
    ) -> None:
        self.queue = queue
        self.handler = handler
        self.config = config
        self.worker_id = worker_id
        self._running = False
        self._thread: threading.Thread | None = None
        self._shutdown_event = threading.Event()

    def start(self) -> None:
        """Start the worker thread."""
        if self._running:
            return
        self._running = True
        self._shutdown_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info(
            "Worker started",
            extra={"worker_id": self.worker_id, "queue": self.queue.name},
        )

    def stop(self, timeout: float | None = None) -> None:
        """Stop the worker thread."""
        if not self._running:
            return
        self._running = False
        self._shutdown_event.set()
        if self._thread:
            self._thread.join(timeout=timeout or self.config.shutdown_timeout)
        logger.info(
            "Worker stopped",
            extra={"worker_id": self.worker_id, "queue": self.queue.name},
        )

    def _run_loop(self) -> None:
        """Main worker loop."""
        while self._running and not self._shutdown_event.is_set():
            job = self.queue.dequeue(timeout=1.0)
            if job is None:
                continue

            self._process_job(job)

    def _process_job(self, job: Job) -> None:
        """Process a single job with retry logic."""
        attempt = job.attempt + 1
        max_attempts = job.max_attempts

        # Update job status to STARTED
        job = Job(
            job_id=job.job_id,
            job_type=job.job_type,
            payload=job.payload,
            priority=job.priority,
            status=JobStatus.STARTED,
            attempt=attempt,
            max_attempts=max_attempts,
            created_at=job.created_at,
            started_at=datetime.now(tz=UTC).isoformat(),
            tags=job.tags,
        )
        self.queue.update_job(job)

        logger.info(
            "Processing job",
            extra={
                "worker_id": self.worker_id,
                "job_id": job.job_id,
                "job_type": job.job_type,
                "attempt": attempt,
            },
        )

        try:
            # Execute the handler
            self.handler(job)

            # Mark as completed
            completed_job = Job(
                job_id=job.job_id,
                job_type=job.job_type,
                payload=job.payload,
                priority=job.priority,
                status=JobStatus.COMPLETED,
                attempt=attempt,
                max_attempts=max_attempts,
                created_at=job.created_at,
                started_at=job.started_at,
                completed_at=datetime.now(tz=UTC).isoformat(),
                tags=job.tags,
            )
            self.queue.update_job(completed_job)

            logger.info(
                "Job completed",
                extra={"worker_id": self.worker_id, "job_id": job.job_id},
            )

        except Exception as e:  # noqa: BLE001
            # Handle failure with retry logic
            error_msg = str(e)
            logger.error(
                "Job failed",
                extra={
                    "worker_id": self.worker_id,
                    "job_id": job.job_id,
                    "attempt": attempt,
                    "error": error_msg,
                },
            )

            if attempt >= max_attempts:
                # Max attempts reached - mark as failed
                failed_job = Job(
                    job_id=job.job_id,
                    job_type=job.job_type,
                    payload=job.payload,
                    priority=job.priority,
                    status=JobStatus.FAILED,
                    attempt=attempt,
                    max_attempts=max_attempts,
                    created_at=job.created_at,
                    started_at=job.started_at,
                    completed_at=datetime.now(tz=UTC).isoformat(),
                    error=error_msg,
                    tags=job.tags,
                )
                self.queue.update_job(failed_job)
            else:
                # Schedule retry with exponential backoff
                delay = min(
                    self.config.base_retry_delay
                    * (self.config.retry_multiplier ** (attempt - 1)),
                    self.config.max_retry_delay,
                )

                retry_job = Job(
                    job_id=job.job_id,
                    job_type=job.job_type,
                    payload=job.payload,
                    priority=job.priority,
                    status=JobStatus.RETRY_PENDING,
                    attempt=attempt,
                    max_attempts=max_attempts,
                    created_at=job.created_at,
                    started_at=job.started_at,
                    tags=job.tags,
                )
                self.queue.update_job(retry_job)

                # Re-queue after delay
                time.sleep(delay)
                self.queue.enqueue(retry_job)


class WorkerPool:
    """Manages a pool of workers for a queue."""

    def __init__(self, config: WorkerConfig, handler: Callable[[Job], Any]) -> None:
        self.config = config
        self.handler = handler
        self.queue = JobQueue(config.queue_name)
        self.workers: list[Worker] = []
        self._executor: ThreadPoolExecutor | None = None

    def start(self) -> None:
        """Start all workers in the pool."""
        self._executor = ThreadPoolExecutor(max_workers=self.config.max_workers)
        for i in range(self.config.max_workers):
            worker_id = f"{self.config.queue_name}-worker-{i}"
            worker = Worker(self.queue, self.handler, self.config, worker_id)
            worker.start()
            self.workers.append(worker)
        logger.info(
            "Worker pool started",
            extra={"queue": self.config.queue_name, "workers": len(self.workers)},
        )

    def stop(self, timeout: float | None = None) -> None:
        """Stop all workers in the pool."""
        for worker in self.workers:
            worker.stop(timeout)
        if self._executor:
            self._executor.shutdown(wait=True)
        logger.info("Worker pool stopped", extra={"queue": self.config.queue_name})

    def submit_job(
        self,
        job_type: str,
        payload: dict[str, Any],
        priority: int = JobPriority.NORMAL.value,
        max_attempts: int = 3,
        tags: dict[str, str] | None = None,
    ) -> str:
        """Submit a new job to the queue."""
        job = Job(
            job_id=str(uuid.uuid4()),
            job_type=job_type,
            payload=payload,
            priority=priority,
            max_attempts=max_attempts,
            tags=tags or {},
        )
        self.queue.enqueue(job)
        logger.info(
            "Job submitted",
            extra={
                "queue": self.config.queue_name,
                "job_id": job.job_id,
                "job_type": job_type,
            },
        )
        return job.job_id

    def get_job_status(self, job_id: str) -> Job | None:
        """Get job status by ID."""
        return self.queue.get_job(job_id)

    def get_queue_stats(self) -> dict[str, Any]:
        """Get queue statistics."""
        pending = self.queue.list_pending()
        status_counts: dict[str, int] = {}
        for job in pending:
            status_counts[job.status.value] = status_counts.get(job.status.value, 0) + 1
        return {
            "queue_name": self.config.queue_name,
            "pending_count": len(pending),
            "queue_size": self.queue.size(),
            "status_breakdown": status_counts,
            "workers": len(self.workers),
        }


# --- Job Registry ---


class JobRegistry:
    """Global registry for all worker pools."""

    def __init__(self) -> None:
        self._pools: dict[str, WorkerPool] = {}
        self._lock = threading.Lock()

    def register_pool(
        self, config: WorkerConfig, handler: Callable[[Job], Any]
    ) -> WorkerPool:
        """Register a new worker pool."""
        with self._lock:
            if config.queue_name in self._pools:
                raise ValueError(f"Pool for queue '{config.queue_name}' already exists")
            pool = WorkerPool(config, handler)
            self._pools[config.queue_name] = pool
            return pool

    def get_pool(self, queue_name: str) -> WorkerPool | None:
        """Get a worker pool by queue name."""
        with self._lock:
            return self._pools.get(queue_name)

    def start_all(self) -> None:
        """Start all registered pools."""
        with self._lock:
            for pool in self._pools.values():
                pool.start()

    def stop_all(self, timeout: float | None = None) -> None:
        """Stop all registered pools."""
        with self._lock:
            for pool in self._pools.values():
                pool.stop(timeout)

    def submit_job(
        self,
        queue_name: str,
        job_type: str,
        payload: dict[str, Any],
        priority: int = JobPriority.NORMAL.value,
        max_attempts: int = 3,
        tags: dict[str, str] | None = None,
    ) -> str | None:
        """Submit a job to a specific queue."""
        pool = self.get_pool(queue_name)
        if not pool:
            logger.error("Queue not found", extra={"queue_name": queue_name})
            return None
        return pool.submit_job(job_type, payload, priority, max_attempts, tags)

    def get_all_stats(self) -> dict[str, Any]:
        """Get statistics for all queues."""
        with self._lock:
            return {name: pool.get_queue_stats() for name, pool in self._pools.items()}


# Global registry
_job_registry: JobRegistry | None = None


def get_job_registry() -> JobRegistry:
    """Get the global job registry (singleton)."""
    global _job_registry
    if _job_registry is None:
        _job_registry = JobRegistry()
    return _job_registry


def create_default_pools() -> JobRegistry:
    """Create default worker pools with standard handlers."""
    registry = get_job_registry()

    # Register default handlers (placeholders - replace with actual handlers)
    def default_handler(job: Job) -> Any:
        logger.info("Default handler processing", extra={"job_type": job.job_type})
        return {"status": "processed"}

    for config in QUEUE_CONFIGS.values():
        registry.register_pool(config, default_handler)

    return registry


# --- Example Usage ---
#
# registry = create_default_pools()
# registry.start_all()
#
# # Submit a job
# job_id = registry.submit_job(
#     "content-generation",
#     "generate_playlist",
#     {"theme": "lofi", "duration_hours": 2},
#     priority=JobPriority.HIGH.value,
# )
#
# # Check status
# job = registry.get_pool("content-generation").get_job_status(job_id)
# print(job.status)
#
# registry.stop_all()
