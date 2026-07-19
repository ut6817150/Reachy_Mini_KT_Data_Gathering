"""Hardware-independent tests for device discovery output parsing."""

import json
import unittest

from scripts.device_discovery import (
    CameraDevice,
    DeviceCatalog,
    MicrophoneDevice,
    _parse_avfoundation_devices,
    _parse_avfoundation_video_sizes,
    _parse_dshow_devices,
    _parse_pulse_sources,
)


class AvFoundationParserTests(unittest.TestCase):
    def test_parses_cameras_and_microphones_but_not_screen_capture(self) -> None:
        output = """
[AVFoundation indev @ 0x123] AVFoundation video devices:
[AVFoundation indev @ 0x123] [0] FaceTime HD Camera
[AVFoundation indev @ 0x123] [1] External USB Camera
[AVFoundation indev @ 0x123] [2] Capture screen 0
[AVFoundation indev @ 0x123] AVFoundation audio devices:
[AVFoundation indev @ 0x123] [0] MacBook Pro Microphone
[AVFoundation indev @ 0x123] [1] USB Audio Device
"""

        cameras, microphones = _parse_avfoundation_devices(output)

        self.assertEqual([camera.identifier for camera in cameras], ["0", "1"])
        self.assertEqual(cameras[1].name, "External USB Camera")
        self.assertEqual([microphone.identifier for microphone in microphones], ["0", "1"])

    def test_parses_modes_and_prefers_a_supported_landscape_size(self) -> None:
        output = """
[in#0] Supported modes:
[in#0]   640x480@[15.000000 30.000000]fps
[in#0]   1080x1920@[15.000000 30.000000]fps
[in#0]   1280x720@[15.000000 30.000000]fps
[in#0]   1920x1080@[15.000000 30.000000]fps
"""

        sizes = _parse_avfoundation_video_sizes(output)
        camera = CameraDevice(
            "0",
            "Camera",
            "avfoundation",
            0,
            supported_video_sizes=sizes,
        )

        self.assertEqual(sizes, ((640, 480), (1080, 1920), (1280, 720), (1920, 1080)))
        self.assertEqual(camera.preferred_capture_size, (1920, 1080))

    def test_uses_largest_landscape_mode_when_widescreen_is_unavailable(self) -> None:
        camera = CameraDevice(
            "2",
            "Desk View",
            "avfoundation",
            2,
            supported_video_sizes=((1920, 1440),),
        )

        self.assertEqual(camera.preferred_capture_size, (1920, 1440))


class DirectShowParserTests(unittest.TestCase):
    def test_parses_video_and_audio_names(self) -> None:
        output = """
[dshow @ 000001] "Integrated Camera" (video)
[dshow @ 000001]   Alternative name "@device_pnp_camera"
[dshow @ 000001] "External Microphone" (audio)
"""

        cameras, microphones = _parse_dshow_devices(output)

        self.assertEqual(cameras[0].identifier, "Integrated Camera")
        self.assertEqual(microphones[0].identifier, "External Microphone")


class PulseParserTests(unittest.TestCase):
    def test_excludes_output_monitor_sources(self) -> None:
        output = """
45\talsa_output.pci.monitor\tPipeWire\ts32le 2ch 48000Hz\tSUSPENDED
46\talsa_input.usb_external_mic\tPipeWire\ts32le 1ch 48000Hz\tRUNNING
"""

        microphones = _parse_pulse_sources(output)

        self.assertEqual(len(microphones), 1)
        self.assertEqual(microphones[0].identifier, "alsa_input.usb_external_mic")


class DeviceCatalogTests(unittest.TestCase):
    def test_serializes_to_json(self) -> None:
        catalog = DeviceCatalog(
            cameras=(CameraDevice("0", "Camera", "avfoundation", 0),),
            microphones=(MicrophoneDevice("1", "Microphone", "avfoundation"),),
            warnings=("Example warning",),
        )

        result = catalog.to_dict()

        self.assertEqual(result["cameras"][0]["name"], "Camera")
        self.assertEqual(result["microphones"][0]["identifier"], "1")
        json.dumps(result)


if __name__ == "__main__":
    unittest.main()
