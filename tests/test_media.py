"""Media pipeline tests for zMusic."""

import unittest

from scripts.config import StreamConfig
from scripts.media import (
    PRESETS,
    FFmpegCommand,
    StreamConfigOverride,
    build_playlist_command,
    build_rtmp_output_command,
    check_ffmpeg_available,
    run_ffmpeg,
    validate_preset,
)


class StreamPresetTest(unittest.TestCase):
    def test_presets_defined(self):
        self.assertIn("youtube_1080p", PRESETS)
        self.assertIn("youtube_720p", PRESETS)

    def test_youtube_1080p_values(self):
        preset = PRESETS["youtube_1080p"]
        self.assertEqual(preset.width, 1920)
        self.assertEqual(preset.height, 1080)
        self.assertEqual(preset.fps, 30)
        self.assertEqual(preset.video_bitrate, "4500k")
        self.assertEqual(preset.audio_bitrate, "160k")

    def test_youtube_720p_values(self):
        preset = PRESETS["youtube_720p"]
        self.assertEqual(preset.width, 1280)
        self.assertEqual(preset.height, 720)
        self.assertEqual(preset.fps, 30)
        self.assertEqual(preset.video_bitrate, "2500k")
        self.assertEqual(preset.audio_bitrate, "128k")

    def test_validate_preset_valid(self):
        preset = validate_preset("youtube_1080p")
        self.assertEqual(preset.name, "youtube_1080p")

    def test_validate_preset_invalid(self):
        with self.assertRaises(ValueError):
            validate_preset("nonexistent")


class StreamConfigOverrideTest(unittest.TestCase):
    def test_default_override(self):
        override = StreamConfigOverride()
        config = StreamConfig()
        preset = override.resolved(config)
        self.assertEqual(preset.name, "youtube_1080p")
        self.assertEqual(preset.width, 1920)

    def test_custom_values(self):
        override = StreamConfigOverride(
            preset="youtube_720p",
            width=640,
            height=360,
            fps=24,
        )
        config = StreamConfig()
        preset = override.resolved(config)
        self.assertEqual(preset.name, "youtube_720p")
        self.assertEqual(preset.width, 640)
        self.assertEqual(preset.height, 360)
        self.assertEqual(preset.fps, 24)

    def test_unknown_preset(self):
        override = StreamConfigOverride(preset="nonexistent")
        config = StreamConfig()
        with self.assertRaises(ValueError):
            override.resolved(config)


class FFmpegCommandTest(unittest.TestCase):
    def test_build_rtmp_command(self):
        cmd = build_rtmp_output_command(
            input_file="/tmp/test.mp4",
            rtmp_url="rtmp://localhost:1935/live",
            stream_key="test-key",
            preset_name="youtube_1080p",
        )
        args = cmd.build()
        self.assertEqual(args[0], "ffmpeg")
        self.assertIn("-re", args)
        self.assertIn("-stream_loop", args)
        self.assertIn("-1", args)
        self.assertIn("/tmp/test.mp4", args)
        self.assertIn("rtmp://localhost:1935/live/test-key", args)
        self.assertIn("-c:v", args)
        self.assertIn("libx264", args)

    def test_build_rtmp_command_720p(self):
        cmd = build_rtmp_output_command(
            input_file="/tmp/test.mp4",
            rtmp_url="rtmp://localhost:1935/live",
            stream_key="",
            preset_name="youtube_720p",
        )
        args = cmd.build()
        # Should contain 720p scale
        self.assertIn("scale=1280:720", args)

    def test_build_playlist_command(self):
        cmd, concat_path, concat_list = build_playlist_command(
            input_files=["/tmp/a.mp4", "/tmp/b.mp4"],
            output_path="/tmp/output.mp4",
        )
        args = cmd.build()
        self.assertIn("-f", args)
        self.assertIn("concat", args)
        self.assertEqual(concat_path, "/tmp/zmusic_concat_list.txt")
        self.assertIn("file '/tmp/a.mp4'", concat_list)
        self.assertIn("file '/tmp/b.mp4'", concat_list)

    def test_unsafe_input_path_rejected(self):
        cmd = FFmpegCommand()
        with self.assertRaises(ValueError):
            cmd.add_input("/tmp/test; rm -rf /")

    def test_unsafe_output_path_rejected(self):
        cmd = FFmpegCommand()
        with self.assertRaises(ValueError):
            cmd.add_output("/tmp/test | sh")

    def test_command_is_list_not_shell(self):
        cmd = build_rtmp_output_command(
            input_file="/tmp/test.mp4",
            rtmp_url="rtmp://localhost:1935/live",
            stream_key="key",
        )
        args = cmd.build()
        self.assertIsInstance(args, list)
        self.assertTrue(all(isinstance(a, str) for a in args))


class RunFFmpegTest(unittest.TestCase):
    def test_check_ffmpeg_available(self):
        # FFmpeg should be available in this environment
        self.assertTrue(check_ffmpeg_available())

    def test_run_ffmpeg_invalid_command(self):
        cmd = FFmpegCommand()
        cmd.add_input("/tmp/nonexistent_file_for_test.mp4")
        cmd.add_output("/tmp/nonexistent_output.mp4")
        result = run_ffmpeg(cmd, timeout=10)
        # FFmpeg should fail because input doesn't exist
        self.assertFalse(result["success"])
        self.assertNotEqual(result["returncode"], 0)


if __name__ == "__main__":
    unittest.main()
