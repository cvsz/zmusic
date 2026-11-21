"""Configuration tests for zMusic."""

import os
import unittest

from scripts.config import load_config, validate_config


class ConfigTest(unittest.TestCase):
    def setUp(self):
        # Clear env vars that could affect tests
        for key in list(os.environ.keys()):
            if key.startswith("ZMUSIC_"):
                del os.environ[key]

    def test_defaults(self):
        config = load_config()
        self.assertEqual(config.environment, "development")
        self.assertFalse(config.debug)
        self.assertEqual(config.log_level, "INFO")
        self.assertEqual(config.database.url, "sqlite:///data/zmusic.db")
        self.assertEqual(config.database.pool_size, 5)
        self.assertEqual(config.stream.max_concurrent_streams, 5)
        self.assertEqual(config.stream.default_fps, 30)
        self.assertEqual(config.stream.default_resolution, "1080p")
        self.assertEqual(config.security.rate_limit_per_minute, 60)
        self.assertEqual(config.security.max_upload_size_mb, 500)
        self.assertEqual(config.youtube.client_id, "")
        self.assertEqual(config.youtube.client_secret, "")

    def test_env_overrides(self):
        os.environ["ZMUSIC_ENV"] = "production"
        os.environ["ZMUSIC_DEBUG"] = "true"
        os.environ["ZMUSIC_LOG_LEVEL"] = "DEBUG"
        os.environ["ZMUSIC_DATABASE_URL"] = "sqlite:///data/test.db"
        os.environ["ZMUSIC_DB_POOL_SIZE"] = "10"
        os.environ["ZMUSIC_MAX_CONCURRENT_STREAMS"] = "3"
        os.environ["ZMUSIC_JWT_SECRET"] = "test-secret"
        os.environ["ZMUSIC_YOUTUBE_CLIENT_ID"] = "test-client-id"
        os.environ["ZMUSIC_YOUTUBE_CLIENT_SECRET"] = "test-secret"

        config = load_config()
        self.assertEqual(config.environment, "production")
        self.assertTrue(config.debug)
        self.assertEqual(config.log_level, "DEBUG")
        self.assertEqual(config.database.url, "sqlite:///data/test.db")
        self.assertEqual(config.database.pool_size, 10)
        self.assertEqual(config.stream.max_concurrent_streams, 3)
        self.assertEqual(config.security.jwt_secret, "test-secret")
        self.assertEqual(config.youtube.client_id, "test-client-id")
        self.assertEqual(config.youtube.client_secret, "test-secret")

    def test_validate_config_valid(self):
        config = load_config()
        errors = validate_config(config)
        self.assertEqual(errors, [])

    def test_validate_config_invalid_env(self):
        os.environ["ZMUSIC_ENV"] = "invalid"
        config = load_config()
        errors = validate_config(config)
        self.assertIn("ZMUSIC_ENV must be development, staging, or production", errors)

    def test_validate_config_production_missing_jwt(self):
        os.environ["ZMUSIC_ENV"] = "production"
        # Ensure JWT_SECRET is not set
        if "ZMUSIC_JWT_SECRET" in os.environ:
            del os.environ["ZMUSIC_JWT_SECRET"]
        config = load_config()
        errors = validate_config(config)
        self.assertIn("ZMUSIC_JWT_SECRET is required in production", errors)

    def test_validate_config_negative_streams(self):
        os.environ["ZMUSIC_MAX_CONCURRENT_STREAMS"] = "0"
        config = load_config()
        errors = validate_config(config)
        self.assertIn("ZMUSIC_MAX_CONCURRENT_STREAMS must be >= 1", errors)

    def test_validate_config_negative_pool(self):
        os.environ["ZMUSIC_DB_POOL_SIZE"] = "-1"
        config = load_config()
        errors = validate_config(config)
        self.assertIn("ZMUSIC_DB_POOL_SIZE must be >= 1", errors)


if __name__ == "__main__":
    unittest.main()
