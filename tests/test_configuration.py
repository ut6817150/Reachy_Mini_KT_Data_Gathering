"""Tests for researcher and participant configuration validation."""

import unittest

from scripts.configuration import (
    ParticipantConfiguration,
    ResearcherConfiguration,
    VideoAspectRatio,
    normalize_participant_id,
)
from scripts.device_discovery import CameraDevice, MicrophoneDevice
from scripts.reachy_controller import ReachyConnectionConfig, RobotConnectionMode


CAMERA = CameraDevice("0", "USB Camera", "avfoundation", 0)
MICROPHONE = MicrophoneDevice("1", "USB Microphone", "avfoundation")


class ParticipantIdTests(unittest.TestCase):
    def test_normalizes_safe_participant_id(self) -> None:
        self.assertEqual(normalize_participant_id(" p-001 "), "P-001")

    def test_rejects_path_traversal_and_spaces(self) -> None:
        for value in ("../P001", "P 001", "A", ""):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_participant_id(value)


class ConfigurationTests(unittest.TestCase):
    def test_researcher_configuration_requires_defaults_in_device_lists(self) -> None:
        with self.assertRaises(ValueError):
            ResearcherConfiguration(
                reachy=ReachyConnectionConfig(),
                cameras=(CAMERA,),
                microphones=(MICROPHONE,),
                default_camera=CameraDevice("2", "Other", "avfoundation", 2),
                default_microphone=MICROPHONE,
            )

    def test_serializes_researcher_and_participant_separately(self) -> None:
        researcher = ResearcherConfiguration(
            reachy=ReachyConnectionConfig(mode=RobotConnectionMode.WIRELESS),
            cameras=(CAMERA,),
            microphones=(MICROPHONE,),
            default_camera=CAMERA,
            default_microphone=MICROPHONE,
            video_aspect_ratio=VideoAspectRatio.STANDARD,
        )
        participant = ParticipantConfiguration("p001", CAMERA, MICROPHONE)

        self.assertEqual(researcher.to_dict()["reachy"]["mode"], "wireless")
        self.assertEqual(researcher.to_dict()["video_aspect_ratio"], "4:3")
        self.assertEqual(participant.to_dict()["participant_id"], "P001")
        self.assertEqual(participant.to_dict()["camera"]["name"], "USB Camera")


if __name__ == "__main__":
    unittest.main()
