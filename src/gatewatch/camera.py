from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional, Protocol

from loguru import logger


class FrameSource(Protocol):
    def read(self) -> Optional[object]:  # object is typically a numpy ndarray
        """Return a frame, or None if unavailable."""

    def close(self) -> None: ...


def camera_source_from_env() -> str:
    return os.getenv("GATEWATCH_CAMERA_SOURCE", "0")


def camera_id_from_env() -> str:
    return os.getenv("GATEWATCH_CAMERA_ID", "gate-1")


@dataclass
class OpenCVCameraSource:
    source: str

    def __post_init__(self) -> None:
        # Local import so the repo can be imported without OpenCV installed.
        import cv2  # type: ignore

        src: object
        s = self.source.strip()
        src = int(s) if s.isdigit() else s

        self._cv2 = cv2
        self._cap = cv2.VideoCapture(src)
        if not self._cap.isOpened():
            logger.warning("OpenCV VideoCapture failed to open source: {}", self.source)

    def read(self) -> Optional[object]:
        ok, frame = self._cap.read()
        if not ok:
            return None
        return frame

    def close(self) -> None:
        try:
            self._cap.release()
        except Exception:
            logger.exception("Failed to release VideoCapture")
