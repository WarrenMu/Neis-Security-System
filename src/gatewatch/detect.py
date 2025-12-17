from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable, Optional

from loguru import logger


@dataclass(frozen=True)
class Detection:
    label: str
    confidence: float
    # xyxy in pixel coordinates
    x1: float
    y1: float
    x2: float
    y2: float


def _parse_csv_env(name: str) -> Optional[set[str]]:
    raw = os.getenv(name)
    if not raw:
        return None
    items = {s.strip() for s in raw.split(",") if s.strip()}
    return {s.lower() for s in items} if items else None


@dataclass
class YoloDetector:
    weights: str = "yolov8n.pt"
    conf: float = 0.25
    allow_labels: Optional[set[str]] = None

    def __post_init__(self) -> None:
        # Local import so import gatewatch works without ultralytics installed.
        from ultralytics import YOLO  # type: ignore

        self._model = YOLO(self.weights)
        # model.names: dict[int, str]
        self._names = getattr(self._model, "names", {})

    @classmethod
    def from_env(cls) -> "YoloDetector":
        weights = os.getenv("GATEWATCH_YOLO_WEIGHTS", "yolov8n.pt")
        conf = float(os.getenv("GATEWATCH_DET_CONF", "0.25"))
        allow = _parse_csv_env("GATEWATCH_DET_LABELS")
        return cls(weights=weights, conf=conf, allow_labels=allow)

    def detect(self, frame: object) -> list[Detection]:
        try:
            results = self._model.predict(frame, conf=self.conf, verbose=False)
        except Exception:
            logger.exception("YOLO predict failed")
            return []

        out: list[Detection] = []
        for r in results:
            boxes = getattr(r, "boxes", None)
            if boxes is None:
                continue

            # Ultralytics boxes give tensors; convert to python floats.
            try:
                cls_ids = boxes.cls.tolist() if boxes.cls is not None else []
                confs = boxes.conf.tolist() if boxes.conf is not None else []
                xyxys = boxes.xyxy.tolist() if boxes.xyxy is not None else []
            except Exception:
                logger.exception("Failed to parse YOLO result boxes")
                continue

            for cls_id, c, xyxy in zip(cls_ids, confs, xyxys):
                label = str(self._names.get(int(cls_id), str(cls_id))).lower()
                if self.allow_labels is not None and label not in self.allow_labels:
                    continue
                try:
                    x1, y1, x2, y2 = (float(xyxy[0]), float(xyxy[1]), float(xyxy[2]), float(xyxy[3]))
                except Exception:
                    continue
                out.append(Detection(label=label, confidence=float(c), x1=x1, y1=y1, x2=x2, y2=y2))

        return out


def any_label(detections: Iterable[Detection], labels: set[str]) -> bool:
    wanted = {l.lower() for l in labels}
    return any(d.label.lower() in wanted for d in detections)
