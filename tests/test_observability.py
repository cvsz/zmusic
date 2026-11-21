"""Observability tests for zMusic."""

import unittest

from scripts.observability import (
    HealthChecker,
    HealthCheckResult,
    MetricsCollector,
    clear_correlation_id,
    correlation_context,
    get_correlation_id,
    get_metrics_collector,
    get_structured_logger,
    health_endpoint,
    health_live_endpoint,
    health_ready_endpoint,
    instrument,
    metrics_endpoint,
    set_correlation_id,
    trace,
)


class CorrelationIDTest(unittest.TestCase):
    def test_correlation_id_generation(self):
        clear_correlation_id()
        cid1 = get_correlation_id()
        cid2 = get_correlation_id()
        self.assertEqual(cid1, cid2)  # Same within context

    def test_set_correlation_id(self):
        set_correlation_id("test-correlation-id")
        self.assertEqual(get_correlation_id(), "test-correlation-id")
        clear_correlation_id()

    def test_correlation_context_manager(self):
        clear_correlation_id()
        with correlation_context("ctx-123") as cid:
            self.assertEqual(cid, "ctx-123")
            self.assertEqual(get_correlation_id(), "ctx-123")
        # After context, should be new ID
        new_id = get_correlation_id()
        self.assertNotEqual(new_id, "ctx-123")


class MetricsCollectorTest(unittest.TestCase):
    def setUp(self):
        self.collector = MetricsCollector()

    def test_increment_counter(self):
        self.collector.increment("test_counter", 1.0, {"label": "value"})
        self.collector.increment("test_counter", 2.0, {"label": "value"})
        metrics = self.collector.get_metric("test_counter")
        self.assertEqual(len(metrics), 2)
        self.assertEqual(metrics[-1].value, 3.0)

    def test_gauge(self):
        self.collector.gauge("test_gauge", 42.0, {"host": "server1"})
        metrics = self.collector.get_metric("test_gauge")
        self.assertEqual(len(metrics), 1)
        self.assertEqual(metrics[-1].value, 42.0)

    def test_histogram(self):
        for i in range(5):
            self.collector.histogram("test_hist", float(i), {"type": "latency"})
        metrics = self.collector.get_metric("test_hist")
        self.assertEqual(len(metrics), 5)

    def test_prometheus_export(self):
        self.collector.increment("requests_total", 5, {"method": "GET"})
        self.collector.gauge("memory_usage", 75.5)
        self.collector.histogram("request_duration", 0.1)
        self.collector.histogram("request_duration", 0.2)

        output = self.collector.export_prometheus()
        self.assertIn("requests_total", output)
        self.assertIn("memory_usage", output)
        self.assertIn("request_duration", output)

    def test_get_all_metrics(self):
        self.collector.increment("a", 1)
        self.collector.gauge("b", 2)
        all_metrics = self.collector.get_all_metrics()
        self.assertIn("a", all_metrics)
        self.assertIn("b", all_metrics)


class MetricsCollectorSingletonTest(unittest.TestCase):
    def test_singleton(self):
        m1 = get_metrics_collector()
        m2 = get_metrics_collector()
        self.assertIs(m1, m2)


class HealthCheckTest(unittest.TestCase):
    def test_health_check_result(self):
        result = HealthCheckResult(
            name="test",
            status="healthy",
            message="All good",
            details={"key": "value"},
        )
        self.assertEqual(result.name, "test")
        self.assertEqual(result.status, "healthy")
        self.assertEqual(result.message, "All good")
        self.assertEqual(result.details, {"key": "value"})

    def test_health_checker_registration(self):
        checker = HealthChecker()

        def custom_check():
            return HealthCheckResult("custom", "healthy")

        checker.register_check("custom", custom_check)
        result = checker.run_check("custom")
        self.assertEqual(result.status, "healthy")

    def test_health_checker_missing_check(self):
        checker = HealthChecker()
        result = checker.run_check("nonexistent")
        self.assertEqual(result.status, "unhealthy")

    def test_health_checker_overall_status(self):
        checker = HealthChecker()
        checker.register_check("a", lambda: HealthCheckResult("a", "healthy"))
        checker.register_check("b", lambda: HealthCheckResult("b", "healthy"))
        self.assertEqual(checker.get_overall_status(), "healthy")

        checker2 = HealthChecker()
        checker2.register_check("a", lambda: HealthCheckResult("a", "healthy"))
        checker2.register_check("b", lambda: HealthCheckResult("b", "unhealthy"))
        self.assertEqual(checker2.get_overall_status(), "unhealthy")

        checker3 = HealthChecker()
        checker3.register_check("a", lambda: HealthCheckResult("a", "healthy"))
        checker3.register_check("b", lambda: HealthCheckResult("b", "degraded"))
        self.assertEqual(checker3.get_overall_status(), "degraded")


class HealthEndpointsTest(unittest.TestCase):
    def test_health_endpoint(self):
        result = health_endpoint()
        self.assertIn("status", result)
        self.assertIn("timestamp", result)
        self.assertIn("checks", result)
        self.assertIsInstance(result["checks"], dict)

    def test_health_live_endpoint(self):
        result = health_live_endpoint()
        self.assertEqual(result["status"], "alive")
        self.assertIn("timestamp", result)

    def test_health_ready_endpoint(self):
        result = health_ready_endpoint()
        self.assertIn("status", result)
        self.assertIn("overall", result)
        self.assertIn("timestamp", result)

    def test_metrics_endpoint(self):
        # Add some metrics first
        collector = get_metrics_collector()
        collector.increment("test_metric", 1)
        output = metrics_endpoint()
        self.assertIn("test_metric", output)


class StructuredLoggerTest(unittest.TestCase):
    def test_structured_logger(self):
        logger = get_structured_logger("test")
        # Just verify it can be created and called without error
        logger.info("test message", extra_field="value")
        logger.warning("warning message")
        logger.error("error message")


class InstrumentDecoratorTest(unittest.TestCase):
    def test_instrument_success(self):
        collector = get_metrics_collector()
        collector._counters.clear()
        collector._gauges.clear()
        collector._histograms.clear()
        collector._metrics.clear()

        @instrument("test_func", {"env": "test"})
        def success_func():
            return "success"

        result = success_func()
        self.assertEqual(result, "success")

        # Check metrics were recorded
        metrics = collector.get_all_metrics()
        self.assertIn("test_func_success", metrics)
        self.assertIn("test_func_duration", metrics)

    def test_instrument_error(self):
        collector = get_metrics_collector()
        collector._counters.clear()

        @instrument("error_func")
        def error_func():
            raise ValueError("test error")

        with self.assertRaises(ValueError):
            error_func()

        metrics = collector.get_all_metrics()
        self.assertIn("error_func_error", metrics)


class TraceDecoratorTest(unittest.TestCase):
    def test_trace_decorator(self):
        @trace("test_operation")
        def traced_func():
            return "traced"

        result = traced_func()
        self.assertEqual(result, "traced")


if __name__ == "__main__":
    unittest.main()
