from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Optional

from loguru import logger

from .detect import Detection, YoloDetector


def _normalize_plate(text: str) -> str:
    # Keep simple: uppercase alnum only.
    return re.sub(r"[^A-Z0-9]", "", text.upper())


@dataclass
class PlateRecognizer:
    """Optional license plate recognition.

    If `plate_detector` is None, this recognizer returns None (OCR disabled).
    """

    plate_detector: Optional[YoloDetector] = None
    ocr_langs: tuple[str, ...] = ("en",)

    def __post_init__(self) -> None:
        # Local import so import gatewatch works without easyocr installed.
        if self.plate_detector is None:
            self._reader = None
            return

        import easyocr  # type: ignore

        self._reader = easyocr.Reader(list(self.ocr_langs), gpu=False)

    @classmethod
    def from_env(cls) -> "PlateRecognizer":
        langs = tuple(s.strip() for s in os.getenv("GATEWATCH_OCR_LANGS", "en").split(",") if s.strip())
        plate_weights = os.getenv("GATEWATCH_PLATE_DET_WEIGHTS")
        if not plate_weights:
            return cls(plate_detector=None, ocr_langs=langs)

        conf = float(os.getenv("GATEWATCH_PLATE_DET_CONF", "0.25"))
        detector = YoloDetector(weights=plate_weights, conf=conf, allow_labels=None)
        return cls(plate_detector=detector, ocr_langs=langs)

    def recognize(self, frame: object) -> Optional[str]:
        if self.plate_detector is None or self._reader is None:
            return None

        dets = self.plate_detector.detect(frame)
        if not dets:
            return None

        # Pick highest-confidence bbox as plate region.
        best: Detection = max(dets, key=lambda d: d.confidence)
        try:
            # frame is a numpy array (H,W,C)
            roi = frame[int(best.y1) : int(best.y2), int(best.x1) : int(best.x2)]
        except Exception:
            logger.exception("Failed to crop plate ROI")
            return None

        try:
            # easyocr returns list of tuples: (bbox, text, confidence)
            results = self._reader.readtext(roi)  # type: ignore[union-attr]
        except Exception:
            logger.exception("EasyOCR readtext failed")
            return None

        if not results:
            return None

        # Choose highest OCR confidence.
        try:
            best_text = max(results, key=lambda t: float(t[2]))[1]
        except Exception:
            best_text = str(results[0][1])

        plate = _normalize_plate(str(best_text))
        return plate or None
