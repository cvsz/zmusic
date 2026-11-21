"""Database tests for zMusic."""

import os
import tempfile
import unittest

from scripts.config import DatabaseConfig
from scripts.database import _local, get_connection, init_db, transaction


class DatabaseTest(unittest.TestCase):
    def setUp(self):
        # Reset thread-local connection so each test gets a fresh one
        if hasattr(_local, "conn") and _local.conn is not None:
            try:
                _local.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                _local.conn.close()
            except Exception:
                pass
            _local.conn = None
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test.db")
        self.config = DatabaseConfig(url=f"sqlite:///{self.db_path}")

    def tearDown(self):
        if hasattr(_local, "conn") and _local.conn is not None:
            try:
                _local.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                _local.conn.close()
            except Exception:
                pass
            _local.conn = None
        self.temp_dir.cleanup()

    def test_init_db_creates_tables(self):
        init_db(self.config)
        conn = get_connection()
        try:
            # Check all expected tables exist
            expected_tables = [
                "users",
                "organizations",
                "channels",
                "channel_settings",
                "agents",
                "agent_runs",
                "content",
                "playlists",
                "playlist_items",
                "tracks",
                "track_metadata",
                "track_rights",
                "visual_assets",
                "audio_assets",
                "overlay_assets",
                "scenes",
                "compositions",
                "streams",
                "stream_sessions",
                "stream_events",
                "stream_health",
                "schedules",
                "schedule_items",
                "youtube_accounts",
                "analytics",
                "analytics_snapshots",
                "jobs",
                "job_attempts",
                "audit_logs",
                "system_events",
            ]
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
            table_names = {row["name"] for row in rows}
            for table in expected_tables:
                self.assertIn(table, table_names, f"Table {table} missing")
        finally:
            conn.close()

    def test_init_db_idempotent(self):
        init_db(self.config)
        init_db(self.config)  # Should not raise

    def test_foreign_keys_enforced(self):
        init_db(self.config)
        conn = get_connection()
        try:
            # Insert an organization
            conn.execute(
                "INSERT INTO organizations (id, name, slug) VALUES (?, ?, ?)",
                ("org-1", "Test Org", "test-org"),
            )
            conn.commit()

            # Insert a channel referencing the org
            conn.execute(
                "INSERT INTO channels (id, organization_id, name) VALUES (?, ?, ?)",
                ("ch-1", "org-1", "Test Channel"),
            )
            conn.commit()

            # Try to insert a channel referencing a non-existent org
            with self.assertRaises(Exception):
                conn.execute(
                    "INSERT INTO channels (id, organization_id, name) VALUES (?, ?, ?)",
                    ("ch-2", "non-existent-org", "Bad Channel"),
                )
                conn.commit()
        finally:
            conn.close()

    def test_uuid_primary_keys(self):
        init_db(self.config)
        conn = get_connection()
        try:
            conn.execute(
                "INSERT INTO organizations (id, name, slug) VALUES (?, ?, ?)",
                ("org-1", "Test Org", "test-org"),
            )
            conn.commit()

            row = conn.execute(
                "SELECT id FROM organizations WHERE id = ?", ("org-1",)
            ).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["id"], "org-1")
        finally:
            conn.close()

    def test_timestamps_auto_populated(self):
        init_db(self.config)
        conn = get_connection()
        try:
            conn.execute(
                "INSERT INTO organizations (id, name, slug) VALUES (?, ?, ?)",
                ("org-1", "Test Org", "test-org"),
            )
            conn.commit()

            row = conn.execute(
                "SELECT created_at, updated_at FROM organizations WHERE id = ?",
                ("org-1",),
            ).fetchone()
            self.assertIsNotNone(row["created_at"])
            self.assertIsNotNone(row["updated_at"])
        finally:
            conn.close()

    def test_soft_deletion_columns(self):
        init_db(self.config)
        conn = get_connection()
        try:
            # Check that tables with soft deletion have deleted_at column
            tables_with_soft_delete = [
                "users",
                "organizations",
                "channels",
                "channel_settings",
                "agents",
                "agent_runs",
                "content",
                "playlists",
                "playlist_items",
                "tracks",
                "track_metadata",
                "track_rights",
                "visual_assets",
                "audio_assets",
                "overlay_assets",
                "scenes",
                "compositions",
                "streams",
                "stream_sessions",
                "stream_events",
                "stream_health",
                "schedules",
                "schedule_items",
                "youtube_accounts",
                "analytics",
                "analytics_snapshots",
                "jobs",
                "job_attempts",
                "audit_logs",
                "system_events",
            ]
            for table in tables_with_soft_delete:
                pragma = conn.execute(f"PRAGMA table_info({table})").fetchall()
                column_names = {row["name"] for row in pragma}
                self.assertIn(
                    "deleted_at", column_names, f"Table {table} missing deleted_at"
                )
        finally:
            conn.close()

    def test_transaction_rollback_on_error(self):
        init_db(self.config)
        conn = get_connection()
        try:
            conn.execute(
                "INSERT INTO organizations (id, name, slug) VALUES (?, ?, ?)",
                ("org-1", "Test Org", "test-org"),
            )
            conn.commit()

            # Try a transaction that fails
            with self.assertRaises(Exception), transaction() as t:
                t.execute(
                    "INSERT INTO organizations (id, name, slug) VALUES (?, ?, ?)",
                    ("org-2", "Test Org 2", "test-org-2"),
                )
                # Force an error by referencing non-existent table
                t.execute("SELECT * FROM non_existent_table")

            # org-2 should not exist because transaction was rolled back
            row = conn.execute(
                "SELECT id FROM organizations WHERE id = ?", ("org-2",)
            ).fetchone()
            self.assertIsNone(row)
        finally:
            conn.close()

    def test_wal_mode(self):
        init_db(self.config)
        conn = get_connection()
        try:
            journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            self.assertEqual(journal_mode.lower(), "wal")
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
