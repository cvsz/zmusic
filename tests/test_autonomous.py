"""Autonomous mode tests for zMusic."""

import os
import tempfile
import unittest

from scripts.autonomous import (
    ApprovalGate,
    AutonomousConfig,
    AutonomousController,
    AutonomousCycleResult,
    AutonomousMode,
    get_approval_status,
    get_autonomous_controller,
    set_autonomous_mode,
)
from scripts.channel import (
    ChannelConfig,
    MusicConfig,
    ProgrammingMode,
    get_channel_manager,
)
from scripts.config import DatabaseConfig
from scripts.database import get_connection, init_db


class AutonomousConfigTest(unittest.TestCase):
    def test_autonomous_config_defaults(self):
        config = AutonomousConfig()
        self.assertEqual(config.mode, AutonomousMode.MANUAL)
        self.assertEqual(config.required_approvals, [])
        self.assertFalse(config.auto_schedule)
        self.assertFalse(config.auto_start_stream)
        self.assertTrue(config.auto_recover)
        self.assertEqual(config.max_concurrent_streams, 1)

    def test_autonomous_config_custom(self):
        config = AutonomousConfig(
            mode=AutonomousMode.AUTONOMOUS,
            required_approvals=[ApprovalGate.CONTENT_APPROVAL],
            auto_schedule=True,
            auto_start_stream=True,
        )
        self.assertEqual(config.mode, AutonomousMode.AUTONOMOUS)
        self.assertEqual(len(config.required_approvals), 1)
        self.assertTrue(config.auto_schedule)
        self.assertTrue(config.auto_start_stream)


class AutonomousModeTest(unittest.TestCase):
    def test_autonomous_mode_values(self):
        self.assertEqual(AutonomousMode.MANUAL.value, "manual")
        self.assertEqual(AutonomousMode.ASSISTED.value, "assisted")
        self.assertEqual(AutonomousMode.AUTONOMOUS.value, "autonomous")


class ApprovalGateTest(unittest.TestCase):
    def test_approval_gate_values(self):
        self.assertEqual(ApprovalGate.CONTENT_APPROVAL.value, "content_approval")
        self.assertEqual(ApprovalGate.RIGHTS_APPROVAL.value, "rights_approval")
        self.assertEqual(ApprovalGate.STREAM_APPROVAL.value, "stream_approval")
        self.assertEqual(ApprovalGate.METADATA_APPROVAL.value, "metadata_approval")


class AutonomousCycleResultTest(unittest.TestCase):
    def test_cycle_result_creation(self):
        result = AutonomousCycleResult(
            cycle_id="cycle-001",
            channel_id="ch-001",
            success=True,
            steps_completed=["step1", "step2"],
            steps_failed=[],
        )
        self.assertEqual(result.cycle_id, "cycle-001")
        self.assertEqual(result.channel_id, "ch-001")
        self.assertTrue(result.success)
        self.assertEqual(result.steps_completed, ["step1", "step2"])


class AutonomousControllerTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test.db")
        config = DatabaseConfig(url=f"sqlite:///{self.db_path}")
        init_db(config)

        # Store connection; do NOT close it here as init_db stores it
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

    def test_controller_creation(self):
        config = AutonomousConfig(mode=AutonomousMode.AUTONOMOUS)
        controller = AutonomousController(config)
        self.assertIsNotNone(controller)
        self.assertEqual(controller.config.mode, AutonomousMode.AUTONOMOUS)

    def test_controller_singleton(self):
        c1 = get_autonomous_controller()
        c2 = get_autonomous_controller()
        self.assertIs(c1, c2)

    def test_run_autonomous_cycle_not_found(self):
        controller = AutonomousController()
        result = controller.run_autonomous_cycle("nonexistent")
        self.assertFalse(result.success)
        self.assertIn("not found", result.error.lower())


class SetAutonomousModeTest(unittest.TestCase):
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

    def test_set_autonomous_mode(self):
        manager = get_channel_manager()
        config = ChannelConfig(
            channel_id="ch-test",
            name="Test Channel",
            music=MusicConfig(genres=["lofi"]),
        )
        manager.create_channel(config, "org-default")

        set_autonomous_mode("ch-test", ProgrammingMode.AUTONOMOUS)
        channel = manager.get_channel("ch-test")
        self.assertEqual(channel.programming_mode, ProgrammingMode.AUTONOMOUS)

    def test_get_approval_status(self):
        manager = get_channel_manager()
        config = ChannelConfig(
            channel_id="ch-test",
            name="Test Channel",
            music=MusicConfig(genres=["lofi"]),
        )
        manager.create_channel(config, "org-default")

        status = get_approval_status("ch-test")
        self.assertEqual(status["channel_id"], "ch-test")
        self.assertEqual(status["mode"], "manual")  # Default mode


if __name__ == "__main__":
    unittest.main()
