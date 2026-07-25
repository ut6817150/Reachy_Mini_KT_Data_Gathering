"""Record synchronized camera video and microphone audio to MP4 with FFmpeg."""

import math
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from typing import Callable

CAMERA_NAME = "MacBook Pro Camera"
MICROPHONE_NAME = "MacBook Pro Microphone"


class RecordingError(RuntimeError):
    """Raised when recording cannot start or produce a valid audio/video MP4."""


def ffmpeg_path() -> str:
    executable = shutil.which("ffmpeg")
    if not executable:
        raise RecordingError("FFmpeg is not installed or is not available on PATH.")
    return executable


def build_ffmpeg_command(output_path: str | Path) -> list[str]:
    """Build the fixed MacBook camera and microphone recording command."""

    output = str(Path(output_path))
    # Cameras and microphones have independent clocks, even when FFmpeg opens
    # them through one capture backend. Normalize the video clock and let the
    # audio resampler add/drop samples when its clock drifts. This also pads any
    # short startup delay with silence instead of shifting speech against video.
    synchronized_output = [
        "-vf",
        "setpts=PTS-STARTPTS",
        "-af",
        "aresample=async=1000:first_pts=0",
        "-fps_mode:v",
        "cfr",
        "-r",
        "30",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        "-movflags",
        "+faststart",
        output,
    ]

    return [
        ffmpeg_path(),
        "-hide_banner",
        "-loglevel",
        "warning",
        "-y",
        "-f",
        "avfoundation",
        # AVFoundation otherwise defaults to 29.97 fps, which the built-in
        # camera can reject even though it supports an exact 30 fps mode.
        "-framerate",
        "30",
        "-video_size",
        "1920x1080",
        # Names are stable even when macOS changes AVFoundation indices.
        "-i",
        f"{CAMERA_NAME}:{MICROPHONE_NAME}",
        *synchronized_output,
    ]


class FFmpegRecorder:
    """Manage one FFmpeg process and finalize its MP4 gracefully."""

    def __init__(self, output_path: str | Path) -> None:
        self.output_path = Path(output_path).expanduser().resolve()
        self._process: subprocess.Popen[bytes] | None = None
        self._log_file = None
        self._log_path = self.output_path.with_suffix(".ffmpeg.log")
        self._started_at: float | None = None

    def start(self) -> None:
        if self._process is not None:
            raise RecordingError("This recorder has already been started.")
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        if self.output_path.exists():
            raise FileExistsError(
                f"Refusing to overwrite recording: {self.output_path}"
            )

        command = build_ffmpeg_command(self.output_path)
        self._log_file = self._log_path.open("wb")
        try:
            self._process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=self._log_file,
            )
        except OSError as error:
            self._close_log()
            self._log_path.unlink(missing_ok=True)
            raise RecordingError(f"Could not start FFmpeg: {error}") from error
        self._started_at = time.monotonic()

        # Give FFmpeg a moment to reject invalid devices or permissions.
        time.sleep(0.15)
        if self._process.poll() is not None:
            message = self._read_log_tail()
            self._close_log()
            self._process = None
            self.output_path.unlink(missing_ok=True)
            self._log_path.unlink(missing_ok=True)
            raise RecordingError(f"FFmpeg stopped during startup. {message}")

    def stop(self, timeout_seconds: float = 12.0) -> tuple[Path, float]:
        process = self._process
        if process is None or self._started_at is None:
            raise RecordingError("No recording is active.")

        if process.poll() is None:
            try:
                if process.stdin is not None:
                    process.stdin.write(b"q\n")
                    process.stdin.flush()
                process.wait(timeout=timeout_seconds)
            except (BrokenPipeError, subprocess.TimeoutExpired):
                self._terminate(process)

        duration = max(0.0, time.monotonic() - self._started_at)
        return_code = process.returncode
        self._process = None
        self._close_log()

        if return_code != 0:
            raise RecordingError(
                f"FFmpeg exited with status {return_code}. {self._read_log_tail()}"
            )
        if not self.output_path.is_file() or self.output_path.stat().st_size == 0:
            raise RecordingError("FFmpeg did not create a non-empty recording.")

        contains_video, contains_audio = probe_recording(self.output_path)
        if not contains_video or not contains_audio:
            missing = "video" if not contains_video else "audio"
            raise RecordingError(f"The recording is missing its {missing} stream.")
        self._log_path.unlink(missing_ok=True)
        return self.output_path, duration

    def cancel(self) -> None:
        """Stop without preserving a possibly partial output file."""

        process = self._process
        self._process = None
        if process is not None and process.poll() is None:
            self._terminate(process)
        self._close_log()
        self.output_path.unlink(missing_ok=True)
        self._log_path.unlink(missing_ok=True)

    def _close_log(self) -> None:
        if self._log_file is not None:
            self._log_file.close()
            self._log_file = None

    @staticmethod
    def _terminate(process: subprocess.Popen[bytes]) -> None:
        process.terminate()
        try:
            process.wait(timeout=3.0)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3.0)

    def _read_log_tail(self) -> str:
        try:
            text = self._log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
        return text[-1200:].strip()


def probe_recording(path: str | Path) -> tuple[bool, bool]:
    """Verify that an MP4 contains both video and audio streams."""

    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        # FFprobe is normally distributed with FFmpeg. Size verification is the
        # safest available fallback on unusual installations.
        recording = Path(path)
        exists = recording.is_file() and recording.stat().st_size > 0
        return exists, exists

    completed = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(Path(path)),
        ],
        capture_output=True,
        check=False,
        text=True,
        timeout=10.0,
    )
    if completed.returncode != 0:
        raise RecordingError(f"Could not inspect recording: {completed.stderr.strip()}")
    stream_types = set(completed.stdout.splitlines())
    return "video" in stream_types, "audio" in stream_types


def record_device_test(
    *,
    duration_seconds: float = 5.0,
    test_kind: str = "researcher",
    countdown_callback: Callable[[int], None] | None = None,
) -> Path:
    """Create a short blocking recording for device-check playback."""

    if duration_seconds <= 0:
        raise ValueError("duration_seconds must be greater than zero")
    if test_kind not in {"researcher", "participant"}:
        raise ValueError("Unknown device test kind")
    directory = Path(tempfile.gettempdir()) / "reachy-mini-participant-study"
    directory.mkdir(parents=True, exist_ok=True)
    output = directory / f"{test_kind}_device_test.mp4"
    output.unlink(missing_ok=True)
    recorder = FFmpegRecorder(output)
    try:
        recorder.start()
        deadline = time.monotonic() + duration_seconds
        last_reported: int | None = None
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            displayed = max(1, math.ceil(remaining))
            if countdown_callback is not None and displayed != last_reported:
                countdown_callback(displayed)
                last_reported = displayed
            time.sleep(min(0.1, remaining))
        if countdown_callback is not None:
            countdown_callback(0)
        path, _ = recorder.stop()
        return path
    except Exception:
        recorder.cancel()
        raise
