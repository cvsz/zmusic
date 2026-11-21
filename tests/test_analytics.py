"""Analytics tests for zMusic."""

import os
import tempfile
import unittest

from scripts.analytics import (
    AnalyticsCollector,
    StreamMetrics,
    get_analytics,
)
from scripts.config import DatabaseConfig
from scripts.database import get_connection, init_db


class StreamMetricsTest(unittest.TestCase):
    def test_stream_metrics_creation(self):
        metrics = StreamMetrics(
            stream_id="stream-1",
            channel_id="ch-1",
            started_at="2026-01-01T06:00:00Z",
            duration_seconds=3600.0,
            peak_viewers=150,
            total_viewer_hours=150.0,
        )
        self.assertEqual(metrics.stream_id, "stream-1")
        self.assertEqual(metrics.peak_viewers, 150)
        self.assertEqual(metrics.total_viewer_hours, 150.0)


class AnalyticsCollectorTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test.db")
        config = DatabaseConfig(url=f"sqlite:///{self.db_path}")
        init_db(config)

        # Store connection for use in test methods; do NOT close it here
        # as init_db() stores it in thread-local _local.conn.
        # Closing it here would break subsequent get_connection() calls.
        self.conn = get_connection()
        try:
            self.conn.execute(
                "INSERT INTO organizations (id, name, slug) VALUES (?, ?, ?)",
                ("org-1", "Test Org", "test-org"),
            )
            self.conn.execute(
                "INSERT INTO channels (id, organization_id, name) VALUES (?, ?, ?)",
                ("ch-1", "org-1", "Test Channel"),
            )
            self.conn.execute(
                "INSERT INTO streams (id, channel_id, state) VALUES (?, ?, ?)",
                ("stream-1", "ch-1", "live"),
            )
            self.conn.commit()
        except Exception:
            self.conn.close()
            raise

    def tearDown(self):
        # Close the thread-local connection and reset it so the next test
        # starts fresh. Do NOT reset _config — setUp will reinitialize it.
        try:
            conn = get_connection()
            conn.close()
        except Exception:  # noqa: S110, BLE001
            pass
        import scripts.database as dbmod

        dbmod._local.conn = None
        self.temp_dir.cleanup()

    def test_record_stream_session(self):
        collector = AnalyticsCollector()
        session_id = collector.record_stream_session(
            stream_id="stream-1",
            channel_id="ch-1",
            started_at="2026-01-01T06:00:00Z",
        )
        self.assertIsNotNone(session_id)

    def test_end_stream_session(self):
        collector = AnalyticsCollector()
        session_id = collector.record_stream_session(
            stream_id="stream-1",
            channel_id="ch-1",
            started_at="2026-01-01T06:00:00Z",
        )
        collector.end_stream_session(
            session_id=session_id,
            ended_at="2026-01-01T09:00:00Z",
        )

    def test_record_viewer_count(self):
        collector = AnalyticsCollector()
        session_id = collector.record_stream_session(
            stream_id="stream-1",
            channel_id="ch-1",
            started_at="2026-01-01T06:00:00Z",
        )
        collector.record_viewer_count(session_id=session_id, viewer_count=100)

    def test_compute_stream_metrics(self):
        collector = AnalyticsCollector()
        session_id = collector.record_stream_session(
            stream_id="stream-1",
            channel_id="ch-1",
            started_at="2026-01-01T06:00:00Z",
        )
        collector.end_stream_session(
            session_id=session_id,
            ended_at="2026-01-01T09:00:00Z",
        )
        collector.record_viewer_count(session_id=session_id, viewer_count=150)

        metrics = collector.compute_stream_metrics(stream_id="stream-1")
        self.assertEqual(metrics.stream_id, "stream-1")
        self.assertEqual(metrics.channel_id, "ch-1")
        self.assertEqual(metrics.peak_viewers, 150)
        self.assertAlmostEqual(metrics.duration_seconds, 10800.0, delta=1.0)

    def test_record_analytics_snapshot(self):
        collector = AnalyticsCollector()
        snapshot_id = collector.record_analytics_snapshot(
            channel_id="ch-1",
            date="2026-01-01",
            snapshot_data={
                "total_streams": 5,
                "total_viewer_hours": 25.5,
                "peak_concurrent_viewers": 200,
            },
        )
        self.assertIsNotNone(snapshot_id)

    def test_get_channel_analytics(self):
        collector = AnalyticsCollector()
        collector.record_analytics_snapshot(
            channel_id="ch-1",
            date="2026-01-01",
            snapshot_data={
                "total_streams": 3,
                "total_viewer_hours": 10.0,
                "peak_concurrent_viewers": 100,
            },
        )
        records = collector.get_channel_analytics(channel_id="ch-1")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["channel_id"], "ch-1")
        self.assertEqual(records[0]["total_streams"], 3)

    def test_generate_post_stream_report(self):
        collector = AnalyticsCollector()
        session_id = collector.record_stream_session(
            stream_id="stream-1",
            channel_id="ch-1",
            started_at="2026-01-01T06:00:00Z",
        )
        collector.end_stream_session(
            session_id=session_id,
            ended_at="2026-01-01T09:00:00Z",
        )
        collector.record_stream_event(
            stream_id="stream-1",
            event_type="stream.degraded",
            event_data={"reason": "network_interruption"},
        )

        report = collector.generate_post_stream_report(stream_id="stream-1")
        self.assertEqual(report["stream_id"], "stream-1")
        self.assertIn("metrics", report)
        self.assertIn("events", report)
        self.assertEqual(report["metrics"]["peak_viewers"], 0)
        # Report includes all stream events (started, stopped, degraded)
        self.assertEqual(len(report["events"]), 3)
        event_types = [e["event_type"] for e in report["events"]]
        self.assertIn("stream.degraded", event_types)


class GlobalAnalyticsTest(unittest.TestCase):
    def test_get_analytics_singleton(self):
        a1 = get_analytics()
        a2 = get_analytics()
        self.assertIs(a1, a2)
        self.assertIsInstance(a1, AnalyticsCollector)


if __name__ == "__main__":
    unittest.main()
