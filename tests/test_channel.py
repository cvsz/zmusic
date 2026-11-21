"""Channel configuration tests for zMusic."""

import os
import tempfile
import unittest

from scripts.channel import (
    ChannelConfig,
    ChannelManager,
    MusicConfig,
    ProgrammingMode,
    ScheduleConfig,
    StreamConfig,
    StreamResolution,
    VisualConfig,
    get_channel_manager,
)
from scripts.config import DatabaseConfig
from scripts.database import get_connection, init_db


class ChannelConfigTest(unittest.TestCase):
    def test_channel_config_creation(self):
        config = ChannelConfig(
            channel_id="ch-test",
            name="Test Channel",
            programming_mode=ProgrammingMode.AUTONOMOUS,
            music=MusicConfig(genres=["lofi", "ambient"]),
            visual=VisualConfig(theme="rainy_city"),
            stream=StreamConfig(resolution="1080p"),
            schedule=ScheduleConfig(timezone="Asia/Bangkok"),
        )
        self.assertEqual(config.channel_id, "ch-test")
        self.assertEqual(config.name, "Test Channel")
        self.assertEqual(config.programming_mode, ProgrammingMode.AUTONOMOUS)
        self.assertEqual(config.music.genres, ["lofi", "ambient"])
        self.assertEqual(config.visual.theme, "rainy_city")
        self.assertEqual(config.stream.resolution, "1080p")
        self.assertEqual(config.schedule.timezone, "Asia/Bangkok")

    def test_music_config_defaults(self):
        music = MusicConfig()
        self.assertEqual(music.genres, [])
        self.assertIsNone(music.mood)
        self.assertEqual(music.transition_style, "crossfade")

    def test_visual_config_defaults(self):
        visual = VisualConfig()
        self.assertEqual(visual.theme, "default")
        self.assertEqual(visual.camera_motion, "slow")
        self.assertEqual(visual.loop_duration_seconds, 1200)

    def test_stream_config_defaults(self):
        stream = StreamConfig()
        self.assertEqual(stream.resolution, "1080p")
        self.assertEqual(stream.fps, 30)
        self.assertEqual(stream.video_bitrate, "4500k")
        self.assertEqual(stream.encoder, "libx264")

    def test_schedule_config_defaults(self):
        schedule = ScheduleConfig()
        self.assertEqual(schedule.timezone, "UTC")


class ChannelManagerTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test.db")
        config = DatabaseConfig(url=f"sqlite:///{self.db_path}")
        init_db(config)

        # Store connection; do NOT close it here as init_db stores it
        # in thread-local _local.conn. Closing it would break
        # subsequent get_connection() calls.
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
        # Properly close and reset the thread-local connection
        try:
            conn = get_connection()
            conn.close()
        except Exception:
            pass
        import scripts.database as dbmod

        dbmod._local.conn = None
        dbmod._config = dbmod.DatabaseConfig()
        self.temp_dir.cleanup()

    def test_create_channel(self):
        manager = ChannelManager()
        config = ChannelConfig(
            channel_id="ch-test",
            name="Test Channel",
            programming_mode=ProgrammingMode.AUTONOMOUS,
            music=MusicConfig(genres=["lofi"]),
        )
        created = manager.create_channel(config)
        self.assertEqual(created.channel_id, "ch-test")
        self.assertEqual(created.name, "Test Channel")

    def test_get_channel(self):
        manager = ChannelManager()
        config = ChannelConfig(
            channel_id="ch-test",
            name="Test Channel",
            music=MusicConfig(genres=["lofi"]),
        )
        manager.create_channel(config)
        retrieved = manager.get_channel("ch-test")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.channel_id, "ch-test")
        self.assertEqual(retrieved.name, "Test Channel")

    def test_get_nonexistent_channel(self):
        manager = ChannelManager()
        result = manager.get_channel("nonexistent")
        self.assertIsNone(result)

    def test_update_channel(self):
        manager = ChannelManager()
        config = ChannelConfig(
            channel_id="ch-test",
            name="Test Channel",
            music=MusicConfig(genres=["lofi"]),
        )
        manager.create_channel(config)

        updated = manager.update_channel(
            "ch-test",
            {
                "name": "Updated Channel",
                "music": {"genres": ["lofi", "ambient"]},
            },
        )
        self.assertEqual(updated.name, "Updated Channel")
        self.assertEqual(updated.music.genres, ["lofi", "ambient"])
        self.assertEqual(updated.version, 2)

    def test_delete_channel(self):
        manager = ChannelManager()
        config = ChannelConfig(
            channel_id="ch-test",
            name="Test Channel",
            music=MusicConfig(genres=["lofi"]),
        )
        manager.create_channel(config)

        deleted = manager.delete_channel("ch-test")
        self.assertTrue(deleted)

        # Should not be retrievable after soft delete
        result = manager.get_channel("ch-test")
        self.assertIsNone(result)

    def test_list_channels(self):
        manager = ChannelManager()
        config1 = ChannelConfig(
            channel_id="ch-1", name="Channel 1", music=MusicConfig(genres=["lofi"])
        )
        config2 = ChannelConfig(
            channel_id="ch-2", name="Channel 2", music=MusicConfig(genres=["ambient"])
        )
        manager.create_channel(config1)
        manager.create_channel(config2)

        channels = manager.list_channels()
        self.assertEqual(len(channels), 2)
        channel_ids = {c.channel_id for c in channels}
        self.assertEqual(channel_ids, {"ch-1", "ch-2"})

    def test_get_channel_config_dict(self):
        manager = ChannelManager()
        config = ChannelConfig(
            channel_id="ch-test",
            name="Test Channel",
            music=MusicConfig(genres=["lofi"]),
        )
        manager.create_channel(config)

        config_dict = manager.get_channel_config_dict("ch-test")
        self.assertIsNotNone(config_dict)
        self.assertEqual(config_dict["name"], "Test Channel")
        self.assertEqual(config_dict["music"]["genres"], ["lofi"])


class ProgrammingModeTest(unittest.TestCase):
    def test_programming_mode_values(self):
        self.assertEqual(ProgrammingMode.MANUAL.value, "manual")
        self.assertEqual(ProgrammingMode.ASSISTED.value, "assisted")
        self.assertEqual(ProgrammingMode.AUTONOMOUS.value, "autonomous")

    def test_stream_resolution_values(self):
        self.assertEqual(StreamResolution.RES_480P.value, "480p")
        self.assertEqual(StreamResolution.RES_720P.value, "720p")
        self.assertEqual(StreamResolution.RES_1080P.value, "1080p")


class ChannelManagerSingletonTest(unittest.TestCase):
    def test_singleton(self):
        m1 = get_channel_manager()
        m2 = get_channel_manager()
        self.assertIs(m1, m2)


if __name__ == "__main__":
    unittest.main()
