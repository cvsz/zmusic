"""Agent tests for zMusic."""

import os
import tempfile
import unittest

from scripts.agents import (
    AgentResult,
    MusicDirector,
    RightsValidator,
    get_agent,
    initialize_agents,
    register_agent,
)
from scripts.config import AppConfig, DatabaseConfig
from scripts.database import get_connection, init_db


class AgentResultTest(unittest.TestCase):
    def test_agent_result_to_dict(self):
        result = AgentResult(
            agent="test_agent",
            version="1.0",
            status="success",
            plan={"key": "value"},
            warnings=["warning1"],
            requires_approval=True,
        )
        d = result.to_dict()
        self.assertEqual(d["agent"], "test_agent")
        self.assertEqual(d["version"], "1.0")
        self.assertEqual(d["status"], "success")
        self.assertEqual(d["plan"], {"key": "value"})
        self.assertEqual(d["warnings"], ["warning1"])
        self.assertEqual(d["requires_approval"], True)
        self.assertIsNone(d["error"])

    def test_agent_result_to_json(self):
        result = AgentResult(
            agent="test_agent",
            version="1.0",
            status="success",
            plan={},
        )
        j = result.to_json()
        self.assertIn("test_agent", j)
        self.assertIn("success", j)


class RightsValidatorTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test.db")
        config = DatabaseConfig(url=f"sqlite:///{self.db_path}")
        init_db(config)

        conn = get_connection()
        try:
            # Insert org, channel, track, and rights
            conn.execute(
                "INSERT INTO organizations (id, name, slug) VALUES (?, ?, ?)",
                ("org-1", "Test Org", "test-org"),
            )
            conn.execute(
                "INSERT INTO channels (id, organization_id, name) VALUES (?, ?, ?)",
                ("ch-1", "org-1", "Test Channel"),
            )
            conn.execute(
                "INSERT INTO tracks (id, title, artist) VALUES (?, ?, ?)",
                ("track-1", "Test Track", "Test Artist"),
            )
            conn.execute(
                """
                INSERT INTO track_rights
                (track_id, ownership_verified, license_valid_until,
                 commercial_allowed, youtube_allowed, attribution_required,
                 geographic_restrictions)
                VALUES (?, 1, NULL, 1, 1, 0, NULL)
                """,
                ("track-1",),
            )
            conn.commit()
        finally:
            # Don't close here — init_db owns _local.conn; close in tearDown
            pass

    def tearDown(self):
        conn = get_connection()
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            conn.close()
        except Exception:  # noqa: S110, BLE001
            pass
        self.temp_dir.cleanup()

    def test_validate_track_cleared(self):
        validator = RightsValidator()
        rights = validator.validate_track("track-1")
        self.assertEqual(rights.track_id, "track-1")
        self.assertTrue(rights.youtube_allowed)
        self.assertTrue(rights.commercial_allowed)
        self.assertFalse(rights.attribution_required)

    def test_validate_track_missing(self):
        validator = RightsValidator()
        rights = validator.validate_track("nonexistent")
        self.assertFalse(rights.youtube_allowed)
        self.assertFalse(rights.commercial_allowed)

    def test_is_stream_safe_all_cleared(self):
        validator = RightsValidator()
        safe, failures = validator.is_stream_safe(["track-1"])
        self.assertTrue(safe)
        self.assertEqual(failures, [])

    def test_is_stream_safe_multiple_tracks(self):
        conn = get_connection()
        try:
            conn.execute(
                "INSERT INTO tracks (id, title, artist) VALUES (?, ?, ?)",
                ("track-2", "Track 2", "Artist 2"),
            )
            conn.execute(
                """
                INSERT INTO track_rights
                (track_id, ownership_verified, license_valid_until,
                 commercial_allowed, youtube_allowed, attribution_required)
                VALUES (?, 1, NULL, 1, 1, 0)
                """,
                ("track-2",),
            )
            conn.commit()
        finally:
            pass  # Don't close shared connection

        validator = RightsValidator()
        safe, failures = validator.is_stream_safe(["track-1", "track-2"])
        self.assertTrue(safe)
        self.assertEqual(failures, [])

    def test_is_stream_safe_youtube_not_allowed(self):
        conn = get_connection()
        try:
            conn.execute(
                "INSERT INTO tracks (id, title, artist) VALUES (?, ?, ?)",
                ("track-bad", "Bad Track", "Bad Artist"),
            )
            conn.execute(
                """
                INSERT INTO track_rights
                (track_id, ownership_verified, license_valid_until,
                 commercial_allowed, youtube_allowed, attribution_required)
                VALUES (?, 1, NULL, 1, 0, 0)
                """,
                ("track-bad",),
            )
            conn.commit()
        finally:
            pass  # Don't close shared connection

        validator = RightsValidator()
        safe, failures = validator.is_stream_safe(["track-bad"])
        self.assertFalse(safe)
        self.assertTrue(any("YouTube not allowed" in f for f in failures))

    def test_validate_content_rights(self):
        validator = RightsValidator()
        result = validator.validate_content_rights("nonexistent-content")
        self.assertFalse(result["rights_valid"])
        self.assertEqual(result["tracks"], [])


class MusicDirectorTest(unittest.TestCase):
    def setUp(self):
        self.director = MusicDirector()

    def test_create_plan_basic(self):
        result = self.director.create_plan(
            theme="late night rain",
            genre="lofi",
            duration_hours=6,
            target_mood="calm",
        )
        self.assertEqual(result.agent, "music_director")
        self.assertEqual(result.status, "success")
        self.assertEqual(result.version, "1.0")
        self.assertFalse(result.requires_approval)
        self.assertEqual(len(result.warnings), 0)

        plan = result.plan
        self.assertEqual(plan["theme"], "late night rain")
        self.assertEqual(plan["genre"], "lofi")
        self.assertEqual(plan["mood"], "calm")
        self.assertEqual(plan["bpm_range"], [60, 90])
        self.assertEqual(plan["session_duration_hours"], 6)
        self.assertEqual(len(plan["energy_curve"]), 6)
        self.assertEqual(plan["track_ordering"], "by_energy_ascending")
        self.assertEqual(plan["transition_strategy"], "crossfade")

    def test_create_plan_unknown_genre(self):
        result = self.director.create_plan(
            theme="test",
            genre="nonexistent_genre",
            duration_hours=4,
            target_mood="calm",
        )
        self.assertEqual(result.status, "warning")
        self.assertTrue(len(result.warnings) > 0)
        self.assertEqual(result.plan["bpm_range"], [80, 120])

    def test_create_plan_unknown_mood(self):
        result = self.director.create_plan(
            theme="test",
            genre="lofi",
            duration_hours=4,
            target_mood="nonexistent_mood",
        )
        self.assertEqual(result.status, "warning")
        self.assertTrue(len(result.warnings) > 0)

    def test_create_plan_requires_approval_long_duration(self):
        result = self.director.create_plan(
            theme="test",
            genre="lofi",
            duration_hours=8,
            target_mood="calm",
        )
        self.assertTrue(result.requires_approval)

    def test_create_plan_energetic_energy_curve(self):
        result = self.director.create_plan(
            theme="workout",
            genre="edm",
            duration_hours=2,
            target_mood="energetic",
        )
        curve = result.plan["energy_curve"]
        self.assertEqual(len(curve), 6)
        # Peak should be in the middle
        self.assertEqual(curve[2], 0.9)

    def test_result_to_json(self):
        result = self.director.create_plan(
            theme="test",
            genre="lofi",
            duration_hours=2,
            target_mood="calm",
        )
        j = result.to_json()
        self.assertIn("music_director", j)
        self.assertIn("lofi", j)
        self.assertIn("late night rain" if False else "test", j)


class AgentRegistryTest(unittest.TestCase):
    def test_register_and_get_agent(self):
        agent = MusicDirector()
        register_agent("test_agent", agent)
        retrieved = get_agent("test_agent")
        self.assertIs(retrieved, agent)

    def test_get_nonexistent_agent(self):
        self.assertIsNone(get_agent("nonexistent_agent"))

    def test_initialize_agents(self):
        config = AppConfig()
        initialize_agents(config)
        self.assertIsNotNone(get_agent("rights_validator"))
        self.assertIsNotNone(get_agent("music_director"))


if __name__ == "__main__":
    unittest.main()
