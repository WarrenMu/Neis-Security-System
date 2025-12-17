from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from loguru import logger

from .camera import OpenCVCameraSource, camera_id_from_env, camera_source_from_env
from .detect import YoloDetector, any_label
from .ocr import PlateRecognizer


class SubjectType(str, Enum):
    VEHICLE = "vehicle"
    PERSON = "person"
    OBJECT = "object"


class ArrivalType(str, Enum):
    OWNER = "owner"
    BOSS = "boss"
    VISITOR = "visitor"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class DetectionEvent:
    ts_utc: datetime
    subject: SubjectType
    arrival: ArrivalType
    plate_text: Optional[str] = None
    confidence: Optional[float] = None
    camera_id: str = "gate-1"


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class GateWatchPipeline:
    """Vision pipeline.

    Runs a small loop:
    - capture a frame (OpenCV)
    - run YOLO object detection (Ultralytics)
    - optionally recognize license plates (EasyOCR + optional plate-detector YOLO)
    - emit a `DetectionEvent` when a relevant object is detected

    Notes:
    - Plate OCR is disabled unless you set `GATEWATCH_PLATE_DET_WEIGHTS`.
    - This implementation emits at most one event per tick.
    """

    def __init__(
        self,
        whitelist: dict[str, str],
        *,
        camera_source: Optional[str] = None,
        camera_id: Optional[str] = None,
        detector: Optional[YoloDetector] = None,
        plate_recognizer: Optional[PlateRecognizer] = None,
    ):
        # whitelist maps plate_text -> role ("owner" or "boss")
        self.whitelist = {k.strip().upper(): v.strip().lower() for k, v in whitelist.items()}

        self.camera_id = camera_id or camera_id_from_env()

        self._camera_source = camera_source or camera_source_from_env()
        self._cap: Optional[OpenCVCameraSource] = None

        self._detector = detector
        self._plate = plate_recognizer

    @classmethod
    def from_env(cls, whitelist: dict[str, str]) -> "GateWatchPipeline":
        # Allow disabling YOLO if deps aren't available.
        enable_yolo = os.getenv("GATEWATCH_ENABLE_YOLO", "1").strip() not in {"0", "false", "no"}

        detector: Optional[YoloDetector] = None
        if enable_yolo:
            try:
                detector = YoloDetector.from_env()
            except Exception:
                logger.exception("Failed to initialize YOLO detector; pipeline will be inactive")

        plate: Optional[PlateRecognizer] = None
        try:
            plate = PlateRecognizer.from_env()
        except Exception:
            logger.exception("Failed to initialize plate recognizer; OCR disabled")
            plate = PlateRecognizer(plate_detector=None)

        return cls(
            whitelist=whitelist,
            detector=detector,
            plate_recognizer=plate,
        )

    def _ensure_capture(self) -> None:
        if self._cap is not None:
            return

        try:
            self._cap = OpenCVCameraSource(source=self._camera_source)
        except Exception:
            logger.exception("Failed to initialize camera capture")
            self._cap = None

    def close(self) -> None:
        if self._cap is not None:
            try:
                self._cap.close()
            finally:
                self._cap = None

    def process_one_tick(self) -> Optional[DetectionEvent]:
        """Return a DetectionEvent when something interesting happens."""

        if self._detector is None:
            return None

        self._ensure_capture()
        if self._cap is None:
            return None

        frame = self._cap.read()
        if frame is None:
            return None

        dets = self._detector.detect(frame)
        if not dets:
            return None

        # Default label sets (COCO-ish); override via env if desired.
        vehicle_labels = {
            s.strip().lower()
            for s in os.getenv("GATEWATCH_VEHICLE_LABELS", "car,truck,bus,motorcycle").split(",")
            if s.strip()
        }
        person_labels = {s.strip().lower() for s in os.getenv("GATEWATCH_PERSON_LABELS", "person").split(",") if s.strip()}

        # Emit one event per tick: prefer PERSON > VEHICLE.
        if any_label(dets, person_labels):
            conf = max((d.confidence for d in dets if d.label.lower() in person_labels), default=None)
            return DetectionEvent(
                ts_utc=now_utc(),
                subject=SubjectType.PERSON,
                arrival=ArrivalType.UNKNOWN,
                plate_text=None,
                confidence=conf,
                camera_id=self.camera_id,
            )

        if any_label(dets, vehicle_labels):
            conf = max((d.confidence for d in dets if d.label.lower() in vehicle_labels), default=None)

            plate_text = None
            if self._plate is not None:
                plate_text = self._plate.recognize(frame)

            arrival = ArrivalType.UNKNOWN
            if plate_text:
                arrival = self.classify_plate(plate_text)

            return DetectionEvent(
                ts_utc=now_utc(),
                subject=SubjectType.VEHICLE,
                arrival=arrival,
                plate_text=plate_text,
                confidence=conf,
                camera_id=self.camera_id,
            )

        return None

    def classify_plate(self, plate_text: str) -> ArrivalType:
        role = self.whitelist.get(plate_text.strip().upper())
        if role == "owner":
            return ArrivalType.OWNER
        if role == "boss":
            return ArrivalType.BOSS
        return ArrivalType.VISITOR
