"""Tests for Reachy's prepared speech playback."""

from pathlib import Path
from threading import Barrier, Event, Thread
import tempfile
import unittest
from unittest.mock import patch
import wave

from services.speech import RobotSpeaker, expected_speech_assets


class FakeReachy:
    def __init__(self, barrier: Barrier) -> None:
        self.barrier = barrier
        self.played: list[Path] = []

    def play_sound(self, path: str | Path) -> None:
        self.played.append(Path(path))
        self.barrier.wait(timeout=2.0)


class CancellableReachy:
    def __init__(self) -> None:
        self.played: list[Path] = []
        self.sound_started = Event()
        self.stopped = False

    def play_sound(self, path: str | Path) -> None:
        self.played.append(Path(path))
        self.sound_started.set()

    def stop_sound(self) -> None:
        self.stopped = True


class RobotSpeakerTests(unittest.TestCase):
    def test_speech_assets_use_question_zero_through_twelve(self) -> None:
        questions = tuple(f"Question {number}" for number in range(13))
        assets = expected_speech_assets(questions)
        question_files = [name for name in assets if name.startswith("question_")]
        self.assertEqual(question_files[0], "question_00.wav")
        self.assertEqual(question_files[-1], "question_12.wav")
        self.assertEqual(len(question_files), 13)

    def test_play_during_starts_audio_and_movement_concurrently(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            audio_path = Path(temp_dir) / "message.wav"
            with wave.open(str(audio_path), "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(24_000)
                audio.writeframes(b"")
            barrier = Barrier(2)
            reachy = FakeReachy(barrier)
            speaker = RobotSpeaker()
            movement_started = False

            def movement() -> None:
                nonlocal movement_started
                movement_started = True
                barrier.wait(timeout=2.0)

            with patch("services.speech._wav_duration", return_value=0.0):
                result = speaker.play_during(  # type: ignore[arg-type]
                    reachy,
                    audio_path,
                    movement,
                )

            self.assertTrue(movement_started)
            self.assertEqual(reachy.played, [audio_path.resolve()])
            self.assertEqual(result, audio_path.resolve())

    def test_stop_interrupts_active_voiceover(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            audio_path = Path(temp_dir) / "question.wav"
            audio_path.touch()
            reachy = CancellableReachy()
            speaker = RobotSpeaker()

            with patch("services.speech._wav_duration", return_value=30.0):
                worker = Thread(
                    target=speaker.play,
                    args=(reachy, audio_path),  # type: ignore[arg-type]
                )
                worker.start()
                self.assertTrue(reachy.sound_started.wait(timeout=1.0))
                self.assertTrue(speaker.stop(reachy))  # type: ignore[arg-type]
                worker.join(timeout=1.0)

            self.assertFalse(worker.is_alive())
            self.assertTrue(reachy.stopped)
            self.assertEqual(reachy.played, [audio_path.resolve()])

    def test_stop_returns_false_without_active_voiceover(self) -> None:
        speaker = RobotSpeaker()
        self.assertFalse(speaker.stop(CancellableReachy()))  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
