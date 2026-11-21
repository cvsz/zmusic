"""Resource management tests for zMusic."""

import os
import tempfile
import unittest

from scripts.config import DatabaseConfig
from scripts.database import get_connection, init_db
from scripts.resources import (
    ProcessSupervisor,
    ResourceCheckResult,
    ResourceLimit,
    ResourceManager,
    ResourceStatus,
    ResourceType,
    StreamResourceRequirements,
    TempFileManager,
    get_resource_manager,
    get_temp_file_manager,
    preflight_check,
)


class ResourceTypeTest(unittest.TestCase):
    def test_resource_type_values(self):
        self.assertEqual(ResourceType.CPU.value, "cpu")
        self.assertEqual(ResourceType.MEMORY.value, "memory")
        self.assertEqual(ResourceType.DISK.value, "disk")
        self.assertEqual(ResourceType.STREAM.value, "stream")
        self.assertEqual(ResourceType.WORKER.value, "worker")


class ResourceStatusTest(unittest.TestCase):
    def test_resource_status_values(self):
        self.assertEqual(ResourceStatus.AVAILABLE.value, "available")
        self.assertEqual(ResourceStatus.LIMITED.value, "limited")
        self.assertEqual(ResourceStatus.EXHAUSTED.value, "exhausted")


class ResourceLimitTest(unittest.TestCase):
    def test_resource_limit_creation(self):
        limit = ResourceLimit(ResourceType.CPU, max_value=80.0)
        self.assertEqual(limit.resource_type, ResourceType.CPU)
        self.assertEqual(limit.max_value, 80.0)
        self.assertEqual(limit.warning_threshold, 0.8)
        self.assertEqual(limit.critical_threshold, 0.95)


class StreamResourceRequirementsTest(unittest.TestCase):
    def test_requirements_creation(self):
        req = StreamResourceRequirements(
            stream_id="stream-001",
            estimated_cpu_percent=25.0,
            estimated_memory_mb=1024.0,
            estimated_disk_mb=2048.0,
        )
        self.assertEqual(req.stream_id, "stream-001")
        self.assertEqual(req.estimated_cpu_percent, 25.0)
        self.assertEqual(req.estimated_memory_mb, 1024.0)


class ResourceManagerTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test.db")
        config = DatabaseConfig(url=f"sqlite:///{self.db_path}")
        init_db(config)

        self.conn = get_connection()
        try:
            self.conn.execute(
                "INSERT INTO organizations (id, name, slug) VALUES (?, ?, ?)",
                ("org-default", "Default Org", "default"),
            )
            self.conn.commit()
        except Exception:
            self.conn.close()
            raise

    def tearDown(self):
        try:
            conn = get_connection()
            conn.close()
        except Exception:  # noqa: S110, BLE001
            pass
        import scripts.database as dbmod

        dbmod._local.conn = None
        dbmod._config = dbmod.DatabaseConfig()
        self.temp_dir.cleanup()

    def test_resource_manager_creation(self):
        manager = ResourceManager()
        self.assertIsNotNone(manager)
        self.assertIn(ResourceType.CPU, manager.limits)

    def test_check_resources(self):
        manager = ResourceManager()
        req = StreamResourceRequirements(
            stream_id="stream-001",
            estimated_cpu_percent=10.0,
            estimated_memory_mb=256.0,
            estimated_disk_mb=512.0,
        )
        results = manager.check_resources(req)
        self.assertEqual(len(results), 4)  # CPU, Memory, Disk, Stream

        for r in results:
            self.assertIsInstance(r, ResourceCheckResult)
            self.assertIn(
                r.status,
                [
                    ResourceStatus.AVAILABLE,
                    ResourceStatus.LIMITED,
                    ResourceStatus.EXHAUSTED,
                ],
            )

    def test_can_start_stream(self):
        manager = ResourceManager()
        req = StreamResourceRequirements(
            stream_id="stream-001",
            estimated_cpu_percent=5.0,
            estimated_memory_mb=128.0,
            estimated_disk_mb=256.0,
        )
        can_start, _results = manager.can_start_stream(req)
        self.assertTrue(can_start)

    def test_reserve_and_release_resources(self):
        manager = ResourceManager()
        req = StreamResourceRequirements(
            stream_id="stream-001",
            estimated_cpu_percent=10.0,
            estimated_memory_mb=256.0,
            estimated_disk_mb=512.0,
        )

        # Reserve
        reserved = manager.reserve_stream_resources("stream-001", req)
        self.assertTrue(reserved)

        # Release
        released = manager.release_stream_resources("stream-001")
        self.assertTrue(released)

        # Cannot release twice
        released_again = manager.release_stream_resources("stream-001")
        self.assertFalse(released_again)

    def test_get_resource_status(self):
        manager = ResourceManager()
        status = manager.get_resource_status()
        self.assertIn("cpu", status)
        self.assertIn("memory", status)
        self.assertIn("disk", status)
        self.assertIn("stream", status)

        for resource_status in status.values():
            self.assertIn("current", resource_status)
            self.assertIn("max", resource_status)
            self.assertIn("available", resource_status)
            self.assertIn("usage_percent", resource_status)


class TempFileManagerTest(unittest.TestCase):
    def test_temp_file_manager_creation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = TempFileManager(base_dir=tmpdir)
            self.assertIsNotNone(manager)

    def test_create_temp_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = TempFileManager(base_dir=tmpdir)
            path = manager.create_temp_file(prefix="test_", suffix=".txt")
            self.assertTrue(os.path.exists(path))
            self.assertTrue(path.startswith(tmpdir))
            self.assertTrue(path.endswith(".txt"))

    def test_create_temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = TempFileManager(base_dir=tmpdir)
            path = manager.create_temp_dir(prefix="testdir_")
            self.assertTrue(os.path.isdir(path))
            self.assertTrue(path.startswith(tmpdir))

    def test_track_untrack_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = TempFileManager(base_dir=tmpdir)
            path = manager.create_temp_file()

            # Already tracked
            count_before = manager.get_tracked_count()

            # Untrack
            result = manager.untrack_file(path)
            self.assertTrue(result)

            count_after = manager.get_tracked_count()
            self.assertEqual(count_after, count_before - 1)

    def test_cleanup_old_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = TempFileManager(
                base_dir=tmpdir, max_age_hours=0
            )  # Immediate expiration
            path = manager.create_temp_file()
            self.assertTrue(os.path.exists(path))

            # Should clean up immediately since max_age=0
            cleaned = manager.cleanup_old_files()
            self.assertGreaterEqual(cleaned, 1)
            self.assertFalse(os.path.exists(path))


class ProcessSupervisorTest(unittest.TestCase):
    def test_process_supervisor_creation(self):
        supervisor = ProcessSupervisor(max_restarts=3, restart_delay=1.0)
        self.assertIsNotNone(supervisor)

    def test_register_unregister_process(self):
        supervisor = ProcessSupervisor()
        # Register with a dummy PID and no callback
        supervisor.register_process("test_proc", 99999)

        # Note: check_process requires psutil which may not work in test environment
        # Just test register/unregister
        unregistered = supervisor.unregister_process("test_proc")
        self.assertTrue(unregistered)

        unregistered_again = supervisor.unregister_process("test_proc")
        self.assertFalse(unregistered_again)


class ResourceManagerSingletonTest(unittest.TestCase):
    def test_singleton(self):
        m1 = get_resource_manager()
        m2 = get_resource_manager()
        self.assertIs(m1, m2)


class TempFileManagerSingletonTest(unittest.TestCase):
    def test_singleton(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            m1 = get_temp_file_manager(tmpdir)
            m2 = get_temp_file_manager(tmpdir)
            self.assertIs(m1, m2)


class PreflightCheckTest(unittest.TestCase):
    def test_preflight_check(self):
        req = StreamResourceRequirements(
            stream_id="stream-test",
            estimated_cpu_percent=5.0,
            estimated_memory_mb=128.0,
            estimated_disk_mb=256.0,
        )
        ok, details = preflight_check("stream-test", req)
        self.assertIn("can_start", details)
        self.assertIn("resources", details)
        self.assertIn("assets_ok", details)
        self.assertIn("rights_ok", details)
        self.assertIn("network_ok", details)
        self.assertIn("youtube_ok", details)
        self.assertIsInstance(ok, bool)


if __name__ == "__main__":
    unittest.main()
