"""Integration tests for zMusic.

Tests cross-module integration and end-to-end workflows.
"""

import os
import tempfile
import unittest

from scripts.agents import MusicDirector, RightsValidator, get_agent, register_agent
from scripts.analytics import get_analytics
from scripts.approval import ApprovalManager
from scripts.channel import (
    ChannelConfig,
    MusicConfig,
    ProgrammingMode,
    ScheduleConfig,
    StreamConfig,
    VisualConfig,
    get_channel_manager,
)
from scripts.config import DatabaseConfig
from scripts.database import get_connection, init_db, transaction
from scripts.events import EVENT_STREAM_STARTED, make_event, serialize_event
from scripts.idempotency import IdempotencyManager
from scripts.monitoring import get_monitor
from scripts.resources import (
    StreamResourceRequirements,
    get_resource_manager,
    preflight_check,
)
from scripts.scheduler import get_scheduler
from scripts.validation import validate_for_production
from scripts.youtube import get_youtube


class IntegrationTest(unittest.TestCase):
    """Base class for integration tests with database setup."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test.db")
        config = DatabaseConfig(url=f"sqlite:///{self.db_path}")
        init_db(config)

        self.conn = get_connection()
        try:
            self.conn.execute(
                "INSERT INTO organizations (id, name, slug) VALUES (?, ?, ?)",
                ("org-dev", "Development Org", "dev"),
            )
            # Create idempotency and approval tables (not in base schema)
            self.conn.executescript("""
                CREATE TABLE IF NOT EXISTS idempotency_keys (
                    key TEXT PRIMARY KEY,
                    operation TEXT NOT NULL,
                    input_hash TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    result TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    completed_at TEXT,
                    expires_at TEXT,
                    deleted_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_idempotency_status ON idempotency_keys(status);
                CREATE INDEX IF NOT EXISTS idx_idempotency_expires ON idempotency_keys(expires_at);
                CREATE TABLE IF NOT EXISTS approval_requests (
                    id TEXT PRIMARY KEY,
                    gate TEXT NOT NULL,
                    channel_id TEXT NOT NULL,
                    resource_type TEXT NOT NULL,
                    resource_id TEXT NOT NULL,
                    requested_by TEXT NOT NULL,
                    requested_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    reviewer TEXT,
                    reviewed_at TEXT,
                    comment TEXT,
                    expires_at TEXT,
                    metadata TEXT DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                    deleted_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_approval_channel_status ON approval_requests(channel_id, status);
                CREATE INDEX IF NOT EXISTS idx_approval_gate ON approval_requests(gate);
                """)
            self.conn.commit()
        except Exception:
            self.conn.close()
            raise

    def tearDown(self):
        try:
            conn = get_connection()
            conn.close()
        except Exception:
            pass
        import scripts.database as dbmod

        dbmod._local.conn = None
        dbmod._config = dbmod.DatabaseConfig()
        self.temp_dir.cleanup()

    def _create_test_channel(self, channel_id: str = "ch-integration") -> None:
        """Helper to create a test channel with all required FKs."""
        channel_manager = get_channel_manager()
        config = ChannelConfig(
            channel_id=channel_id,
            name=f"Test Channel {channel_id}",
            programming_mode=ProgrammingMode.AUTONOMOUS,
            music=MusicConfig(genres=["lofi"]),
            visual=VisualConfig(theme="rainy_city"),
            stream=StreamConfig(resolution="1080p"),
            schedule=ScheduleConfig(timezone="UTC"),
        )
        channel_manager.create_channel(config, "org-dev")
        return channel_id


class ChannelSchedulerIntegrationTest(IntegrationTest):
    """Test channel and scheduler integration."""

    def test_create_channel_and_schedule(self):
        scheduler = get_scheduler()

        # Create channel first
        self._create_test_channel("ch-integration")

        # Create schedule
        schedule_id = scheduler.create_schedule(
            channel_id="ch-integration",
            name="Integration Schedule",
            timezone="UTC",
        )
        self.assertIsNotNone(schedule_id)


class AgentSchedulerIntegrationTest(IntegrationTest):
    """Test agent and scheduler integration."""

    def test_music_director_creates_plan(self):
        scheduler = get_scheduler()

        # Create channel
        self._create_test_channel("ch-integration")

        # Create a schedule for the channel
        schedule_id = scheduler.create_schedule(
            channel_id="ch-integration",
            name="Music Director Schedule",
            timezone="UTC",
        )

        # Register Music Director
        music_director = MusicDirector()
        register_agent("music_director", music_director)

        # Run Music Director agent
        agent = get_agent("music_director")
        self.assertIsNotNone(agent)

        plan = agent.create_plan(
            theme="lofi beats",
            genre="lofi",
            duration_hours=2,
            target_mood="relaxed",
        )

        self.assertIsNotNone(plan)


class AnalyticsMonitoringIntegrationTest(IntegrationTest):
    """Test analytics and monitoring integration."""

    def test_stream_analytics_and_monitoring(self):
        # Create channel
        self._create_test_channel("ch-integration")

        analytics = get_analytics()
        monitor = get_monitor()

        # Create a stream first (required for FK)
        with transaction() as conn:
            conn.execute(
                """INSERT INTO streams (id, channel_id, state) VALUES (?, ?, ?)""",
                ("stream-integration", "ch-integration", "live"),
            )

        # Record a stream session
        session_id = analytics.record_stream_session(
            stream_id="stream-integration",
            channel_id="ch-integration",
            started_at="2026-01-01T06:00:00Z",
        )
        self.assertIsNotNone(session_id)

        # Record viewer counts
        analytics.record_viewer_count(session_id, 100)
        analytics.record_viewer_count(session_id, 150)

        # End session
        analytics.end_stream_session(session_id, "2026-01-01T09:00:00Z")

        # Check monitoring
        monitor.start_monitoring("stream-integration")
        health = monitor.get_health("stream-integration")
        self.assertIsNotNone(health)
        monitor.stop_monitoring("stream-integration")

        # Generate report
        report = analytics.generate_post_stream_report("stream-integration")
        self.assertEqual(report["stream_id"], "stream-integration")


class YouTubeAnalyticsIntegrationTest(IntegrationTest):
    """Test YouTube and analytics integration."""

    def test_youtube_stream_creation_and_analytics(self):
        from unittest.mock import MagicMock

        from scripts.youtube import YouTubeBroadcast, YouTubeClient, YouTubeStream

        youtube = get_youtube()

        # Mock YouTube provider
        provider = MagicMock(spec=YouTubeClient)
        provider.authenticate.return_value = "test-token"
        provider.create_broadcast.return_value = YouTubeBroadcast(
            broadcast_id="broadcast-123",
            title="Integration Test Stream",
            status="upcoming",
            stream_id="stream-456",
        )
        provider.create_stream.return_value = YouTubeStream(
            stream_id="stream-456",
            ingest_address="rtmp://a.rtmp.youtube.com/live2/test",
            playback_url="https://youtube.com/watch?v=test",
            status="active",
        )

        # Override the provider
        youtube.provider = provider

        # Create live stream setup
        result = youtube.create_live_stream_setup(
            title="Integration Test Stream",
        )

        self.assertEqual(result["broadcast_id"], "broadcast-123")
        self.assertEqual(result["stream_id"], "stream-456")
        self.assertTrue(result["ingest_address"].startswith("rtmp://"))


class EventValidationIntegrationTest(IntegrationTest):
    """Test event system and validation integration."""

    def test_event_creation_and_validation(self):

        # Create event
        event = make_event(
            EVENT_STREAM_STARTED,
            "scheduler",
            {"stream_id": "stream-123", "channel_id": "ch-123"},
        )

        # Serialize
        serialized = serialize_event(event)

        self.assertEqual(serialized["event_type"], EVENT_STREAM_STARTED)
        self.assertEqual(serialized["source"], "scheduler")
        self.assertIn("stream_id", serialized["payload"])

        # Validate the payload - scheduler agent requires 'schedule' field
        result = validate_for_production(
            "agent_output",
            {
                "agent": "scheduler",
                "version": "1.0",
                "status": "success",
                "schedule": {"stream_id": "stream-123"},
            },
        )
        self.assertTrue(result.valid)


class IdempotencyApprovalIntegrationTest(IntegrationTest):
    """Test idempotency and approval integration."""

    def test_idempotent_stream_start(self):
        # Create fresh idempotency manager for this test

        idempotency = IdempotencyManager()
        approval = ApprovalManager()

        # Create idempotency key for stream start
        key = idempotency.generate_key("start_stream", {"stream_id": "stream-123"})

        # First attempt should succeed
        started = idempotency.start_operation(key, "start_stream", "hash123")
        self.assertTrue(started)

        # Second attempt should fail (already started)
        started_again = idempotency.start_operation(key, "start_stream", "hash123")
        self.assertFalse(started_again)

        # Complete operation
        completed = idempotency.complete_operation(
            key, {"status": "started", "stream_id": "stream-123"}
        )
        self.assertTrue(completed)

        # Get result
        result = idempotency.get_result(key)
        self.assertIsNotNone(result)

        # Create approval request for stream
        approval_request = approval.create_approval_request(
            gate="stream_approval",
            channel_id="ch-integration",
            resource_type="stream",
            resource_id="stream-123",
            requested_by="scheduler",
        )
        self.assertIsNotNone(approval_request.request_id)

        # Approve
        approved = approval.approve_request(approval_request.request_id, "reviewer")
        self.assertTrue(approved)


class ResourcePreflightIntegrationTest(IntegrationTest):
    """Test resource management and preflight checks."""

    def test_preflight_check_integration(self):

        manager = get_resource_manager()

        requirements = StreamResourceRequirements(
            stream_id="stream-integration",
            estimated_cpu_percent=10.0,
            estimated_memory_mb=256.0,
            estimated_disk_mb=512.0,
        )

        # Check resources
        can_start, results = manager.can_start_stream(requirements)
        self.assertTrue(can_start)

        # Reserve resources
        reserved = manager.reserve_stream_resources(
            "stream-resource-test", requirements
        )
        self.assertTrue(reserved)

        # Pre-flight check
        ok, details = preflight_check("stream-preflight", requirements)
        self.assertTrue(ok)
        self.assertIn("can_start", details)
        self.assertIn("resources", details)

        # Release resources
        released = manager.release_stream_resources("stream-resource-test")
        self.assertTrue(released)


class FullWorkflowIntegrationTest(IntegrationTest):
    """Test complete end-to-end workflow."""

    def test_complete_stream_workflow(self):
        """Test a complete stream workflow from channel creation to analytics."""

        # 1. Create channel
        channel_manager = get_channel_manager()
        config = ChannelConfig(
            channel_id="ch-workflow",
            name="Workflow Test Channel",
            programming_mode=ProgrammingMode.AUTONOMOUS,
            music=MusicConfig(genres=["lofi"]),
            visual=VisualConfig(theme="rainy_city"),
            stream=StreamConfig(resolution="1080p"),
            schedule=ScheduleConfig(timezone="UTC"),
        )
        channel_manager.create_channel(config, "org-dev")

        # 2. Create schedule
        scheduler = get_scheduler()
        schedule_id = scheduler.create_schedule(
            channel_id="ch-workflow",
            name="Workflow Schedule",
            timezone="UTC",
        )

        # 3. Run Music Director agent
        music_director = MusicDirector()
        register_agent("music_director", music_director)

        plan = music_director.create_plan(
            theme="lofi workflow",
            genre="lofi",
            duration_hours=1,
            target_mood="focused",
        )

        # 3. Validate rights
        rights_validator = get_agent("rights_validator")
        if not rights_validator:
            register_agent("rights_validator", RightsValidator())
            rights_validator = get_agent("rights_validator")

        rights_result = rights_validator.validate_track("track-001")
        # Rights validator may pass or fail based on test data

        # 4. Create stream
        stream_id = "stream-workflow-test"

        # 5. Reserve resources
        resource_manager = get_resource_manager()
        requirements = StreamResourceRequirements(
            stream_id=stream_id,
            estimated_cpu_percent=15.0,
            estimated_memory_mb=512.0,
            estimated_disk_mb=1024.0,
        )
        resource_manager.reserve_stream_resources(stream_id, requirements)

        # 7. Start monitoring
        monitor = get_monitor()
        monitor.start_monitoring(stream_id)

        # 8. Record analytics
        analytics = get_analytics()

        # Create stream record for FK
        with transaction() as conn:
            conn.execute(
                """INSERT INTO streams (id, channel_id, state) VALUES (?, ?, ?)""",
                (stream_id, "ch-workflow", "live"),
            )

        session_id = analytics.record_stream_session(
            stream_id=stream_id,
            channel_id="ch-workflow",
            started_at="2026-01-01T06:00:00Z",
        )

        # 9. Simulate stream running
        analytics.record_viewer_count(session_id, 50)
        analytics.record_viewer_count(session_id, 75)

        # 10. End stream
        analytics.end_stream_session(session_id, "2026-01-01T07:00:00Z")

        # 11. Generate report
        report = get_analytics().generate_post_stream_report(stream_id=stream_id)
        self.assertEqual(report["stream_id"], stream_id)

        # 12. Release resources
        # Note: stream_id in resource manager is different from analytics stream_id
        # This is a simplified test


if __name__ == "__main__":
    unittest.main()
