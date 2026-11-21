"""Validation tests for zMusic."""

import unittest


def assertAnyIn(substring: str, container: tuple) -> None:
    """Assert that substring is contained in any element of the tuple."""
    found = any(substring in error for error in container)
    if not found:
        raise AssertionError(f"'{substring}' not found in any element of {container}")


def assertAllIn(substring: str, container: tuple) -> None:
    """Assert that substring is contained in every element of the tuple."""
    found = all(substring in error for error in container)
    if not found:
        raise AssertionError(f"'{substring}' not in all elements of {container}")


from scripts.validation import (
    ValidationResult,
    validate_agent_output,
    validate_channel_config,
    validate_for_production,
    validate_stream_config,
    validate_track_rights,
)


class ValidationResultTest(unittest.TestCase):
    def test_validation_result_creation(self):
        result = ValidationResult(valid=True)
        self.assertTrue(result.valid)
        self.assertEqual(result.errors, ())

        result_with_error = result.with_error("test error")
        self.assertFalse(result_with_error.valid)
        self.assertEqual(result_with_error.errors, ("test error",))

        result_with_warning = result.with_warning("test warning")
        # with_warning preserves valid flag; starting from valid=True stays valid
        self.assertTrue(result_with_warning.valid)
        self.assertEqual(result_with_warning.warnings, ("test warning",))

    def test_validation_result_with_warning_still_valid(self):
        result = ValidationResult(valid=True)
        warned = result.with_warning("something")
        self.assertTrue(warned.valid)
        self.assertEqual(warned.warnings, ("something",))


class ChannelConfigValidationTest(unittest.TestCase):
    def test_valid_channel_config(self):
        config = {
            "name": "Test Channel",
            "programming": {"mode": "autonomous"},
            "music": {"genres": ["lofi", "ambient"]},
            "visual": {"theme": "rainy_city"},
            "stream": {"resolution": "1080p", "fps": 30},
            "schedule": {"timezone": "Asia/Bangkok"},
        }
        result = validate_channel_config(config)
        self.assertTrue(result.valid)
        self.assertEqual(result.errors, ())

    def test_invalid_channel_config_missing_name(self):
        config = {
            "programming": {"mode": "autonomous"},
            "music": {"genres": ["lofi"]},
            "visual": {"theme": "rainy_city"},
            "stream": {"resolution": "1080p", "fps": 30},
            "schedule": {"timezone": "Asia/Bangkok"},
        }
        result = validate_channel_config(config)
        self.assertFalse(result.valid)
        self.assertIn("channel.name must be a non-empty string", result.errors)

    def test_invalid_channel_config_bad_mode(self):
        config = {
            "name": "Test Channel",
            "programming": {"mode": "invalid_mode"},
            "music": {"genres": ["lofi"]},
            "visual": {"theme": "rainy_city"},
            "stream": {"resolution": "1080p", "fps": 30},
            "schedule": {"timezone": "Asia/Bangkok"},
        }
        result = validate_channel_config(config)
        self.assertFalse(result.valid)
        assertAnyIn("programming.mode must be one of", result.errors)

    def test_invalid_channel_config_bad_resolution(self):
        config = {
            "name": "Test Channel",
            "programming": {"mode": "autonomous"},
            "music": {"genres": ["lofi"]},
            "visual": {"theme": "rainy_city"},
            "stream": {"resolution": "4k", "fps": 30},
            "schedule": {"timezone": "Asia/Bangkok"},
        }
        result = validate_channel_config(config)
        self.assertFalse(result.valid)
        assertAnyIn("stream.resolution must be one of", result.errors)


class TrackRightsValidationTest(unittest.TestCase):
    def test_valid_track_rights(self):
        track = {
            "track_id": "track-001",
            "youtube_allowed": True,
            "commercial_allowed": True,
            "license_valid_until": None,
            "attribution_required": False,
        }
        result = validate_track_rights(track)
        self.assertTrue(result.valid)
        self.assertEqual(result.errors, ())

    def test_invalid_track_rights_missing_id(self):
        track = {
            "youtube_allowed": True,
            "commercial_allowed": True,
            "license_valid_until": None,
            "attribution_required": False,
        }
        result = validate_track_rights(track)
        self.assertFalse(result.valid)
        self.assertIn("track.track_id must be a non-empty string", result.errors)

    def test_invalid_track_rights_bad_youtube(self):
        track = {
            "track_id": "track-001",
            "youtube_allowed": "yes",  # should be bool
            "commercial_allowed": True,
            "license_valid_until": None,
            "attribution_required": False,
        }
        result = validate_track_rights(track)
        self.assertFalse(result.valid)
        self.assertIn("track.youtube_allowed must be a boolean", result.errors)


class StreamConfigValidationTest(unittest.TestCase):
    def test_valid_stream_config(self):
        config = {
            "stream_id": "str-001",
            "channel_id": "ch-001",
            "resolution": "1080p",
            "fps": 30,
            "bitrate": "4500k",
            "encoder": "libx264",
        }
        result = validate_stream_config(config)
        self.assertTrue(result.valid)
        self.assertEqual(result.errors, ())

    def test_invalid_stream_config_bad_encoder(self):
        config = {
            "stream_id": "str-001",
            "channel_id": "ch-001",
            "resolution": "1080p",
            "fps": 30,
            "bitrate": "4500k",
            "encoder": "invalid_encoder",
        }
        result = validate_stream_config(config)
        self.assertFalse(result.valid)
        assertAnyIn("stream.encoder must be one of", result.errors)

    def test_invalid_stream_config_missing_id(self):
        config = {
            "channel_id": "ch-001",
            "resolution": "1080p",
            "fps": 30,
            "bitrate": "4500k",
            "encoder": "libx264",
        }
        result = validate_stream_config(config)
        self.assertFalse(result.valid)
        self.assertIn("stream.stream_id must be a non-empty string", result.errors)


class AgentOutputValidationTest(unittest.TestCase):
    def test_valid_music_director_output(self):
        output = {
            "agent": "music_director",
            "version": "1.0",
            "status": "success",
            "plan": {
                "audio_playlist": "playlist_001",
                "visual_scene": "scene_004",
            },
            "warnings": [],
            "requires_approval": False,
        }
        result = validate_agent_output("music_director", output)
        self.assertTrue(result.valid)
        self.assertEqual(result.errors, ())

    def test_invalid_music_director_missing_plan(self):
        output = {
            "agent": "music_director",
            "version": "1.0",
            "status": "success",
            "warnings": [],
            "requires_approval": False,
        }
        result = validate_agent_output("music_director", output)
        self.assertFalse(result.valid)
        self.assertIn("music_director output missing 'plan' field", result.errors)

    def test_invalid_output_not_dict(self):
        result = validate_agent_output("test", "not a dictionary")
        self.assertFalse(result.valid)
        self.assertIn("test output must be a dictionary", result.errors)

    def test_valid_rights_validator_output(self):
        output = {
            "agent": "rights_validator",
            "version": "1.0",
            "status": "success",
            "rights": {
                "youtube_allowed": True,
                "commercial_allowed": False,
            },
            "warnings": [],
        }
        result = validate_agent_output("rights_validator", output)
        self.assertTrue(result.valid)

    def test_valid_metadata_output(self):
        output = {
            "agent": "metadata",
            "version": "1.0",
            "status": "success",
            "title": "Test Stream",
            "description": "A test description",
        }
        result = validate_agent_output("metadata", output)
        self.assertTrue(result.valid)

    def test_validate_for_production_channel_config(self):
        config = {
            "name": "Test Channel",
            "programming": {"mode": "autonomous"},
            "music": {"genres": ["lofi"]},
            "visual": {"theme": "rainy_city"},
            "stream": {"resolution": "1080p", "fps": 30},
            "schedule": {"timezone": "Asia/Bangkok"},
        }
        result = validate_for_production("channel_config", config)
        self.assertTrue(result.valid)

    def test_validate_for_production_unknown_operation(self):
        result = validate_for_production("unknown_op", {})
        self.assertFalse(result.valid)
        self.assertIn("Unknown operation type", result.errors[0])


if __name__ == "__main__":
    unittest.main()
