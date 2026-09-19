"""YOLO person detector. Thin wrapper over ultralytics so callers don't touch the model API directly."""
from dataclasses import dataclass

import numpy as np

PERSON_CLASS_ID = 0  # COCO 'person'


@dataclass
class Detection:
    x1: float
    y1: float
    x2: float
    y2: float
    confidence: float

    @property
    def centroid(self) -> tuple[float, float]:
        return (self.x1 + self.x2) / 2, (self.y1 + self.y2) / 2


class PersonDetector:
    def __init__(self, weights_path: str, confidence_threshold: float = 0.4, device: str = "cuda"):
        from ultralytics import YOLO  # imported lazily - heavy dep, only needed at runtime

        self.model = YOLO(weights_path)
        self.confidence_threshold = confidence_threshold
        self.device = device

    def detect(self, frame: np.ndarray) -> list[Detection]:
        results = self.model.predict(
            frame, classes=[PERSON_CLASS_ID], conf=self.confidence_threshold,
            device=self.device, verbose=False,
        )[0]
        return [
            Detection(x1=float(b[0]), y1=float(b[1]), x2=float(b[2]), y2=float(b[3]), confidence=float(c))
            for b, c in zip(results.boxes.xyxy.tolist(), results.boxes.conf.tolist())
        ]
