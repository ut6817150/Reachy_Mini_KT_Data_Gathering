"""Discover cameras and microphones available to the study application.

The recorder will use FFmpeg, so this module prefers identifiers reported by
FFmpeg itself. Platform fallbacks keep the start page usable when FFmpeg is not
installed yet or a host does not expose its devices through FFmpeg.

Run ``python -m scripts.device_discovery`` to print the detected devices as
JSON. Discovery never raises for an unavailable optional dependency; problems
are returned in ``DeviceCatalog.warnings`` for the Streamlit UI to display.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, replace
import json
from pathlib import Path
import platform
import re
import shutil
import subprocess
from typing import Any, Sequence


@dataclass(frozen=True, slots=True)
class CameraDevice:
    """A camera source that can be shown in the participant setup UI."""

    identifier: str
    name: str
    backend: str
    opencv_index: int | None = None
    supported_video_sizes: tuple[tuple[int, int], ...] = ()

    @property
    def label(self) -> str:
        """Human-readable dropdown label."""

        return self.name

    @property
    def preferred_capture_size(self) -> tuple[int, int] | None:
        """Choose a supported landscape mode shared by preview and recording."""

        landscape_sizes = tuple(
            size for size in self.supported_video_sizes if size[0] >= size[1]
        )
        for preferred in ((1920, 1080), (1280, 720)):
            if preferred in landscape_sizes:
                return preferred
        if landscape_sizes:
            return max(landscape_sizes, key=lambda size: size[0] * size[1])
        return None


@dataclass(frozen=True, slots=True)
class MicrophoneDevice:
    """A microphone source that can be shown in the participant setup UI."""

    identifier: str
    name: str
    backend: str
    max_input_channels: int | None = None
    default_sample_rate: float | None = None
    is_default: bool = False

    @property
    def label(self) -> str:
        """Human-readable dropdown label."""

        suffix = " (default)" if self.is_default else ""
        return f"{self.name}{suffix}"


@dataclass(frozen=True, slots=True)
class DeviceCatalog:
    """Device-discovery result, including non-fatal diagnostic warnings."""

    cameras: tuple[CameraDevice, ...]
    microphones: tuple[MicrophoneDevice, ...]
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""

        return {
            "cameras": [asdict(device) for device in self.cameras],
            "microphones": [asdict(device) for device in self.microphones],
            "warnings": list(self.warnings),
        }


def _run_listing_command(command: Sequence[str], timeout: float = 8.0) -> str:
    """Run a device-listing command and return its combined output.

    FFmpeg intentionally exits with a non-zero status after listing devices, so
    the return code is not treated as an error.
    """

    completed = subprocess.run(
        list(command),
        capture_output=True,
        check=False,
        text=True,
        timeout=timeout,
    )
    return "\n".join(part for part in (completed.stdout, completed.stderr) if part)


def _parse_avfoundation_devices(
    output: str,
) -> tuple[list[CameraDevice], list[MicrophoneDevice]]:
    """Parse ``ffmpeg -f avfoundation -list_devices true`` output."""

    cameras: list[CameraDevice] = []
    microphones: list[MicrophoneDevice] = []
    section: str | None = None

    for raw_line in output.splitlines():
        line = raw_line.strip()
        if "AVFoundation video devices:" in line:
            section = "video"
            continue
        if "AVFoundation audio devices:" in line:
            section = "audio"
            continue

        match = re.search(r"\[(\d+)\]\s+(.+?)\s*$", line)
        if not match or section is None:
            continue

        identifier, name = match.groups()
        if section == "video":
            # AVFoundation also reports desktop capture sources. They should not
            # appear in a camera-only participant dropdown.
            if re.search(r"(?:capture\s+screen|screen\s+capture)", name, re.IGNORECASE):
                continue
            cameras.append(
                CameraDevice(
                    identifier=identifier,
                    name=name,
                    backend="avfoundation",
                    opencv_index=int(identifier),
                )
            )
        else:
            microphones.append(
                MicrophoneDevice(
                    identifier=identifier,
                    name=name,
                    backend="avfoundation",
                )
            )

    return _deduplicate(cameras), _deduplicate(microphones)


def _parse_avfoundation_video_sizes(output: str) -> tuple[tuple[int, int], ...]:
    """Parse the modes AVFoundation prints after an unsupported-size request."""

    sizes: list[tuple[int, int]] = []
    for width, height in re.findall(r"\b(\d{2,5})x(\d{2,5})@\[", output):
        size = (int(width), int(height))
        if size not in sizes:
            sizes.append(size)
    return tuple(sizes)


def _probe_avfoundation_video_sizes(
    ffmpeg_path: str,
    camera: CameraDevice,
) -> tuple[tuple[int, int], ...]:
    """Ask AVFoundation for a camera's modes without beginning capture."""

    output = _run_listing_command(
        [
            ffmpeg_path,
            "-hide_banner",
            "-loglevel",
            "info",
            "-f",
            "avfoundation",
            "-video_size",
            "1x1",
            "-framerate",
            "30",
            "-i",
            f"{camera.identifier}:none",
            "-t",
            "0.1",
            "-f",
            "null",
            "-",
        ],
        timeout=3.0,
    )
    return _parse_avfoundation_video_sizes(output)


def _parse_dshow_devices(
    output: str,
) -> tuple[list[CameraDevice], list[MicrophoneDevice]]:
    """Parse ``ffmpeg -f dshow -list_devices true`` output."""

    cameras: list[CameraDevice] = []
    microphones: list[MicrophoneDevice] = []
    pattern = re.compile(r'"(?P<name>.+?)"\s+\((?P<kind>video|audio)\)\s*$')

    for raw_line in output.splitlines():
        match = pattern.search(raw_line.strip())
        if not match:
            continue

        name = match.group("name")
        if match.group("kind") == "video":
            cameras.append(CameraDevice(identifier=name, name=name, backend="dshow"))
        else:
            microphones.append(MicrophoneDevice(identifier=name, name=name, backend="dshow"))

    return _deduplicate(cameras), _deduplicate(microphones)


def _parse_pulse_sources(output: str) -> list[MicrophoneDevice]:
    """Parse ``pactl list short sources`` output."""

    microphones: list[MicrophoneDevice] = []
    for raw_line in output.splitlines():
        fields = raw_line.split("\t")
        if len(fields) < 2:
            fields = raw_line.split()
        if len(fields) < 2:
            continue

        identifier = fields[1]
        # Monitor sources represent speaker output rather than a microphone.
        if identifier.endswith(".monitor"):
            continue
        microphones.append(
            MicrophoneDevice(identifier=identifier, name=identifier, backend="pulse")
        )

    return _deduplicate(microphones)


def _deduplicate(devices: list[Any]) -> list[Any]:
    """Preserve discovery order while removing duplicate backend identifiers."""

    seen: set[tuple[str, str]] = set()
    result: list[Any] = []
    for device in devices:
        key = (device.backend, device.identifier)
        if key not in seen:
            seen.add(key)
            result.append(device)
    return result


def _discover_with_ffmpeg(
    system: str, ffmpeg_path: str
) -> tuple[list[CameraDevice], list[MicrophoneDevice]]:
    """Discover FFmpeg-native devices for macOS or Windows."""

    if system == "darwin":
        output = _run_listing_command(
            [
                ffmpeg_path,
                "-hide_banner",
                "-f",
                "avfoundation",
                "-list_devices",
                "true",
                "-i",
                "",
            ]
        )
        cameras, microphones = _parse_avfoundation_devices(output)
        cameras_with_modes: list[CameraDevice] = []
        for camera in cameras:
            try:
                sizes = _probe_avfoundation_video_sizes(ffmpeg_path, camera)
            except (OSError, subprocess.TimeoutExpired):
                sizes = ()
            cameras_with_modes.append(
                replace(camera, supported_video_sizes=sizes)
            )
        return cameras_with_modes, microphones

    if system == "windows":
        output = _run_listing_command(
            [
                ffmpeg_path,
                "-hide_banner",
                "-list_devices",
                "true",
                "-f",
                "dshow",
                "-i",
                "dummy",
            ]
        )
        return _parse_dshow_devices(output)

    return [], []


def _discover_linux_cameras() -> list[CameraDevice]:
    """List Linux Video4Linux devices without opening them."""

    cameras: list[CameraDevice] = []
    for device_path in sorted(Path("/dev").glob("video*"), key=lambda path: path.name):
        name_path = Path("/sys/class/video4linux") / device_path.name / "name"
        try:
            hardware_name = name_path.read_text(encoding="utf-8").strip()
        except OSError:
            hardware_name = device_path.name

        cameras.append(
            CameraDevice(
                identifier=str(device_path),
                name=f"{hardware_name} ({device_path})",
                backend="v4l2",
            )
        )
    return cameras


def _discover_linux_microphones() -> list[MicrophoneDevice]:
    """List PulseAudio/PipeWire microphone sources when pactl is available."""

    pactl_path = shutil.which("pactl")
    if not pactl_path:
        return []
    try:
        return _parse_pulse_sources(
            _run_listing_command([pactl_path, "list", "short", "sources"])
        )
    except (OSError, subprocess.TimeoutExpired):
        return []


def _probe_opencv_cameras(max_camera_index: int) -> tuple[list[CameraDevice], str | None]:
    """Fallback camera probe used when native discovery finds nothing."""

    try:
        import cv2  # type: ignore[import-not-found]
    except ImportError:
        return [], "OpenCV is not installed, so fallback camera discovery was skipped."

    cameras: list[CameraDevice] = []
    for index in range(max_camera_index + 1):
        capture = cv2.VideoCapture(index)
        try:
            if capture.isOpened():
                cameras.append(
                    CameraDevice(
                        identifier=str(index),
                        name=f"Camera {index}",
                        backend="opencv",
                        opencv_index=index,
                    )
                )
        finally:
            capture.release()
    return cameras, None


def _discover_sounddevice_microphones() -> tuple[list[MicrophoneDevice], str | None]:
    """Fallback microphone discovery through PortAudio."""

    try:
        import sounddevice as sd  # type: ignore[import-not-found]
    except (ImportError, OSError) as error:
        return [], f"SoundDevice microphone discovery is unavailable: {error}"

    try:
        raw_devices = sd.query_devices()
        default_pair = sd.default.device
        default_input = int(default_pair[0]) if default_pair is not None else -1
    except (OSError, ValueError) as error:
        return [], f"Could not query microphones: {error}"

    microphones: list[MicrophoneDevice] = []
    for index, raw_device in enumerate(raw_devices):
        max_channels = int(raw_device.get("max_input_channels", 0))
        if max_channels <= 0:
            continue
        microphones.append(
            MicrophoneDevice(
                identifier=str(index),
                name=str(raw_device.get("name", f"Microphone {index}")),
                backend="portaudio",
                max_input_channels=max_channels,
                default_sample_rate=float(raw_device.get("default_samplerate", 0.0)) or None,
                is_default=index == default_input,
            )
        )
    return microphones, None


def discover_media_devices(max_camera_index: int = 10) -> DeviceCatalog:
    """Discover cameras and microphones without failing the Streamlit page.

    Args:
        max_camera_index: Highest OpenCV camera index to probe when native
            discovery is unavailable. The inclusive default probes indices
            0 through 10.
    """

    if max_camera_index < 0:
        raise ValueError("max_camera_index must be zero or greater")

    system = platform.system().lower()
    warnings: list[str] = []
    cameras: list[CameraDevice] = []
    microphones: list[MicrophoneDevice] = []
    ffmpeg_path = shutil.which("ffmpeg")

    if ffmpeg_path and system in {"darwin", "windows"}:
        try:
            cameras, microphones = _discover_with_ffmpeg(system, ffmpeg_path)
        except (OSError, subprocess.TimeoutExpired) as error:
            warnings.append(f"FFmpeg device discovery failed: {error}")
    elif system in {"darwin", "windows"}:
        warnings.append(
            "FFmpeg is not installed or not on PATH; recording-ready device names "
            "could not be discovered."
        )

    if system == "linux":
        cameras = _discover_linux_cameras()
        microphones = _discover_linux_microphones()

    if not cameras:
        cameras, warning = _probe_opencv_cameras(max_camera_index)
        if warning:
            warnings.append(warning)

    if not microphones:
        microphones, warning = _discover_sounddevice_microphones()
        if warning:
            warnings.append(warning)

    if not cameras:
        warnings.append("No camera was detected.")
    if not microphones:
        warnings.append("No microphone was detected.")

    return DeviceCatalog(
        cameras=tuple(_deduplicate(cameras)),
        microphones=tuple(_deduplicate(microphones)),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Print discovered devices as JSON for setup and troubleshooting."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--max-camera-index",
        type=int,
        default=10,
        help="highest OpenCV camera index to probe (default: 10)",
    )
    args = parser.parse_args(argv)
    catalog = discover_media_devices(max_camera_index=args.max_camera_index)
    print(json.dumps(catalog.to_dict(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
