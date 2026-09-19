"""ByteTrack wrapper via the `supervision` library - handles occlusion, no re-id model needed for v1."""
from dataclasses import dataclass

import numpy as np

from services.perception.detector import Detection


@dataclass
class Track:
    track_id: int
    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def centroid(self) -> tuple[float, float]:
        return (self.x1 + self.x2) / 2, (self.y1 + self.y2) / 2


class PersonTracker:
    def __init__(self):
        import supervision as sv  # imported lazily - only needed at runtime

        self._tracker = sv.ByteTrack()
        self._sv = sv

    def update(self, detections: list[Detection], frame: np.ndarray) -> list[Track]:
        sv = self._sv
        if detections:
            xyxy = np.array([[d.x1, d.y1, d.x2, d.y2] for d in detections], dtype=np.float32)
            confidence = np.array([d.confidence for d in detections], dtype=np.float32)
        else:
            xyxy = np.zeros((0, 4), dtype=np.float32)
            confidence = np.zeros((0,), dtype=np.float32)

        sv_detections = sv.Detections(xyxy=xyxy, confidence=confidence)
        tracked = self._tracker.update_with_detections(sv_detections)

        return [
            Track(track_id=int(tid), x1=float(b[0]), y1=float(b[1]), x2=float(b[2]), y2=float(b[3]))
            for b, tid in zip(tracked.xyxy.tolist(), tracked.tracker_id.tolist())
        ]
