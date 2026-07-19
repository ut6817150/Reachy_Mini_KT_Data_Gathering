"""Hardware-independent tests for live-preview framing."""

import unittest

import numpy as np

from scripts.configuration import VideoAspectRatio
from scripts.live_preview import fit_frame_to_aspect_ratio


class LivePreviewFramingTests(unittest.TestCase):
    def test_native_ratio_preserves_the_original_frame(self) -> None:
        frame = np.ones((480, 640, 3), dtype=np.uint8)

        framed = fit_frame_to_aspect_ratio(frame, VideoAspectRatio.NATIVE)

        self.assertIs(framed, frame)

    def test_standard_ratio_pads_widescreen_without_cropping(self) -> None:
        frame = np.full((720, 1280, 3), 255, dtype=np.uint8)

        framed = fit_frame_to_aspect_ratio(frame, VideoAspectRatio.STANDARD)

        self.assertEqual(framed.shape, (960, 1280, 3))
        self.assertTrue(np.array_equal(framed[120:840], frame))
        self.assertEqual(int(framed[:120].max()), 0)


if __name__ == "__main__":
    unittest.main()
