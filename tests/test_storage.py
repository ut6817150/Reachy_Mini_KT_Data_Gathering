"""Tests for participant folders and durable session metadata."""

from datetime import datetime, timezone
import json
import tempfile
import unittest

from services.storage import SessionStorage, normalize_participant_id


QUESTIONS = tuple(f"Question {number}" for number in range(13))
REACHY_SETTINGS = {
    "mode": "wired",
    "wireless_host": "reachy-mini.local",
}
FIXED_TIME = datetime(2026, 7, 19, 10, 30, tzinfo=timezone.utc)


class SessionStorageTests(unittest.TestCase):
    def test_normalizes_participant_ids(self) -> None:
        self.assertEqual(
            normalize_participant_id("  Participant   one\ttrial 2  "),
            "Participant_one_trial_2",
        )
        self.assertEqual(normalize_participant_id("group/person\\1"), "group_person_1")
        with self.assertRaises(ValueError):
            normalize_participant_id("   ")

    def test_creates_designated_participant_session_and_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage = SessionStorage.create(
                temp_dir,
                "p001",
                REACHY_SETTINGS,
                QUESTIONS,
                clock=lambda: FIXED_TIME,
            )
            self.assertEqual(storage.session_dir.parent.name, "p001")
            self.assertTrue(storage.metadata_path.is_file())
            self.assertEqual(storage.recording_path(0).name, "question_00.mp4")
            payload = json.loads(storage.metadata_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["participant_id"], "p001")
            self.assertEqual(
                payload["researcher_configuration"]["camera"], "MacBook Pro Camera"
            )
            self.assertEqual(len(payload["questions"]), 13)
            self.assertEqual(payload["schema_version"], 2)
            self.assertEqual(payload["questions"][-1]["number"], 12)
            self.assertFalse(payload["questions"][0]["scored"])
            self.assertTrue(payload["questions"][1]["scored"])

    def test_updates_recording_and_finalizes_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            storage = SessionStorage.create(
                temp_dir,
                "P002",
                REACHY_SETTINGS,
                QUESTIONS,
                clock=lambda: FIXED_TIME,
            )
            recording_path = storage.session_dir / "question_00.mp4"
            storage.mark_recording_started(0)
            storage.mark_recording_complete(
                0,
                recording_path,
                12.3456,
            )
            storage.finalize()
            payload = json.loads(storage.metadata_path.read_text(encoding="utf-8"))
            self.assertTrue(payload["completed"])
            self.assertEqual(payload["questions"][0]["recording"], "question_00.mp4")
            self.assertEqual(payload["questions"][0]["duration_seconds"], 12.346)
            self.assertFalse(storage.metadata_path.with_suffix(".json.tmp").exists())


if __name__ == "__main__":
    unittest.main()
