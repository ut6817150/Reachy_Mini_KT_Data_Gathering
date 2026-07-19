"""Tests for participant folders and durable session metadata."""

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from scripts.configuration import (
    ParticipantConfiguration,
    ResearcherConfiguration,
    VideoAspectRatio,
)
from scripts.device_discovery import CameraDevice, MicrophoneDevice
from scripts.question_loader import Question
from scripts.reachy_controller import ReachyConnectionConfig
from scripts.recorder import RecordingResult
from scripts.storage import SessionStorage


CAMERA = CameraDevice("0", "Camera", "avfoundation", 0)
MICROPHONE = MicrophoneDevice("1", "Mic", "avfoundation")
QUESTIONS = tuple(Question(number, f"Question {number}") for number in range(1, 11))
FIXED_TIME = datetime(2026, 7, 19, 10, 30, tzinfo=timezone.utc)


def researcher_configuration() -> ResearcherConfiguration:
    return ResearcherConfiguration(
        reachy=ReachyConnectionConfig(),
        cameras=(CAMERA,),
        microphones=(MICROPHONE,),
        default_camera=CAMERA,
        default_microphone=MICROPHONE,
    )


class SessionStorageTests(unittest.TestCase):
    def test_creates_designated_participant_session_and_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage = SessionStorage.create(
                temp_dir,
                researcher_configuration(),
                ParticipantConfiguration("p001", CAMERA, MICROPHONE),
                QUESTIONS,
                clock=lambda: FIXED_TIME,
            )

            self.assertEqual(storage.session_dir.parent.name, "P001")
            self.assertTrue(storage.metadata_path.is_file())
            self.assertEqual(storage.recording_path(1).name, "question_01.mp4")
            payload = json.loads(storage.metadata_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["participant_id"], "P001")
            self.assertEqual(
                payload["researcher_configuration"]["video_aspect_ratio"],
                VideoAspectRatio.WIDESCREEN.value,
            )
            self.assertEqual(len(payload["questions"]), 10)

    def test_updates_recording_and_finalizes_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage = SessionStorage.create(
                temp_dir,
                researcher_configuration(),
                ParticipantConfiguration("P002", CAMERA, MICROPHONE),
                QUESTIONS,
                clock=lambda: FIXED_TIME,
            )
            recording_path = storage.session_dir / "question_01.mp4"
            storage.mark_recording_started(1)
            storage.mark_recording_complete(
                1,
                RecordingResult(recording_path, 12.3456, True, True),
            )
            storage.finalize()

            payload = json.loads(storage.metadata_path.read_text(encoding="utf-8"))
            self.assertTrue(payload["completed"])
            self.assertEqual(payload["questions"][0]["recording"], "question_01.mp4")
            self.assertEqual(payload["questions"][0]["duration_seconds"], 12.346)
            self.assertFalse(storage.metadata_path.with_suffix(".json.tmp").exists())


if __name__ == "__main__":
    unittest.main()
