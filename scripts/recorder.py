"""Record synchronized camera video and microphone audio to MP4 with FFmpeg."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from typing import BinaryIO, Callable, Sequence

from scripts.configuration import VideoAspectRatio
from scripts.device_discovery import CameraDevice, MicrophoneDevice


class RecordingError(RuntimeError):
    """Raised when recording cannot start or produce a valid audio/video MP4."""


@dataclass(frozen=True, slots=True)
class RecordingResult:
    path: Path
    duration_seconds: float
    contains_video: bool
    contains_audio: bool


PopenFactory = Callable[..., subprocess.Popen[bytes]]


def ffmpeg_path() -> str:
    executable = shutil.which("ffmpeg")
    if not executable:
        raise RecordingError("FFmpeg is not installed or is not available on PATH.")
    return executable


def build_ffmpeg_command(
    camera: CameraDevice,
    microphone: MicrophoneDevice,
    output_path: str | Path,
    *,
    executable: str = "ffmpeg",
    aspect_ratio: VideoAspectRatio = VideoAspectRatio.WIDESCREEN,
) -> list[str]:
    """Build a shell-free FFmpeg command for a compatible device pair."""

    output = str(Path(output_path))
    # Cameras and microphones have independent clocks, even when FFmpeg opens
    # them through one capture backend. Normalize the video clock and let the
    # audio resampler add/drop samples when its clock drifts. This also pads any
    # short startup delay with silence instead of shifting speech against video.
    video_filter = "setpts=PTS-STARTPTS"
    if aspect_ratio is VideoAspectRatio.WIDESCREEN:
        video_filter += (
            ",scale=1280:720:force_original_aspect_ratio=decrease"
            ",pad=1280:720:(ow-iw)/2:(oh-ih)/2"
        )
    elif aspect_ratio is VideoAspectRatio.STANDARD:
        video_filter += (
            ",scale=960:720:force_original_aspect_ratio=decrease"
            ",pad=960:720:(ow-iw)/2:(oh-ih)/2"
        )

    synchronized_output = [
        "-vf",
        video_filter,
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

    if camera.backend == "avfoundation" and microphone.backend == "avfoundation":
        avfoundation_input = [
            executable,
            "-hide_banner",
            "-loglevel",
            "warning",
            "-y",
            "-f",
            "avfoundation",
            "-framerate",
            "30",
        ]
        capture_size = camera.preferred_capture_size
        if capture_size is not None:
            avfoundation_input.extend(
                ["-video_size", f"{capture_size[0]}x{capture_size[1]}"]
            )
        return [
            *avfoundation_input,
            "-i",
            f"{camera.identifier}:{microphone.identifier}",
            *synchronized_output,
        ]

    if camera.backend == "dshow" and microphone.backend == "dshow":
        return [
            executable,
            "-hide_banner",
            "-loglevel",
            "warning",
            "-y",
            "-f",
            "dshow",
            "-i",
            f"video={camera.identifier}:audio={microphone.identifier}",
            *synchronized_output,
        ]

    if camera.backend == "v4l2" and microphone.backend == "pulse":
        return [
            executable,
            "-hide_banner",
            "-loglevel",
            "warning",
            "-y",
            "-thread_queue_size",
            "1024",
            "-use_wallclock_as_timestamps",
            "1",
            "-f",
            "v4l2",
            "-framerate",
            "30",
            "-i",
            camera.identifier,
            "-thread_queue_size",
            "1024",
            "-use_wallclock_as_timestamps",
            "1",
            "-f",
            "pulse",
            "-i",
            microphone.identifier,
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            *synchronized_output,
        ]

    raise RecordingError(
        "The selected camera and microphone are fallback devices and cannot yet be "
        "passed to FFmpeg together. Install FFmpeg, refresh devices, and select the "
        "FFmpeg-discovered entries."
    )


class FFmpegRecorder:
    """Manage one FFmpeg process and finalize its MP4 gracefully."""

    def __init__(
        self,
        camera: CameraDevice,
        microphone: MicrophoneDevice,
        output_path: str | Path,
        *,
        executable: str | None = None,
        popen_factory: PopenFactory = subprocess.Popen,
        aspect_ratio: VideoAspectRatio = VideoAspectRatio.WIDESCREEN,
    ) -> None:
        self.camera = camera
        self.microphone = microphone
        self.output_path = Path(output_path).expanduser().resolve()
        self.executable = executable or ffmpeg_path()
        self.aspect_ratio = aspect_ratio
        self._popen_factory = popen_factory
        self._process: subprocess.Popen[bytes] | None = None
        self._log_file: BinaryIO | None = None
        self._log_path = self.output_path.with_suffix(".ffmpeg.log")
        self._started_at: float | None = None

    @property
    def is_recording(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def start(self) -> None:
        if self._process is not None:
            raise RecordingError("This recorder has already been started.")
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        if self.output_path.exists():
            raise FileExistsError(f"Refusing to overwrite recording: {self.output_path}")

        command = build_ffmpeg_command(
            self.camera,
            self.microphone,
            self.output_path,
            executable=self.executable,
            aspect_ratio=self.aspect_ratio,
        )
        self._log_file = self._log_path.open("wb")
        try:
            self._process = self._popen_factory(
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

    def stop(self, timeout_seconds: float = 12.0) -> RecordingResult:
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
                process.terminate()
                try:
                    process.wait(timeout=3.0)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3.0)

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
        return RecordingResult(
            path=self.output_path,
            duration_seconds=duration,
            contains_video=contains_video,
            contains_audio=contains_audio,
        )

    def cancel(self) -> None:
        """Stop without preserving a possibly partial output file."""

        process = self._process
        self._process = None
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3.0)
        self._close_log()
        self.output_path.unlink(missing_ok=True)
        self._log_path.unlink(missing_ok=True)

    def _close_log(self) -> None:
        if self._log_file is not None:
            self._log_file.close()
            self._log_file = None

    def _read_log_tail(self, character_limit: int = 1200) -> str:
        try:
            text = self._log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
        return text[-character_limit:].strip()


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
            "json",
            str(Path(path)),
        ],
        capture_output=True,
        check=False,
        text=True,
        timeout=10.0,
    )
    if completed.returncode != 0:
        raise RecordingError(f"Could not inspect recording: {completed.stderr.strip()}")
    try:
        payload = json.loads(completed.stdout)
        stream_types = {stream.get("codec_type") for stream in payload.get("streams", [])}
    except (json.JSONDecodeError, AttributeError) as error:
        raise RecordingError("FFprobe returned invalid stream information.") from error
    return "video" in stream_types, "audio" in stream_types


def test_recording_path(test_kind: str = "researcher") -> Path:
    """Return a stable temporary path outside participant recordings."""

    if test_kind not in {"researcher", "participant"}:
        raise ValueError("test_kind must be 'researcher' or 'participant'")

    directory = Path(tempfile.gettempdir()) / "reachy-mini-participant-study"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{test_kind}_device_test.mp4"


def record_device_test(
    camera: CameraDevice,
    microphone: MicrophoneDevice,
    *,
    duration_seconds: float = 5.0,
    test_kind: str = "researcher",
    countdown_callback: Callable[[int], None] | None = None,
    aspect_ratio: VideoAspectRatio = VideoAspectRatio.WIDESCREEN,
) -> RecordingResult:
    """Create a short blocking recording for device-check playback."""

    if duration_seconds <= 0:
        raise ValueError("duration_seconds must be greater than zero")
    output = test_recording_path(test_kind)
    output.unlink(missing_ok=True)
    recorder = FFmpegRecorder(
        camera,
        microphone,
        output,
        aspect_ratio=aspect_ratio,
    )
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
        return recorder.stop()
    except Exception:
        recorder.cancel()
        raise
