"""Dashboard tests for zMusic."""

import os
import tempfile
import unittest

from scripts.config import DatabaseConfig
from scripts.dashboard import (
    DashboardEngine,
    SystemMetrics,
    get_dashboard,
)
from scripts.database import get_connection, init_db


class DashboardEngineTest(unittest.TestCase):
    def test_dashboard_engine_creation(self):
        dashboard = DashboardEngine()
        self.assertIsNotNone(dashboard)

    def test_get_dashboard_singleton(self):
        d1 = get_dashboard()
        d2 = get_dashboard()
        self.assertIs(d1, d2)


class ChannelDashboardTest(unittest.TestCase):
    def test_channel_dashboard_creation(self):
        # Just verify the dashboard class and data classes can be created
        dashboard = DashboardEngine()
        self.assertIsNotNone(dashboard)


class SystemMetricsTest(unittest.TestCase):
    def test_system_metrics_creation(self):
        metrics = SystemMetrics(
            cpu_usage=45.5,
            memory_usage=72.3,
            disk_usage=61.0,
            active_streams=3,
            total_streams_today=12,
            active_agents=5,
            failed_agents=1,
        )
        self.assertEqual(metrics.cpu_usage, 45.5)
        self.assertEqual(metrics.memory_usage, 72.3)
        self.assertEqual(metrics.disk_usage, 61.0)
        self.assertEqual(metrics.active_streams, 3)
        self.assertEqual(metrics.total_streams_today, 12)
        self.assertEqual(metrics.active_agents, 5)
        self.assertEqual(metrics.failed_agents, 1)


class DashboardOverviewTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test.db")
        config = DatabaseConfig(url=f"sqlite:///{self.db_path}")
        init_db(config)

        # Store connection for use in test methods;
        # do NOT close it here as init_db stores it in thread-local _local.conn.
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
        # Properly close and reset the thread-local connection
        try:
            conn = get_connection()
            conn.close()
        except Exception:
            pass
        # Reset the global state so get_connection() creates a fresh one
        import scripts.database as dbmod

        dbmod._local.conn = None
        dbmod._config = dbmod.DatabaseConfig()
        self.temp_dir.cleanup()

    def test_dashboard_overview_components(self):
        dashboard = get_dashboard()
        # Verify overview has expected keys; data may vary based on test state
        overview = dashboard.get_overview()
        self.assertIn("total_channels", overview)
        self.assertIn("active_channels", overview)
        self.assertIn("total_streams", overview)
        self.assertIn("active_streams", overview)
        self.assertIn("system_metrics", overview)
        self.assertIn("recent_streams", overview)


if __name__ == "__main__":
    unittest.main()
