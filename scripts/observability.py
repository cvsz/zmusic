"""Observability module for zMusic.

Provides structured logging, metrics collection, distributed tracing support,
and health/readiness endpoints for production monitoring.

Implements:
- Structured JSON logs with correlation IDs
- Prometheus-compatible metrics
- Health checks (/health, /health/live, /health/ready)
- Metrics endpoint (/metrics)
- Correlation ID propagation
"""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import wraps
from typing import Any

from .database import get_connection
from .logging import get_logger

logger = get_logger("zmusic.observability")


# --- Correlation ID Management ---

_correlation_id: threading.local = threading.local()


def get_correlation_id() -> str:
    """Get the current correlation ID, generating one if needed."""
    if not hasattr(_correlation_id, "value") or _correlation_id.value is None:
        _correlation_id.value = str(uuid.uuid4())
    return _correlation_id.value


def set_correlation_id(correlation_id: str) -> None:
    """Set the correlation ID for the current context."""
    _correlation_id.value = correlation_id


def clear_correlation_id() -> None:
    """Clear the correlation ID."""
    if hasattr(_correlation_id, "value"):
        _correlation_id.value = None


@contextmanager
def correlation_context(correlation_id: str | None = None):
    """Context manager for correlation ID."""
    old_id = getattr(_correlation_id, "value", None)
    try:
        if correlation_id:
            _correlation_id.value = correlation_id
        elif not hasattr(_correlation_id, "value") or _correlation_id.value is None:
            _correlation_id.value = str(uuid.uuid4())
        yield _correlation_id.value
    finally:
        if old_id is not None:
            _correlation_id.value = old_id
        else:
            _correlation_id.value = None


# --- Structured Logging ---


class StructuredLogger:
    """Enhanced logger that includes correlation IDs and structured fields."""

    def __init__(self, name: str) -> None:
        self._logger = get_logger(name)

    def _log(self, level: str, message: str, **kwargs) -> None:
        """Log with correlation ID and structured fields."""
        extra = {
            "correlation_id": get_correlation_id(),
            "timestamp": datetime.now(tz=UTC).isoformat(),
            **kwargs,
        }
        getattr(self._logger, level.lower())(message, extra=extra)

    def debug(self, message: str, **kwargs) -> None:
        self._log("DEBUG", message, **kwargs)

    def info(self, message: str, **kwargs) -> None:
        self._log("INFO", message, **kwargs)

    def warning(self, message: str, **kwargs) -> None:
        self._log("WARNING", message, **kwargs)

    def error(self, message: str, **kwargs) -> None:
        self._log("ERROR", message, **kwargs)

    def critical(self, message: str, **kwargs) -> None:
        self._log("CRITICAL", message, **kwargs)


def get_structured_logger(name: str) -> StructuredLogger:
    """Get a structured logger instance."""
    return StructuredLogger(name)


# --- Metrics Collection ---


@dataclass
class MetricValue:
    """A single metric value with metadata."""

    name: str
    value: float
    labels: dict[str, str] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(tz=UTC).isoformat())
    metric_type: str = "gauge"  # gauge, counter, histogram


class MetricsCollector:
    """Thread-safe metrics collector with Prometheus-compatible output."""

    def __init__(self) -> None:
        self._metrics: dict[str, list[MetricValue]] = {}
        self._lock = threading.Lock()
        self._counters: dict[str, float] = {}
        self._gauges: dict[str, float] = {}
        self._histograms: dict[str, list[float]] = {}

    def increment(
        self, name: str, value: float = 1.0, labels: dict[str, str] | None = None
    ) -> None:
        """Increment a counter metric."""
        with self._lock:
            key = self._make_key(name, labels)
            self._counters[key] = self._counters.get(key, 0.0) + value
            self._record(name, self._counters[key], labels, "counter")

    def gauge(
        self, name: str, value: float, labels: dict[str, str] | None = None
    ) -> None:
        """Set a gauge metric."""
        with self._lock:
            key = self._make_key(name, labels)
            self._gauges[key] = value
            self._record(name, value, labels, "gauge")

    def histogram(
        self, name: str, value: float, labels: dict[str, str] | None = None
    ) -> None:
        """Record a histogram value."""
        with self._lock:
            key = self._make_key(name, labels)
            if key not in self._histograms:
                self._histograms[key] = []
            self._histograms[key].append(value)
            # Keep only last 1000 values
            if len(self._histograms[key]) > 1000:
                self._histograms[key] = self._histograms[key][-1000:]
            self._record(name, value, labels, "histogram")

    def _make_key(self, name: str, labels: dict[str, str] | None) -> str:
        """Create a unique key for a metric with labels."""
        if not labels:
            return name
        label_str = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
        return f"{name}{{{label_str}}}"

    def _record(
        self, name: str, value: float, labels: dict[str, str] | None, metric_type: str
    ) -> None:
        """Record a metric value."""
        metric = MetricValue(
            name=name,
            value=value,
            labels=labels or {},
            metric_type=metric_type,
        )
        self._metrics.setdefault(name, []).append(metric)

    def get_metric(self, name: str) -> list[MetricValue]:
        """Get all recorded values for a metric."""
        with self._lock:
            return list(self._metrics.get(name, []))

    def get_all_metrics(self) -> dict[str, list[MetricValue]]:
        """Get all recorded metrics."""
        with self._lock:
            return {k: list(v) for k, v in self._metrics.items()}

    def export_prometheus(self) -> str:
        """Export metrics in Prometheus text format."""
        lines = []
        with self._lock:
            # Export counters
            for key, value in self._counters.items():
                lines.append(f"# TYPE {key} counter")
                lines.append(f"{key} {value}")

            # Export gauges
            for key, value in self._gauges.items():
                lines.append(f"# TYPE {key} gauge")
                lines.append(f"{key} {value}")

            # Export histograms (summary)
            for key, values in self._histograms.items():
                if not values:
                    continue
                lines.append(f"# TYPE {key} histogram")
                count = len(values)
                sum_val = sum(values)
                avg = sum_val / count
                lines.append(f"{key}_count {count}")
                lines.append(f"{key}_sum {sum_val}")
                lines.append(f"{key}_avg {avg}")
        return "\n".join(lines) + "\n"


# Global metrics collector
_metrics_collector: MetricsCollector | None = None


def get_metrics_collector() -> MetricsCollector:
    """Get the global metrics collector (singleton)."""
    global _metrics_collector
    if _metrics_collector is None:
        _metrics_collector = MetricsCollector()
    return _metrics_collector


# --- Health Checks ---


@dataclass
class HealthCheckResult:
    """Result of a health check."""

    name: str
    status: str  # healthy, degraded, unhealthy
    message: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(tz=UTC).isoformat())


class HealthChecker:
    """Performs health checks for the system."""

    def __init__(self) -> None:
        self._checks: dict[str, Callable[[], HealthCheckResult]] = {}

    def register_check(
        self, name: str, check_func: Callable[[], HealthCheckResult]
    ) -> None:
        """Register a health check function."""
        self._checks[name] = check_func

    def run_check(self, name: str) -> HealthCheckResult:
        """Run a specific health check."""
        check_func = self._checks.get(name)
        if not check_func:
            return HealthCheckResult(
                name=name,
                status="unhealthy",
                message=f"Check '{name}' not found",
            )
        try:
            return check_func()
        except Exception as e:  # noqa: BLE001
            return HealthCheckResult(
                name=name,
                status="unhealthy",
                message=str(e),
            )

    def run_all_checks(self) -> dict[str, HealthCheckResult]:
        """Run all registered health checks."""
        return {name: self.run_check(name) for name in self._checks}

    def get_overall_status(self) -> str:
        """Get overall system health status."""
        results = self.run_all_checks()
        if not results:
            return "unknown"
        statuses = [r.status for r in results.values()]
        if all(s == "healthy" for s in statuses):
            return "healthy"
        if any(s == "unhealthy" for s in statuses):
            return "unhealthy"
        return "degraded"


# Default health checks
def _check_database() -> HealthCheckResult:
    """Check database connectivity."""
    try:
        conn = get_connection()
        conn.execute("SELECT 1")
        return HealthCheckResult(
            name="database", status="healthy", message="Database connected"
        )
    except Exception as e:  # noqa: BLE001
        return HealthCheckResult(name="database", status="unhealthy", message=str(e))


def _check_disk_space() -> HealthCheckResult:
    """Check available disk space."""
    import shutil

    try:
        total, _used, free = shutil.disk_usage("/")
        free_percent = (free / total) * 100
        if free_percent > 20:
            return HealthCheckResult(
                name="disk", status="healthy", message=f"{free_percent:.1f}% free"
            )
        elif free_percent > 10:
            return HealthCheckResult(
                name="disk", status="degraded", message=f"{free_percent:.1f}% free"
            )
        return HealthCheckResult(
            name="disk", status="unhealthy", message=f"{free_percent:.1f}% free"
        )
    except Exception as e:  # noqa: BLE001
        return HealthCheckResult(name="disk", status="unknown", message=str(e))


# Global health checker
_health_checker: HealthChecker | None = None


def get_health_checker() -> HealthChecker:
    """Get the global health checker (singleton)."""
    global _health_checker
    if _health_checker is None:
        _health_checker = HealthChecker()
        # Register default checks
        _health_checker.register_check("database", _check_database)
        _health_checker.register_check("disk", _check_disk_space)
    return _health_checker


# --- HTTP Health Endpoints (framework-agnostic) ---


def health_endpoint() -> dict[str, Any]:
    """Main health endpoint - returns overall status."""
    checker = get_health_checker()
    overall = checker.get_overall_status()
    checks = checker.run_all_checks()
    return {
        "status": overall,
        "timestamp": datetime.now(tz=UTC).isoformat(),
        "checks": {
            name: {
                "status": result.status,
                "message": result.message,
                "details": result.details,
            }
            for name, result in checks.items()
        },
    }


def health_live_endpoint() -> dict[str, Any]:
    """Liveness probe - returns 200 if process is alive."""
    return {
        "status": "alive",
        "timestamp": datetime.now(tz=UTC).isoformat(),
    }


def health_ready_endpoint() -> dict[str, Any]:
    """Readiness probe - returns 200 if ready to serve traffic."""
    checker = get_health_checker()
    overall = checker.get_overall_status()
    ready = overall in ("healthy", "degraded")
    return {
        "status": "ready" if ready else "not_ready",
        "timestamp": datetime.now(tz=UTC).isoformat(),
        "overall": overall,
    }


def metrics_endpoint() -> str:
    """Prometheus metrics endpoint."""
    collector = get_metrics_collector()
    return collector.export_prometheus()


# --- Decorators for Instrumentation ---


def instrument(name: str, labels: dict[str, str] | None = None):
    """Decorator to instrument a function with metrics."""

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            collector = get_metrics_collector()
            start = time.time()
            try:
                result = func(*args, **kwargs)
                collector.increment(f"{name}_success", labels=labels)
                collector.histogram(
                    f"{name}_duration", time.time() - start, labels=labels
                )
                return result
            except Exception:
                collector.increment(f"{name}_error", labels=labels)
                raise

        return wrapper

    return decorator


def trace(name: str):
    """Decorator to add tracing with correlation ID."""

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            correlation_id = str(uuid.uuid4())
            with correlation_context(correlation_id):
                slog = get_structured_logger(f"trace.{name}")
                slog.info(f"Starting {name}", correlation_id=correlation_id)
                start = time.time()
                try:
                    result = func(*args, **kwargs)
                    slog.info(f"Completed {name}", duration=time.time() - start)
                    return result
                except Exception as e:
                    slog.error(
                        f"Failed {name}", error=str(e), duration=time.time() - start
                    )
                    raise

        return wrapper

    return decorator


# --- Example Usage ---
#
# # In your application startup:
# checker = get_health_checker()
# checker.register_check("my_service", lambda: HealthCheckResult("my_service", "healthy"))
#
# # In HTTP handlers:
# @app.get("/health")
# def health():
#     return health_endpoint()
#
# @app.get("/health/live")
# def health_live():
#     return health_live_endpoint()
#
# @app.get("/health/ready")
# def health_ready():
#     return health_ready_endpoint()
#
# @app.get("/metrics")
# def metrics():
#     return Response(metrics_endpoint(), media_type="text/plain")
#
# # Instrument functions:
# @instrument("api_request", {"endpoint": "/api/v1/channels"})
# @trace("get_channels")
# def get_channels():
#     ...
