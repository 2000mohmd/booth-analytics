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
    def __init__(self, frame_rate: int = 30, lost_track_buffer_seconds: float = 3.0):
        """lost_track_buffer_seconds is how long ByteTrack keeps trying to re-associate a track
        that stopped getting detections before giving up and freeing its ID. supervision's
        ByteTrack default (30 frames = ~1s at 30fps) is tuned for dense multi-object benchmarks
        with mostly-continuous detections - too short for a real webcam/YOLO-nano feed, where a
        person can drop below the detector's confidence threshold for a second or two (motion
        blur, partial occlusion, awkward pose) and come right back. Too short a buffer means that
        single continuously-present visitor gets split into many separate tracks (and therefore
        many separate visits) - see services/ingestion/pipeline.py's TRACK_GRACE_SECONDS, which
        can't fix this on its own since a *new* track_id always starts a new visit regardless of
        how generous the grace period is.
        """
        import supervision as sv  # imported lazily - only needed at runtime

        self._tracker = sv.ByteTrack(
            frame_rate=frame_rate,
            lost_track_buffer=round(lost_track_buffer_seconds * frame_rate),
        )
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
