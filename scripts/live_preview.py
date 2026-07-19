"""OpenCV-backed live camera previews with recording-matched framing."""

from __future__ import annotations

from typing import Any

import cv2  # type: ignore[import-not-found]
import numpy as np
import numpy.typing as npt

from scripts.configuration import VideoAspectRatio
from scripts.device_discovery import CameraDevice


class LivePreviewError(RuntimeError):
    """Raised when the selected camera cannot provide preview frames."""


def camera_preview_signature(camera: CameraDevice) -> tuple[str, str]:
    return camera.backend, camera.identifier


def fit_frame_to_aspect_ratio(
    frame: npt.NDArray[np.uint8],
    aspect_ratio: VideoAspectRatio,
) -> npt.NDArray[np.uint8]:
    """Pad a frame to the requested ratio without cropping its contents."""

    if aspect_ratio is VideoAspectRatio.NATIVE:
        return frame
    height, width = frame.shape[:2]
    if height <= 0 or width <= 0:
        raise LivePreviewError("The camera returned an invalid frame.")

    target_ratio = 16 / 9 if aspect_ratio is VideoAspectRatio.WIDESCREEN else 4 / 3
    current_ratio = width / height
    if abs(current_ratio - target_ratio) < 0.001:
        return frame

    if current_ratio > target_ratio:
        target_height = round(width / target_ratio)
        padding = target_height - height
        top = padding // 2
        bottom = padding - top
        left = right = 0
    else:
        target_width = round(height * target_ratio)
        padding = target_width - width
        left = padding // 2
        right = padding - left
        top = bottom = 0

    return cv2.copyMakeBorder(
        frame,
        top,
        bottom,
        left,
        right,
        cv2.BORDER_CONSTANT,
        value=(0, 0, 0),
    )


class LiveCameraPreview:
    """Own one camera until the app records or leaves a setup screen."""

    def __init__(self, camera: CameraDevice, *, capture_factory: Any = None) -> None:
        index = camera.opencv_index
        if index is None:
            try:
                index = int(camera.identifier)
            except ValueError as error:
                raise LivePreviewError(
                    f"{camera.label} does not expose an OpenCV camera index."
                ) from error

        factory = capture_factory or cv2.VideoCapture
        backend = {
            "avfoundation": getattr(cv2, "CAP_AVFOUNDATION", cv2.CAP_ANY),
            "dshow": getattr(cv2, "CAP_DSHOW", cv2.CAP_ANY),
            "v4l2": getattr(cv2, "CAP_V4L2", cv2.CAP_ANY),
        }.get(camera.backend, cv2.CAP_ANY)
        self.camera = camera
        self.signature = camera_preview_signature(camera)
        self._capture = factory(index, backend)
        if not self._capture.isOpened():
            self._capture.release()
            raise LivePreviewError(
                f"Could not open {camera.label}. Close other applications using the camera."
            )
        capture_size = camera.preferred_capture_size
        if capture_size is not None:
            self._capture.set(cv2.CAP_PROP_FRAME_WIDTH, capture_size[0])
            self._capture.set(cv2.CAP_PROP_FRAME_HEIGHT, capture_size[1])
        self._capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    def read(self, aspect_ratio: VideoAspectRatio) -> npt.NDArray[np.uint8]:
        available, frame = self._capture.read()
        if not available or frame is None:
            raise LivePreviewError(
                f"No frames received from {self.camera.label}. The camera may be in use."
            )
        framed = fit_frame_to_aspect_ratio(frame, aspect_ratio)
        return cv2.cvtColor(framed, cv2.COLOR_BGR2RGB)

    def close(self) -> None:
        self._capture.release()
