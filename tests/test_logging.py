"""Logging tests for zMusic."""

import io
import json
import logging
import unittest

from scripts.logging import JsonFormatter, get_logger, setup_logging


class LoggingTest(unittest.TestCase):
    def setUp(self):
        self.stream = io.StringIO()
        self.handler = logging.StreamHandler(self.stream)
        self.handler.setFormatter(JsonFormatter())
        self.logger = logging.getLogger("zmusic.test")
        self.logger.setLevel(logging.DEBUG)
        self.logger.handlers = [self.handler]
        self.logger.propagate = False

    def test_json_output(self):
        self.logger.info("test message", extra={"custom_field": "custom_value"})
        output = self.stream.getvalue().strip()
        self.assertTrue(output, "Output should not be empty")

        record = json.loads(output)
        self.assertEqual(record["level"], "INFO")
        self.assertEqual(record["logger"], "zmusic.test")
        self.assertEqual(record["message"], "test message")
        self.assertEqual(record["custom_field"], "custom_value")
        self.assertIn("timestamp", record)

    def test_exception_logged(self):
        try:
            raise ValueError("test error")
        except ValueError:
            self.logger.exception("exception occurred")

        output = self.stream.getvalue().strip()
        record = json.loads(output)
        self.assertEqual(record["level"], "ERROR")
        self.assertIn("exception", record)
        self.assertIn("ValueError", record["exception"])

    def test_setup_logging(self):
        logger = setup_logging("DEBUG")
        self.assertEqual(logger.level, logging.DEBUG)
        self.assertEqual(logger.name, "zmusic")

    def test_get_logger(self):
        logger = get_logger("test.module")
        self.assertEqual(logger.name, "zmusic.test.module")


if __name__ == "__main__":
    unittest.main()
