"""Monitoring tests for zMusic."""

import os
import tempfile
import unittest

from scripts.config import DatabaseConfig
from scripts.database import get_connection, init_db
from scripts.monitoring import (
    MetricsCollector,
    StreamHealth,
    StreamHealthMonitor,
    _monitor,
    get_metrics,
    get_monitor,
)


class StreamHealthTest(unittest.TestCase):
    def test_health_creation(self):
        health = StreamHealth(
            stream_id="stream-1",
            rtmp_status="healthy",
            video_fps=30,
            bitrate_kbps=4500,
            dropped_frames=0.02,
            audio_status="healthy",
            encoder_status="healthy",
            disk_usage_percent=50.0,
            cpu_usage_percent=30.0,
            memory_usage_percent=40.0,
            recorded_at="2026-01-01T00:00:00Z",
        )
        self.assertEqual(health.stream_id, "stream-1")
        self.assertEqual(health.rtmp_status, "healthy")
        self.assertEqual(health.video_fps, 30)
        self.assertEqual(health.bitrate_kbps, 4500)


class MetricsCollectorTest(unittest.TestCase):
    def setUp(self):
        self.collector = MetricsCollector()

    def test_record_and_get(self):
        self.collector.record("test_metric", 42, {"tag": "value"})
        metrics = self.collector.get_metrics("test_metric")
        self.assertEqual(len(metrics), 1)
        self.assertEqual(metrics[0]["name"], "test_metric")
        self.assertEqual(metrics[0]["value"], 42)
        self.assertEqual(metrics[0]["tags"], {"tag": "value"})
        self.assertIn("timestamp", metrics[0])

    def test_get_metrics_nonexistent(self):
        metrics = self.collector.get_metrics("nonexistent")
        self.assertEqual(metrics, [])

    def test_get_all_metrics(self):
        self.collector.record("m1", 1)
        self.collector.record("m2", 2)
        all_metrics = self.collector.get_all_metrics()
        self.assertIn("m1", all_metrics)
        self.assertIn("m2", all_metrics)
        self.assertEqual(len(all_metrics["m1"]), 1)
        self.assertEqual(len(all_metrics["m2"]), 1)

    def test_record_stream_metrics(self):
        self.collector.record_stream_metrics(
            stream_id="stream-1",
            active=True,
            duration_seconds=3600.0,
            bitrate_kbps=4500,
            fps=30,
            dropped_frames=0.02,
            reconnects=0,
        )
        m = self.collector.get_metrics("stream_active")[0]
        self.assertEqual(m["value"], 1)
        self.assertEqual(m["tags"]["stream_id"], "stream-1")

    def test_record_agent_metrics(self):
        self.collector.record_agent_metrics(
            agent_name="music_director",
            jobs_run=5,
            failures=0,
            latency_seconds=1.5,
        )
        m = self.collector.get_metrics("agent_jobs")[0]
        self.assertEqual(m["value"], 5)
        self.assertEqual(m["tags"]["agent"], "music_director")

    def test_record_queue_metrics(self):
        self.collector.record_queue_metrics(
            queue_name="content-generation",
            depth=3,
            worker_health="healthy",
        )
        m = self.collector.get_metrics("queue_depth")[0]
        self.assertEqual(m["value"], 3)
        self.assertEqual(m["tags"]["queue"], "content-generation")

    def test_record_resource_metrics(self):
        self.collector.record_resource_metrics(45.0, 60.0, 70.0)
        self.assertEqual(self.collector.get_metrics("cpu_usage")[0]["value"], 45.0)
        self.assertEqual(self.collector.get_metrics("memory_usage")[0]["value"], 60.0)
        self.assertEqual(self.collector.get_metrics("disk_usage")[0]["value"], 70.0)


def _create_stream(conn, stream_id="stream-1", channel_id="ch-1"):
    """Helper to insert org, channel, and stream for FK compliance."""
    conn.execute(
        "INSERT INTO organizations (id, name, slug) VALUES (?, ?, ?)",
        ("org-1", "Test Org", "test-org"),
    )
    conn.execute(
        "INSERT INTO channels (id, organization_id, name) VALUES (?, ?, ?)",
        (channel_id, "org-1", "Test Channel"),
    )
    conn.execute(
        "INSERT INTO streams (id, channel_id, state) VALUES (?, ?, ?)",
        (stream_id, channel_id, "created"),
    )
    conn.commit()


class StreamHealthMonitorTest(unittest.TestCase):
    def setUp(self):
        # Reset global singletons for test isolation
        global _monitor, _metrics
        if _monitor is not None:
            try:
                _monitor.stop_all()
            except Exception:
                pass
        _monitor = None
        _metrics = None

        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test.db")

        self.config = DatabaseConfig(url=f"sqlite:///{self.db_path}")
        init_db(self.config)

        # Insert stream record for FK compliance
        conn = get_connection()
        try:
            _create_stream(conn)
        finally:
            conn.close()

    def tearDown(self):
        global _monitor
        if _monitor is not None:
            try:
                _monitor.stop_all()
            except Exception:
                pass
        conn = get_connection()
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            conn.close()
        except Exception:
            pass
        # Retry cleanup on Windows file-lock races
        import time as _time

        for _attempt in range(3):
            try:
                self.temp_dir.cleanup()
                break
            except PermissionError:
                _time.sleep(0.2)

    def test_monitor_creation(self):
        monitor = StreamHealthMonitor()
        self.assertEqual(monitor.MAX_CONSECUTIVE_FAILURES, 3)
        self.assertEqual(monitor.POLL_INTERVAL_SECONDS, 5)

    def test_start_stop_monitoring(self):
        monitor = StreamHealthMonitor()
        monitor.start_monitoring("stream-1")
        self.assertTrue(monitor.is_monitoring("stream-1"))
        monitor.stop_monitoring("stream-1")
        self.assertFalse(monitor.is_monitoring("stream-1"))

    def test_start_monitoring_idempotent(self):
        monitor = StreamHealthMonitor()
        monitor.start_monitoring("stream-1")
        monitor.start_monitoring("stream-1")  # Should not raise
        self.assertTrue(monitor.is_monitoring("stream-1"))
        monitor.stop_monitoring("stream-1")

    def test_stop_nonexistent_monitor(self):
        monitor = StreamHealthMonitor()
        # Should not raise
        monitor.stop_monitoring("nonexistent")

    def test_get_health_before_monitoring(self):
        monitor = StreamHealthMonitor()
        health = monitor.get_health("stream-1")
        self.assertIsNone(health)

    def test_failure_callback_invoked(self):
        callback_calls = []

        def callback(stream_id, reason):
            callback_calls.append((stream_id, reason))

        monitor = StreamHealthMonitor()
        monitor.start_monitoring("stream-1", failure_callback=callback)

        # Simulate the callback being called directly
        monitor._monitors["stream-1"].failure_callback("stream-1", "health_degraded")

        self.assertEqual(len(callback_calls), 1)
        self.assertEqual(callback_calls[0], ("stream-1", "health_degraded"))

        monitor.stop_monitoring("stream-1")

    def test_stop_all(self):
        monitor = StreamHealthMonitor()
        monitor.start_monitoring("stream-1")
        monitor.start_monitoring("stream-2")
        self.assertTrue(monitor.is_monitoring("stream-1"))
        self.assertTrue(monitor.is_monitoring("stream-2"))
        monitor.stop_all()
        self.assertFalse(monitor.is_monitoring("stream-1"))
        self.assertFalse(monitor.is_monitoring("stream-2"))


class GlobalInstancesTest(unittest.TestCase):
    def setUp(self):
        global _monitor, _metrics
        if _monitor is not None:
            try:
                _monitor.stop_all()
            except Exception:
                pass
        _monitor = None
        _metrics = None

    def tearDown(self):
        global _monitor
        if _monitor is not None:
            try:
                _monitor.stop_all()
            except Exception:
                pass

    def test_get_monitor_singleton(self):
        m1 = get_monitor()
        m2 = get_monitor()
        self.assertIs(m1, m2)

    def test_get_metrics_singleton(self):
        m1 = get_metrics()
        m2 = get_metrics()
        self.assertIs(m1, m2)


if __name__ == "__main__":
    unittest.main()
