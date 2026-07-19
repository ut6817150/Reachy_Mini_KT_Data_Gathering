"""Tests for Reachy's local speech orchestration."""

from pathlib import Path
from threading import Barrier, Event, Thread
import tempfile
import unittest
from unittest.mock import patch
import wave

from scripts.speech import RobotSpeaker


class FakeSynthesizer:
    def __init__(self, output: Path) -> None:
        self.output = output
        self.prepared = False

    def synthesize(self, _text: str) -> Path:
        self.prepared = True
        return self.output


class FakeReachy:
    def __init__(self, synthesizer: FakeSynthesizer, barrier: Barrier) -> None:
        self.synthesizer = synthesizer
        self.barrier = barrier
        self.played: list[Path] = []

    def play_sound(self, path: str | Path) -> None:
        self.assert_prepared()
        self.played.append(Path(path))
        self.barrier.wait(timeout=2.0)

    def assert_prepared(self) -> None:
        if not self.synthesizer.prepared:
            raise AssertionError("Speech must be generated before synchronized playback")


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
    def test_speak_during_starts_prepared_audio_and_movement_concurrently(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            audio_path = Path(temp_dir) / "message.wav"
            with wave.open(str(audio_path), "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(24_000)
                audio.writeframes(b"")
            barrier = Barrier(2)
            synthesizer = FakeSynthesizer(audio_path)
            reachy = FakeReachy(synthesizer, barrier)
            speaker = RobotSpeaker(synthesizer=synthesizer)  # type: ignore[arg-type]
            movement_started = False

            def movement() -> None:
                nonlocal movement_started
                reachy.assert_prepared()
                movement_started = True
                barrier.wait(timeout=2.0)

            with patch("scripts.speech._wav_duration", return_value=0.0):
                result = speaker.speak_during(  # type: ignore[arg-type]
                    reachy,
                    "Let us continue.",
                    movement,
                )

            self.assertTrue(movement_started)
            self.assertEqual(reachy.played, [audio_path.resolve()])
            self.assertEqual(result, audio_path)

    def test_stop_interrupts_active_voiceover(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            audio_path = Path(temp_dir) / "question.wav"
            audio_path.touch()
            synthesizer = FakeSynthesizer(audio_path)
            reachy = CancellableReachy()
            speaker = RobotSpeaker(synthesizer=synthesizer)  # type: ignore[arg-type]

            with patch("scripts.speech._wav_duration", return_value=30.0):
                worker = Thread(
                    target=speaker.speak,
                    args=(reachy, "A long question"),  # type: ignore[arg-type]
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
