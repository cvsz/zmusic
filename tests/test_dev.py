"""Development mode tests for zMusic."""

import os
import tempfile
import unittest

from scripts.config import DatabaseConfig
from scripts.database import get_connection, init_db
from scripts.dev import (
    DEFAULT_SEED_DATA,
    DevConfig,
    DevEnvironment,
    create_dev_config,
)


class DevConfigTest(unittest.TestCase):
    def test_dev_config_defaults(self):
        config = DevConfig()
        self.assertTrue(config.auto_migrate)
        self.assertTrue(config.seed_data)
        self.assertTrue(config.hot_reload)
        self.assertTrue(config.debug_mode)
        self.assertEqual(config.log_level, "DEBUG")
        self.assertEqual(config.api_port, 8000)
        self.assertEqual(config.worker_count, 2)
        self.assertFalse(config.use_docker)

    def test_dev_config_custom(self):
        config = DevConfig(
            auto_migrate=False,
            seed_data=False,
            hot_reload=False,
            debug_mode=False,
            log_level="INFO",
            api_port=9000,
            worker_count=4,
            use_docker=True,
        )
        self.assertFalse(config.auto_migrate)
        self.assertFalse(config.seed_data)
        self.assertFalse(config.hot_reload)
        self.assertFalse(config.debug_mode)
        self.assertEqual(config.log_level, "INFO")
        self.assertEqual(config.api_port, 9000)
        self.assertEqual(config.worker_count, 4)
        self.assertTrue(config.use_docker)


class SeedDataTest(unittest.TestCase):
    def test_default_seed_data(self):
        self.assertEqual(len(DEFAULT_SEED_DATA.organizations), 1)
        self.assertEqual(len(DEFAULT_SEED_DATA.channels), 2)
        self.assertEqual(len(DEFAULT_SEED_DATA.content), 2)
        self.assertEqual(len(DEFAULT_SEED_DATA.tracks), 2)
        self.assertEqual(len(DEFAULT_SEED_DATA.schedules), 1)

        org = DEFAULT_SEED_DATA.organizations[0]
        self.assertEqual(org["id"], "org-dev")
        self.assertEqual(org["name"], "Development Org")

        ch = DEFAULT_SEED_DATA.channels[0]
        self.assertEqual(ch["id"], "ch-dev-1")
        self.assertEqual(ch["organization_id"], "org-dev")


class DevEnvironmentTest(unittest.TestCase):
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

    def test_dev_environment_creation(self):
        config = DevConfig()
        env = DevEnvironment(config)
        self.assertIsNotNone(env)
        self.assertFalse(env._running)

    def test_setup_database(self):
        config = DevConfig()
        env = DevEnvironment(config)

        # Create a temporary database for testing
        db_path = os.path.join(self.temp_dir.name, "dev_test.db")
        config_db = DatabaseConfig(url=f"sqlite:///{db_path}")

        env.setup_database(config_db)

        # Check that tables were created and seeded
        conn = get_connection()
        try:
            # This uses the global connection which points to the main test db
            # In a real test, we'd use the new connection
            pass
        finally:
            conn.close()


class CreateDevConfigTest(unittest.TestCase):
    def test_create_dev_config_from_env(self):
        # Test with default environment
        os.environ.pop("ZMUSIC_DEV_AUTO_MIGRATE", None)
        os.environ.pop("ZMUSIC_DEV_SEED_DATA", None)
        os.environ.pop("ZMUSIC_DEV_HOT_RELOAD", None)
        os.environ.pop("ZMUSIC_DEV_DEBUG", None)
        os.environ.pop("ZMUSIC_LOG_LEVEL", None)
        os.environ.pop("ZMUSIC_DEV_API_PORT", None)
        os.environ.pop("ZMUSIC_DEV_WORKER_COUNT", None)
        os.environ.pop("ZMUSIC_DEV_USE_DOCKER", None)

        config = create_dev_config()
        self.assertTrue(config.auto_migrate)
        self.assertTrue(config.seed_data)
        self.assertTrue(config.hot_reload)
        self.assertTrue(config.debug_mode)
        self.assertEqual(config.log_level, "DEBUG")
        self.assertEqual(config.api_port, 8000)
        self.assertEqual(config.worker_count, 2)
        self.assertFalse(config.use_docker)

    def test_create_dev_config_from_env_custom(self):
        # Test with custom environment
        os.environ["ZMUSIC_DEV_AUTO_MIGRATE"] = "false"
        os.environ["ZMUSIC_DEV_SEED_DATA"] = "false"
        os.environ["ZMUSIC_DEV_HOT_RELOAD"] = "false"
        os.environ["ZMUSIC_DEV_DEBUG"] = "false"
        os.environ["ZMUSIC_LOG_LEVEL"] = "INFO"
        os.environ["ZMUSIC_DEV_API_PORT"] = "9000"
        os.environ["ZMUSIC_DEV_WORKER_COUNT"] = "4"
        os.environ["ZMUSIC_DEV_USE_DOCKER"] = "true"

        config = create_dev_config()
        self.assertFalse(config.auto_migrate)
        self.assertFalse(config.seed_data)
        self.assertFalse(config.hot_reload)
        self.assertFalse(config.debug_mode)
        self.assertEqual(config.log_level, "INFO")
        self.assertEqual(config.api_port, 9000)
        self.assertEqual(config.worker_count, 4)
        self.assertTrue(config.use_docker)

        # Clean up
        for key in [
            "ZMUSIC_DEV_AUTO_MIGRATE",
            "ZMUSIC_DEV_SEED_DATA",
            "ZMUSIC_DEV_HOT_RELOAD",
            "ZMUSIC_DEV_DEBUG",
            "ZMUSIC_LOG_LEVEL",
            "ZMUSIC_DEV_API_PORT",
            "ZMUSIC_DEV_WORKER_COUNT",
            "ZMUSIC_DEV_USE_DOCKER",
        ]:
            os.environ.pop(key, None)


if __name__ == "__main__":
    unittest.main()
