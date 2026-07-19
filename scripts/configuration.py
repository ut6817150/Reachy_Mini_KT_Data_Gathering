"""Validated researcher and participant configuration models."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import re
from typing import Any

from scripts.device_discovery import CameraDevice, MicrophoneDevice
from scripts.reachy_controller import ReachyConnectionConfig


PARTICIPANT_ID_PATTERN = re.compile(r"[A-Z0-9_-]{2,30}")


class VideoAspectRatio(str, Enum):
    """Researcher-selectable framing for previews and saved recordings."""

    NATIVE = "native"
    WIDESCREEN = "16:9"
    STANDARD = "4:3"

    @property
    def label(self) -> str:
        return {
            VideoAspectRatio.NATIVE: "Native camera ratio",
            VideoAspectRatio.WIDESCREEN: "16:9 widescreen",
            VideoAspectRatio.STANDARD: "4:3 standard",
        }[self]


def normalize_participant_id(value: str) -> str:
    """Return a filesystem-safe participant ID or raise ``ValueError``."""

    participant_id = value.strip().upper()
    if not PARTICIPANT_ID_PATTERN.fullmatch(participant_id):
        raise ValueError(
            "Participant ID must contain 2–30 letters, numbers, underscores, or hyphens."
        )
    return participant_id


@dataclass(frozen=True, slots=True)
class ResearcherConfiguration:
    """Technical settings verified before participant sessions begin."""

    reachy: ReachyConnectionConfig
    cameras: tuple[CameraDevice, ...]
    microphones: tuple[MicrophoneDevice, ...]
    default_camera: CameraDevice
    default_microphone: MicrophoneDevice
    video_aspect_ratio: VideoAspectRatio = VideoAspectRatio.WIDESCREEN

    def __post_init__(self) -> None:
        if isinstance(self.video_aspect_ratio, str):
            object.__setattr__(
                self,
                "video_aspect_ratio",
                VideoAspectRatio(self.video_aspect_ratio),
            )
        if not self.cameras:
            raise ValueError("At least one camera is required")
        if not self.microphones:
            raise ValueError("At least one microphone is required")
        if self.default_camera not in self.cameras:
            raise ValueError("The default camera must be in the available camera list")
        if self.default_microphone not in self.microphones:
            raise ValueError("The default microphone must be in the available microphone list")

    def to_dict(self) -> dict[str, Any]:
        return {
            "reachy": {
                "mode": self.reachy.mode.value,
                "wireless_host": self.reachy.wireless_host,
                "port": self.reachy.port,
                "timeout_seconds": self.reachy.timeout_seconds,
            },
            "cameras": [asdict(device) for device in self.cameras],
            "microphones": [asdict(device) for device in self.microphones],
            "default_camera": asdict(self.default_camera),
            "default_microphone": asdict(self.default_microphone),
            "video_aspect_ratio": self.video_aspect_ratio.value,
        }


@dataclass(frozen=True, slots=True)
class ParticipantConfiguration:
    """Participant-specific choices collected at the start of each session."""

    participant_id: str
    camera: CameraDevice
    microphone: MicrophoneDevice

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "participant_id", normalize_participant_id(self.participant_id)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "participant_id": self.participant_id,
            "camera": asdict(self.camera),
            "microphone": asdict(self.microphone),
        }
