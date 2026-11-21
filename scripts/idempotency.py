"""Idempotency System for zMusic.

Ensures every externally triggered operation is safe to retry.
Uses idempotency keys and distributed locks to prevent duplicate execution.

Key concepts:
- Idempotency keys: Unique identifiers for operations
- Distributed locks: Prevent concurrent execution of same operation
- Result caching: Store and return previous results for duplicate requests
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, TypeVar, cast

from .config import AppConfig
from .database import get_connection, transaction
from .logging import get_logger

logger = get_logger("zmusic.idempotency")

T = TypeVar("T")


@dataclass
class IdempotencyRecord:
    """Record of an idempotent operation."""

    key: str
    operation: str
    input_hash: str
    status: str  # pending, completed, failed
    result: str | None = None  # JSON serialized result
    error: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(tz=UTC).isoformat())
    completed_at: str | None = None
    expires_at: str | None = None


class IdempotencyManager:
    """Manages idempotency keys and operation deduplication."""

    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config or AppConfig()
        self._locks: dict[str, threading.Lock] = {}
        self._locks_lock = threading.Lock()

    def _get_lock(self, key: str) -> threading.Lock:
        """Get or create a lock for a key."""
        with self._locks_lock:
            if key not in self._locks:
                self._locks[key] = threading.Lock()
            return self._locks[key]

    @contextmanager
    def lock(self, key: str, timeout: float = 30.0):
        """Acquire a distributed lock for a key."""
        lock = self._get_lock(key)
        acquired = lock.acquire(timeout=timeout)
        if not acquired:
            raise TimeoutError(f"Could not acquire lock for key: {key}")
        try:
            yield
        finally:
            lock.release()

    def generate_key(self, operation: str, input_data: dict[str, Any]) -> str:
        """Generate an idempotency key from operation and input."""
        import hashlib

        input_json = json.dumps(input_data, sort_keys=True)
        input_hash = hashlib.sha256(input_json.encode()).hexdigest()[:16]
        return f"{operation}:{input_hash}"

    def check_idempotency(self, key: str) -> IdempotencyRecord | None:
        """Check if an operation with this key has already been executed."""
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM idempotency_keys WHERE key = ? AND deleted_at IS NULL",
                (key,),
            ).fetchone()
            if not row:
                return None
            return IdempotencyRecord(
                key=row["key"],
                operation=row["operation"],
                input_hash=row["input_hash"],
                status=row["status"],
                result=row["result"],
                error=row["error"],
                created_at=row["created_at"],
                completed_at=row["completed_at"],
                expires_at=row["expires_at"],
            )
        finally:
            # Do NOT close connection
            pass

    def start_operation(
        self, key: str, operation: str, input_hash: str, ttl_seconds: int = 3600
    ) -> bool:
        """Mark an operation as started. Returns False if already exists."""
        now = datetime.now(tz=UTC).isoformat()
        expires_at = (datetime.now(tz=UTC) + timedelta(seconds=ttl_seconds)).isoformat()

        with transaction() as conn:
            # Try to insert - will fail if key already exists (IntegrityError)
            try:
                conn.execute(
                    """INSERT INTO idempotency_keys
                       (key, operation, input_hash, status, created_at, expires_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (key, operation, input_hash, "started", now, expires_at),
                )
                return True
            except sqlite3.IntegrityError:
                # Key already exists
                return False

    def complete_operation(self, key: str, result: Any) -> bool:
        """Mark an operation as completed with result."""
        now = datetime.now(tz=UTC).isoformat()
        result_json = json.dumps(result) if result is not None else None

        with transaction() as conn:
            cursor = conn.execute(
                """UPDATE idempotency_keys
                   SET status = ?, result = ?, completed_at = ?
                   WHERE key = ? AND status = ?""",
                (
                    "completed",
                    result_json,
                    datetime.now(tz=UTC).isoformat(),
                    key,
                    "started",
                ),
            )
            return cursor.rowcount > 0

    def fail_operation(self, key: str, error: str) -> bool:
        """Mark an operation as failed."""
        with transaction() as conn:
            cursor = conn.execute(
                """UPDATE idempotency_keys
                   SET status = ?, error = ?, completed_at = ?
                   WHERE key = ? AND status = ?""",
                ("failed", error, datetime.now(tz=UTC).isoformat(), key, "started"),
            )
            return cursor.rowcount > 0

    def get_result(self, key: str) -> Any | None:
        """Get the cached result for a completed operation."""
        record = self.check_idempotency(key)
        if not record or record.status != "completed":
            return None
        if record.result:
            return json.loads(record.result)
        return None


def idempotent(operation: str, ttl_seconds: int = 3600):
    """Decorator to make a function idempotent."""

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        def wrapper(*args, **kwargs) -> T:
            manager = get_idempotency_manager()

            # Generate key from function name and arguments
            input_data = {"args": args, "kwargs": kwargs}
            key = manager.generate_key(operation, {"func": func.__name__, **input_data})

            # Check if already executed
            existing = manager.check_idempotency(key)
            if existing:
                if existing.status == "completed":
                    logger.info("Returning cached result", extra={"key": key})
                    return cast(T, existing.result if existing.result else None)
                elif existing.status == "failed":
                    raise Exception(f"Previous execution failed: {existing.error}")
                elif existing.status == "started":
                    raise Exception(f"Operation already in progress: {key}")

            # Start operation
            input_hash = str(hash(str(args) + str(kwargs)))
            if not manager.start_operation(key, func.__name__, input_hash):
                # Another process started it
                existing = manager.check_idempotency(key)
                if existing and existing.status == "completed":
                    return cast(T, existing.result if existing.result else None)
                raise Exception(f"Operation already in progress: {key}")

            try:
                with manager.lock(key):
                    result = func(*args, **kwargs)
                    manager.complete_operation(key, result)
                    return result
            except Exception as e:
                manager.fail_operation(key, str(e))
                raise

        return wrapper

    return decorator


# Global instance
_idempotency_manager: IdempotencyManager | None = None


def get_idempotency_manager(config: AppConfig | None = None) -> IdempotencyManager:
    """Get the global idempotency manager (singleton)."""
    global _idempotency_manager
    if _idempotency_manager is None:
        _idempotency_manager = IdempotencyManager(config)
    return _idempotency_manager


# --- Database Schema Addition ---

IDEMPOTENCY_KEYS_SCHEMA = """
CREATE TABLE IF NOT EXISTS idempotency_keys (
    key TEXT PRIMARY KEY,
    operation TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending, started, completed, failed
    result TEXT,
    error TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at TEXT,
    expires_at TEXT,
    deleted_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_idempotency_status ON idempotency_keys(status);
CREATE INDEX IF NOT EXISTS idx_idempotency_expires ON idempotency_keys(expires_at);
"""


# --- Example Usage ---
#
# @idempotent("start_stream", ttl_seconds=7200)
# def start_stream(stream_id: str, config: dict) -> dict:
#     # This will only execute once per unique (stream_id, config) combination
#     return {"stream_id": stream_id, "status": "started"}
#
# # Manual usage:
# manager = get_idempotency_manager()
# key = manager.generate_key("create_playlist", {"name": "My Playlist", "tracks": [1,2,3]})
#
# if manager.check_idempotency(key):
#     print("Already done:", manager.get_result(key))
# else:
#     with manager.lock(key):
#         result = create_playlist("My Playlist", [1,2,3])
#         manager.complete_operation(key, result)
