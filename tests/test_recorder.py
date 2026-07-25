"""Tests for the fixed MacBook FFmpeg recorder."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from services.recorder import (
    CAMERA_NAME,
    FFmpegRecorder,
    MICROPHONE_NAME,
    RecordingError,
    build_ffmpeg_command,
    record_device_test,
)


class ExitedProcess:
    stdin = None

    def poll(self) -> int:
        return 1


class RecorderCommandTests(unittest.TestCase):
    def test_device_test_reports_countdown_and_completion(self) -> None:
        updates: list[int] = []
        expected_path = Path("test.mp4")
        with patch("services.recorder.FFmpegRecorder") as recorder_type:
            recorder_type.return_value.stop.return_value = (expected_path, 0.01)
            result = record_device_test(
                duration_seconds=0.01,
                test_kind="participant",
                countdown_callback=updates.append,
            )
        self.assertIs(result, expected_path)
        self.assertEqual(updates[0], 1)
        self.assertEqual(updates[-1], 0)

    def test_rejects_unknown_device_test_kind(self) -> None:
        with self.assertRaises(ValueError):
            record_device_test(test_kind="unknown")

    def test_command_uses_named_devices_and_landscape_input_mode(self) -> None:
        with patch("services.recorder.ffmpeg_path", return_value="ffmpeg"):
            command = build_ffmpeg_command(Path("output.mp4"))
        self.assertIn(f"{CAMERA_NAME}:{MICROPHONE_NAME}", command)
        input_index = command.index("-i")
        framerate_index = command.index("-framerate")
        self.assertEqual(command[framerate_index + 1], "30")
        self.assertLess(framerate_index, input_index)
        size_index = command.index("-video_size")
        self.assertEqual(command[size_index + 1], "1920x1080")
        self.assertLess(size_index, input_index)
        self.assertEqual(command[command.index("-vf") + 1], "setpts=PTS-STARTPTS")
        self.assertEqual(command[-1], "output.mp4")

    def test_failed_startup_removes_log_and_partial_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "response.mp4"

            def exited_factory(*_args: object, **_kwargs: object) -> ExitedProcess:
                output.touch()
                return ExitedProcess()

            recorder = FFmpegRecorder(output)
            with (
                patch("services.recorder.ffmpeg_path", return_value="ffmpeg"),
                patch("services.recorder.subprocess.Popen", side_effect=exited_factory),
            ):
                with self.assertRaises(RecordingError):
                    recorder.start()
            self.assertFalse(output.exists())
            self.assertFalse(output.with_suffix(".ffmpeg.log").exists())


if __name__ == "__main__":
    unittest.main()
