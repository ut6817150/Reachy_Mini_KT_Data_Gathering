"""Prepared speech assets and cancellable Reachy playback."""

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from threading import Event, Lock
from typing import Callable
import wave

from services.reachy_controller import ReachyController


SPEECH_SET_NAME = "Qwen3-TTS-Aiden"
SPEECH_DIR = (
    Path(__file__).resolve().parents[1] / "assets" / "speech" / SPEECH_SET_NAME
)
MANIFEST_PATH = SPEECH_DIR / "manifest.json"

WELCOME_MESSAGE = (
    "Welcome, and thank you for taking part in this study. You will first complete "
    "one unscored practice question, followed by 12 study questions. For every "
    "question, please answer aloud and explain how you arrived at your answer. "
    "Include any numerical calculations you use, and say each step out loud."
)

FIXED_SPEECH = {
    "speaker_test.wav": "Reachy Mini connection test successful.",
    "welcome.wav": WELCOME_MESSAGE,
    "next_question.wav": "Thank you. Let us continue to the next question.",
    "final_question.wav": "Thank you. The next question is the final question.",
    "completion.wav": "Thank you for participating. The interaction is now complete.",
}


class SpeechError(RuntimeError):
    pass


def speech_file(filename: str) -> Path:
    return SPEECH_DIR / filename


def expected_speech_assets(questions: tuple[str, ...]) -> dict[str, str]:
    assets = dict(FIXED_SPEECH)
    assets.update(
        {
            f"question_{number:02d}.wav": text
            for number, text in enumerate(questions)
        }
    )
    return assets


def validate_speech_assets(questions: tuple[str, ...]) -> None:
    """Ensure prepared audio exists and still matches the current question text."""

    expected = expected_speech_assets(questions)
    try:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        manifest = None
    missing = [
        filename
        for filename in expected
        if not speech_file(filename).is_file() or not speech_file(filename).stat().st_size
    ]
    if manifest != expected or missing:
        raise SpeechError(
            "Prepared speech is missing or out of date. Run "
            "'extraction/generate_aiden_speech.ipynb' before starting the study."
        )


class RobotSpeaker:
    """Play prepared speech and allow active voiceovers to be skipped."""

    def __init__(self) -> None:
        self._playback_lock = Lock()
        self._active_cancel_event: Event | None = None

    def play(self, reachy: ReachyController, audio_path: str | Path) -> Path:
        audio_path = Path(audio_path).expanduser().resolve()
        cancel_event = Event()
        with self._playback_lock:
            self._active_cancel_event = cancel_event
        try:
            reachy.play_sound(audio_path)
            cancel_event.wait(_wav_duration(audio_path) + 0.15)
            return audio_path
        finally:
            with self._playback_lock:
                if self._active_cancel_event is cancel_event:
                    self._active_cancel_event = None

    def stop(self, reachy: ReachyController) -> bool:
        with self._playback_lock:
            cancel_event = self._active_cancel_event
        if cancel_event is None:
            return False
        cancel_event.set()
        reachy.stop_sound()
        return True

    def play_during(
        self,
        reachy: ReachyController,
        audio_path: str | Path,
        action: Callable[[], None],
    ) -> Path:
        """Start prepared speech and a movement at approximately the same time."""

        with ThreadPoolExecutor(max_workers=2) as executor:
            movement = executor.submit(action)
            speech = executor.submit(self.play, reachy, audio_path)
            movement.result()
            return speech.result()


def _wav_duration(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as audio:
            frame_rate = audio.getframerate()
            return audio.getnframes() / frame_rate if frame_rate else 0.0
    except (OSError, wave.Error):
        return 0.0
