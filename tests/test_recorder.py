"""Tests for cross-platform FFmpeg recording commands."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.configuration import VideoAspectRatio
from scripts.device_discovery import CameraDevice, MicrophoneDevice
from scripts.recorder import (
    FFmpegRecorder,
    RecordingError,
    RecordingResult,
    build_ffmpeg_command,
    record_device_test,
    test_recording_path as device_test_recording_path,
)


class ExitedProcess:
    stdin = None

    def poll(self) -> int:
        return 1


class RecorderCommandTests(unittest.TestCase):
    def test_device_test_reports_countdown_and_completion(self) -> None:
        updates: list[int] = []
        expected = RecordingResult(Path("test.mp4"), 0.01, True, True)

        with patch("scripts.recorder.FFmpegRecorder") as recorder_type:
            recorder_type.return_value.stop.return_value = expected
            result = record_device_test(
                CameraDevice("0", "Camera", "avfoundation", 0),
                MicrophoneDevice("0", "Mic", "avfoundation"),
                duration_seconds=0.01,
                test_kind="participant",
                countdown_callback=updates.append,
            )

        self.assertIs(result, expected)
        self.assertEqual(updates[0], 1)
        self.assertEqual(updates[-1], 0)

    def test_researcher_and_participant_tests_use_separate_temporary_files(self) -> None:
        researcher_path = device_test_recording_path("researcher")
        participant_path = device_test_recording_path("participant")

        self.assertNotEqual(researcher_path, participant_path)
        self.assertEqual(researcher_path.suffix, ".mp4")
        self.assertEqual(participant_path.suffix, ".mp4")

    def test_rejects_unknown_device_test_kind(self) -> None:
        with self.assertRaises(ValueError):
            device_test_recording_path("unknown")

    def test_builds_macos_avfoundation_pair(self) -> None:
        command = build_ffmpeg_command(
            CameraDevice(
                "1",
                "Camera",
                "avfoundation",
                1,
                supported_video_sizes=((1080, 1920), (1920, 1080)),
            ),
            MicrophoneDevice("2", "Mic", "avfoundation"),
            Path("output.mp4"),
        )
        self.assertIn("avfoundation", command)
        self.assertIn("1:2", command)
        video_filter = command[command.index("-vf") + 1]
        self.assertIn("setpts=PTS-STARTPTS", video_filter)
        self.assertIn("scale=1280:720", video_filter)
        self.assertIn("pad=1280:720", video_filter)
        self.assertIn("aresample=async=1000:first_pts=0", command)
        self.assertIn("-fps_mode:v", command)
        self.assertIn("-shortest", command)
        self.assertEqual(command[command.index("-video_size") + 1], "1920x1080")
        self.assertLess(command.index("-video_size"), command.index("-i"))
        self.assertEqual(command[-1], "output.mp4")

    def test_builds_standard_and_native_aspect_ratio_filters(self) -> None:
        standard = build_ffmpeg_command(
            CameraDevice("1", "Camera", "avfoundation", 1),
            MicrophoneDevice("2", "Mic", "avfoundation"),
            "standard.mp4",
            aspect_ratio=VideoAspectRatio.STANDARD,
        )
        native = build_ffmpeg_command(
            CameraDevice("1", "Camera", "avfoundation", 1),
            MicrophoneDevice("2", "Mic", "avfoundation"),
            "native.mp4",
            aspect_ratio=VideoAspectRatio.NATIVE,
        )

        self.assertIn("scale=960:720", standard[standard.index("-vf") + 1])
        self.assertIn("pad=960:720", standard[standard.index("-vf") + 1])
        self.assertEqual(native[native.index("-vf") + 1], "setpts=PTS-STARTPTS")

    def test_builds_windows_directshow_pair(self) -> None:
        command = build_ffmpeg_command(
            CameraDevice("USB Camera", "Camera", "dshow"),
            MicrophoneDevice("USB Mic", "Mic", "dshow"),
            "output.mp4",
        )
        self.assertIn("video=USB Camera:audio=USB Mic", command)

    def test_builds_linux_separate_inputs(self) -> None:
        command = build_ffmpeg_command(
            CameraDevice("/dev/video0", "Camera", "v4l2"),
            MicrophoneDevice("alsa_input.usb", "Mic", "pulse"),
            "output.mp4",
        )
        self.assertIn("v4l2", command)
        self.assertIn("pulse", command)
        self.assertIn("alsa_input.usb", command)
        self.assertEqual(command.count("-use_wallclock_as_timestamps"), 2)
        self.assertEqual(command.count("-thread_queue_size"), 2)

    def test_rejects_fallback_device_pair(self) -> None:
        with self.assertRaises(RecordingError):
            build_ffmpeg_command(
                CameraDevice("0", "Camera", "opencv", 0),
                MicrophoneDevice("0", "Mic", "portaudio"),
                "output.mp4",
            )

    def test_failed_startup_removes_log_and_partial_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "response.mp4"

            def exited_factory(*_args: object, **_kwargs: object) -> ExitedProcess:
                output.touch()
                return ExitedProcess()

            recorder = FFmpegRecorder(
                CameraDevice("0", "Camera", "avfoundation", 0),
                MicrophoneDevice("0", "Mic", "avfoundation"),
                output,
                executable="ffmpeg",
                popen_factory=exited_factory,  # type: ignore[arg-type]
            )

            with self.assertRaises(RecordingError):
                recorder.start()

            self.assertFalse(output.exists())
            self.assertFalse(output.with_suffix(".ffmpeg.log").exists())


if __name__ == "__main__":
    unittest.main()
