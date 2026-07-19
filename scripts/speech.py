"""Generate local speech audio and play it through Reachy Mini."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
from pathlib import Path
import platform
import shutil
import subprocess
from threading import Event, Lock
from typing import Callable
import wave

from scripts.reachy_controller import ReachyController
from scripts.recorder import ffmpeg_path


class SpeechError(RuntimeError):
    """Raised when local text-to-speech generation fails."""


class SystemSpeechSynthesizer:
    """Use macOS ``say``, Windows System.Speech, or Linux ``espeak``."""

    def __init__(self, cache_dir: str | Path = ".cache/speech") -> None:
        self.cache_dir = Path(cache_dir).expanduser().resolve()

    def synthesize(self, text: str) -> Path:
        normalized = " ".join(text.split())
        if not normalized:
            raise ValueError("Speech text cannot be empty")
        if len(normalized) > 2000:
            raise ValueError("Speech text is too long")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:20]
        output = self.cache_dir / f"{digest}.wav"
        if output.is_file() and output.stat().st_size > 0:
            return output

        system = platform.system().lower()
        if system == "darwin":
            self._synthesize_macos(normalized, output)
        elif system == "windows":
            self._synthesize_windows(normalized, output)
        elif system == "linux":
            self._synthesize_linux(normalized, output)
        else:
            raise SpeechError(f"System text-to-speech is not supported on {platform.system()}.")
        if not output.is_file() or output.stat().st_size == 0:
            raise SpeechError("Text-to-speech did not create an audio file.")
        return output

    def _synthesize_macos(self, text: str, output: Path) -> None:
        say = shutil.which("say")
        if not say:
            raise SpeechError("The macOS 'say' command is unavailable.")
        intermediate = output.with_suffix(".aiff")
        completed = subprocess.run(
            [say, "-o", str(intermediate), text],
            capture_output=True,
            check=False,
            text=True,
            timeout=60.0,
        )
        if completed.returncode != 0:
            raise SpeechError(completed.stderr.strip() or "macOS speech synthesis failed.")
        try:
            self._convert_to_wav(intermediate, output)
        finally:
            intermediate.unlink(missing_ok=True)

    def _synthesize_windows(self, text: str, output: Path) -> None:
        powershell = shutil.which("powershell") or shutil.which("pwsh")
        if not powershell:
            raise SpeechError("PowerShell is unavailable for Windows speech synthesis.")
        escaped_text = text.replace("'", "''")
        escaped_output = str(output).replace("'", "''")
        script = (
            "Add-Type -AssemblyName System.Speech; "
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            f"$s.SetOutputToWaveFile('{escaped_output}'); "
            f"$s.Speak('{escaped_text}'); $s.Dispose();"
        )
        completed = subprocess.run(
            [powershell, "-NoProfile", "-Command", script],
            capture_output=True,
            check=False,
            text=True,
            timeout=60.0,
        )
        if completed.returncode != 0:
            raise SpeechError(completed.stderr.strip() or "Windows speech synthesis failed.")

    def _synthesize_linux(self, text: str, output: Path) -> None:
        espeak = shutil.which("espeak") or shutil.which("espeak-ng")
        if not espeak:
            raise SpeechError("Install espeak or espeak-ng for Linux speech synthesis.")
        completed = subprocess.run(
            [espeak, "-w", str(output), text],
            capture_output=True,
            check=False,
            text=True,
            timeout=60.0,
        )
        if completed.returncode != 0:
            raise SpeechError(completed.stderr.strip() or "Linux speech synthesis failed.")

    @staticmethod
    def _convert_to_wav(source: Path, output: Path) -> None:
        completed = subprocess.run(
            [
                ffmpeg_path(),
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(source),
                "-ac",
                "1",
                "-ar",
                "24000",
                str(output),
            ],
            capture_output=True,
            check=False,
            text=True,
            timeout=60.0,
        )
        if completed.returncode != 0:
            raise SpeechError(completed.stderr.strip() or "Audio conversion failed.")


class RobotSpeaker:
    """Synthesize text locally, play it on Reachy, and wait for completion."""

    def __init__(self, synthesizer: SystemSpeechSynthesizer | None = None) -> None:
        self.synthesizer = synthesizer or SystemSpeechSynthesizer()
        self._playback_lock = Lock()
        self._active_cancel_event: Event | None = None

    def speak(self, reachy: ReachyController, text: str) -> Path:
        cancel_event = Event()
        self._set_active_playback(cancel_event)
        try:
            audio_path = self.synthesizer.synthesize(text)
            return self._play_prepared(reachy, audio_path, cancel_event)
        finally:
            self._clear_active_playback(cancel_event)

    def play_prepared(self, reachy: ReachyController, audio_path: str | Path) -> Path:
        """Play an already-generated speech file and wait for it to finish."""

        cancel_event = Event()
        self._set_active_playback(cancel_event)
        try:
            return self._play_prepared(reachy, audio_path, cancel_event)
        finally:
            self._clear_active_playback(cancel_event)

    def stop(self, reachy: ReachyController) -> bool:
        """Interrupt the current speech wait and stop Reachy's active audio."""

        with self._playback_lock:
            cancel_event = self._active_cancel_event
        if cancel_event is None:
            return False
        cancel_event.set()
        reachy.stop_sound()
        return True

    def _play_prepared(
        self,
        reachy: ReachyController,
        audio_path: str | Path,
        cancel_event: Event,
    ) -> Path:
        resolved_path = Path(audio_path).expanduser().resolve()
        if not cancel_event.is_set():
            reachy.play_sound(resolved_path)
            cancel_event.wait(_wav_duration(resolved_path) + 0.15)
        return resolved_path

    def _set_active_playback(self, cancel_event: Event) -> None:
        with self._playback_lock:
            self._active_cancel_event = cancel_event

    def _clear_active_playback(self, cancel_event: Event) -> None:
        with self._playback_lock:
            if self._active_cancel_event is cancel_event:
                self._active_cancel_event = None

    def speak_during(
        self,
        reachy: ReachyController,
        text: str,
        action: Callable[[], None],
    ) -> Path:
        """Start prepared speech and a robot movement at approximately the same time."""

        audio_path = self.synthesizer.synthesize(text)
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="reachy-synced") as executor:
            movement = executor.submit(action)
            speech = executor.submit(self.play_prepared, reachy, audio_path)
            movement.result()
            speech.result()
        return audio_path


def _wav_duration(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as audio:
            frame_rate = audio.getframerate()
            return audio.getnframes() / frame_rate if frame_rate else 0.0
    except (OSError, wave.Error):
        return 0.0
