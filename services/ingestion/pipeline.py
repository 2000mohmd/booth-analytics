"""Per-camera frame loop: detect -> track -> staff-filter -> zone/dwell update -> event store.

Overhead camera drives counting/dwell/zones (authoritative). Eye-level camera only samples
demographics for tracks the overhead camera has already marked as active stoppers - see
attach_demographics() in metrics_engine, called from the eye-level loop (Phase 3).
"""
import logging
import time

import cv2

from services.metrics_engine import store
from services.metrics_engine.dwell import VisitTracker
from services.perception.detector import PersonDetector
from services.perception.staff_filter import is_staff
from services.perception.tracker import PersonTracker

log = logging.getLogger(__name__)

TRACK_GRACE_SECONDS = 2.0       # how long a track may be unseen before its visit is finalized
OCCUPANCY_SAMPLE_EVERY_S = 5.0


def run_overhead_camera(
    source: str | int,
    detector: PersonDetector,
    tracker: PersonTracker,
    visit_tracker: VisitTracker,
    conn,
    marker_config: dict,
    debug_preview: bool = False,
):
    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        raise RuntimeError(f"could not open camera source: {source}")

    last_sample = 0.0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break

            now = time.time()
            detections = detector.detect(frame)
            tracks = tracker.update(detections, frame)

            for t in tracks:
                crop = frame[int(t.y1):int(t.y2), int(t.x1):int(t.x2)]
                staff = is_staff(crop, marker_config)
                cx, cy = t.centroid
                visit_tracker.update(str(t.track_id), cx, cy, now, is_staff=staff)

            for visit in visit_tracker.expire_stale(now, TRACK_GRACE_SECONDS):
                store.insert_visit(conn, visit)

            if now - last_sample >= OCCUPANCY_SAMPLE_EVERY_S:
                from services.metrics_engine.occupancy import sample_occupancy

                sample_occupancy(conn, visit_tracker.booth_id, visit_tracker)
                last_sample = now

            if debug_preview:
                for t in tracks:
                    cv2.rectangle(frame, (int(t.x1), int(t.y1)), (int(t.x2), int(t.y2)), (0, 255, 0), 2)
                    cv2.putText(frame, f"id={t.track_id}", (int(t.x1), int(t.y1) - 5),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
                cv2.imshow("overhead debug", frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
    finally:
        cap.release()
        if debug_preview:
            cv2.destroyAllWindows()
        # flush any still-active tracks so we don't lose partial visits on shutdown
        now = time.time()
        for visit in visit_tracker.expire_stale(now, grace_seconds=-1):
            store.insert_visit(conn, visit)
